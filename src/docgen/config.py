from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

import yaml
from pydantic import (
    BeforeValidator,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from yaml.nodes import MappingNode

from docgen.errors import InputError
from docgen.models import (
    Fact,
    Format,
    Genre,
    Identifier,
    LengthBand,
    Profile,
    Record,
    ScenarioFamily,
    Text,
)
from docgen.structure_models import (
    LAYOUT_CAPABILITIES,
    Complexity,
    LayoutName,
    StructureRecipe,
)


def share_number(value: object, info: ValidationInfo) -> Decimal:
    if info.mode == "json" and isinstance(value, str):
        try:
            value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Invalid stored decimal share.") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Shares must be finite numbers, not strings or Booleans.")
    number = Decimal(str(value))
    if not number.is_finite() or not Decimal(0) <= number <= Decimal(1):
        raise ValueError("Shares must be finite numbers in [0, 1].")
    return number


Share = Annotated[Decimal, BeforeValidator(share_number)]


def check_mix[Key: str](weights: Mapping[Key, Decimal]) -> None:
    total = sum(weights.values(), Decimal(0))
    if not weights or abs(total - Decimal(1)) > Decimal("1e-9"):
        raise ValueError("Shares must sum to 1 within 1e-9.")


class Topic(Record):
    id: Identifier
    description: Text
    share: Share | None = None


class ProviderConfig(Record):
    base_url: Text
    deployment: Text
    api: Literal["responses"] = "responses"

    @field_validator("base_url")
    @classmethod
    def azure_https_only(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme != "https" or not url.hostname
            or not url.hostname.endswith((".openai.azure.com", ".services.ai.azure.com"))
            or url.username or url.password or url.query or url.fragment
            or url.port not in (None, 443) or url.path != "/openai/v1/"
        ):
            raise ValueError("Use an Azure HTTPS OpenAI v1 base URL without credentials/query.")
        return value


class Limits(Record):
    concurrency: Annotated[StrictInt, Field(ge=1, le=16)] = 2
    request_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=600)] = 120
    transport_attempts_per_candidate: Annotated[StrictInt, Field(ge=1, le=5)] = 3
    max_requests: Annotated[StrictInt, Field(ge=1)] | None = None
    max_output_tokens_per_request: Annotated[StrictInt, Field(ge=1)] = 8000
    max_observed_total_tokens: Annotated[StrictInt, Field(ge=1)] = 250000


class QualityConfig(Record):
    legacy_optional_fields = ("word_band_tolerance",)
    max_candidates_per_item: Annotated[StrictInt, Field(ge=1, le=40)] = 3
    near_duplicate_jaccard: Annotated[Share, Field(gt=0)] = Decimal("0.85")
    language_confidence_min: Annotated[Share, Field(gt=0)] = Decimal("0.90")
    word_band_tolerance: Annotated[Share, Field(le=Decimal("0.05"))] | None = None


def default_genres() -> dict[Genre, Decimal]:
    return {
        "explainer": Decimal("0.25"), "procedure": Decimal("0.25"),
        "faq": Decimal("0.25"), "comparison": Decimal("0.25"),
    }


def default_lengths() -> dict[LengthBand, Decimal]:
    return {"short": Decimal("0.3"), "medium": Decimal("0.5"), "long": Decimal("0.2")}


def default_complexities() -> dict[Complexity, Decimal]:
    return {
        "simple": Decimal("0.30"), "moderate": Decimal("0.45"), "complex": Decimal("0.25"),
    }


class StructureConfig(Record):
    legacy_optional_fields = ("length_aware",)
    length_aware: StrictBool | None = None
    complexity_weights: dict[Complexity, Share] = Field(default_factory=default_complexities)
    recipe_weights: dict[Genre, dict[Complexity, dict[Identifier, Share]]] = Field(
        default_factory=dict
    )
    recipes: dict[Identifier, StructureRecipe] = Field(default_factory=dict)

    @model_validator(mode="after")
    def mixes(self) -> Self:
        check_mix(self.complexity_weights)
        for levels in self.recipe_weights.values():
            if not levels:
                raise ValueError("Recipe overrides must contain a complexity pool.")
            for weights in levels.values():
                check_mix(weights)
        return self


