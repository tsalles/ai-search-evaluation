from typing import Annotated, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
)

Identifier = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9-]{0,63}$")
]
Text = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2048)
]
Genre = Literal["explainer", "procedure", "faq", "comparison"]
LengthBand = Literal["short", "medium", "long"]
Profile = Literal["baseline", "complex"]
Format = Literal["md", "html", "docx", "xlsx", "pptx", "pdf"]


class Record(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, allow_inf_nan=False
    )
    legacy_optional_fields: ClassVar[tuple[str, ...]] = ()
    extension_replacements: ClassVar[dict[str, str]] = {}

    @model_serializer(mode="wrap")
    def serialize_extensions(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data: dict[str, object] = handler(self)
        # Absent opt-in extensions must not change archived content hashes or fingerprints.
        for name in self.legacy_optional_fields:
            if data.get(name) is None:
                data.pop(name, None)
        for extension, legacy in self.extension_replacements.items():
            if (
                data.get(extension) is not None
                and data.get(legacy) == type(self).model_fields[legacy].default
            ):
                data.pop(legacy, None)
        return data