class GenerationConfig(Record):
    legacy_optional_fields = ("structure", "families")
    extension_replacements = {"structure": "structure_profile"}
    count: Annotated[StrictInt, Field(ge=1, le=1000)]
    topics: Annotated[tuple[Topic, ...], Field(min_length=1, max_length=1000)]
    language: Literal["pt", "en"] = "pt"
    locale: Literal["pt-BR", "en-US"] = "pt-BR"
    audience: Text = "general readers"
    genre_weights: dict[Genre, Share] = Field(default_factory=default_genres)
    length_weights: dict[LengthBand, Share] = Field(default_factory=default_lengths)
    structure_profile: Profile = "baseline"
    structure: StructureConfig | None = None
    required_terms: tuple[Text, ...] = ()
    style: Text | None = None
    shared_facts: tuple[Fact, ...] = Field(default=(), max_length=100)
    families: tuple[ScenarioFamily, ...] | None = None
    quality: QualityConfig = Field(default_factory=QualityConfig)
    limits: Limits = Field(default_factory=Limits)
    provider: ProviderConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def exclusive_structure_controls(cls, data: object) -> object:
        if (
            isinstance(data, dict) and data.get("structure") is not None
            and "structure_profile" in data
        ):
            raise ValueError("Do not combine structure_profile with structure recipes.")
        return data

    @model_validator(mode="after")
    def consistency(self) -> Self:
        if self.families is not None:
            if not self.families or self.count != len(self.families) * 6:
                raise ValueError("Family generation requires exactly six documents per family.")
            if len({family.id for family in self.families}) != len(self.families):
                raise ValueError("Family IDs must be unique.")
            labels = [entity.casefold() for family in self.families for entity in family.entities]
            if len(labels) != len(set(labels)):
                raise ValueError("Visible entities must be distinct across families.")
        if self.structure is not None and self.structure_profile != "baseline":
            raise ValueError("Do not combine structure_profile with structure recipes.")
        if len({topic.id for topic in self.topics}) != len(self.topics):
            raise ValueError("Topic IDs must be unique.")
        if len({fact.id for fact in self.shared_facts}) != len(self.shared_facts):
            raise ValueError("Shared fact IDs must be unique.")
        if (self.language, self.locale) not in {("pt", "pt-BR"), ("en", "en-US")}:
            raise ValueError("Language and locale profiles must match.")
        shares = {topic.id: topic.share for topic in self.topics if topic.share is not None}
        if shares:
            if len(shares) != len(self.topics):
                raise ValueError("Either all topics have shares or none do.")
            check_mix(shares)
        check_mix(self.genre_weights)
        check_mix(self.length_weights)
        return self

    @property
    def request_limit(self) -> int:
        return self.limits.max_requests or (
            self.count * self.quality.max_candidates_per_item
            * self.limits.transport_attempts_per_candidate
        )


class RenderConfig(Record):
    legacy_optional_fields = ("layout_weights",)
    extension_replacements = {"layout_weights": "layout_profile"}
    weights: dict[Format, Share]
    allocation: Literal["stratified"] = "stratified"
    layout_profile: Profile = "baseline"
    layout_weights: dict[Format, dict[LayoutName, Share]] | None = None

    @model_validator(mode="before")
    @classmethod
    def exclusive_layout_controls(cls, data: object) -> object:
        if (
            isinstance(data, dict) and data.get("layout_weights") is not None
            and "layout_profile" in data
        ):
            raise ValueError("Do not combine layout_profile with layout_weights.")
        return data

    @model_validator(mode="after")
    def valid_mix(self) -> Self:
        check_mix(self.weights)
        if self.layout_weights is not None:
            if self.layout_profile != "baseline":
                raise ValueError("Do not combine layout_profile with layout_weights.")
            if not self.layout_weights:
                raise ValueError("layout_weights must contain a format.")
            for format, weights in self.layout_weights.items():
                if self.weights.get(format, Decimal(0)) == 0:
                    raise ValueError("Layout controls require a positive-share output format.")
                check_mix(weights)
                if any(name not in LAYOUT_CAPABILITIES[format] for name in weights):
                    raise ValueError(f"Requested native layout is not supported for {format}.")
        return self


class Config(Record):
    schema_version: Literal["1"] = "1"
    seed: Annotated[StrictInt, Field(ge=0, le=2**63 - 1)] = 1729
    generation: GenerationConfig | None = None
    rendering: RenderConfig | None = None

    def require_phase(self, operation: str) -> None:
        if operation not in {"generate", "render", "run"}:
            raise InputError("Unknown phase.")
        if operation in {"generate", "run"} and self.generation is None:
            raise InputError("This phase requires generation configuration.")
        if operation in {"render", "run"} and self.rendering is None:
            raise InputError("This phase requires rendering configuration.")


class UniqueSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, int, float, bool, type(None))):
                raise InputError("Configuration keys must be scalar.")
            if key in result:
                raise InputError("Duplicate configuration keys are not permitted.")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_config(path: Path) -> Config:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueSafeLoader)
        return Config.model_validate(data)
    except ValidationError as exc:
        fields = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise InputError(f"Invalid configuration: {fields}") from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise InputError("Cannot load configuration; check file access and syntax.") from exc
