import re
import unicodedata
from collections.abc import Collection

from pydantic import JsonValue

from docgen.errors import InputError
from docgen.evaluation.models import Query, QueryCohort, QueryTuning
from docgen.evaluation.profile_names import PROFILES as PROFILES
from docgen.evaluation.profile_names import Profile as Profile
from docgen.families import referenced_entities

SEMANTIC_PROFILES = frozenset((
    "semantic-hybrid", "entity-semantic", "semantic-hybrid-lexical",
    "semantic-hybrid-vector", "semantic-hybrid-wide",
    "semantic-bm25",
))
ENTITY_PROFILES = frozenset(("entity-hybrid", "entity-semantic"))
LEXICAL_PROFILES = frozenset(("bm25", "semantic-bm25"))


def scope(split: str, profile: Profile, *, cohort: QueryCohort | None = None) -> str:
    if profile not in PROFILES:
        raise InputError("Unsupported frozen retrieval profile.")
    if cohort is not None and cohort.split != split:
        raise InputError("The query cohort belongs to a different split.")
    base = split if profile == "hybrid" else split + ":" + profile
    return base if cohort is None else base + ":cohort-" + cohort.name


def report_suffix(split: str, profile: Profile, *, cohort: QueryCohort | None = None) -> str:
    scope(split, profile, cohort=cohort)
    base = split if profile == "hybrid" else split + "-" + profile
    return base if cohort is None else base + "-cohort-" + cohort.name


def profile_vector_k(profile: Profile, *, tuning: QueryTuning | None = None) -> int:
    if tuning is not None and tuning.vector_k is not None:
        return tuning.vector_k
    return 100 if profile in {"hybrid-wide", "semantic-hybrid-wide"} else 50


def retrieval_request(
    query: Query,
    vector: list[float] | None,
    *,
    profile: Profile,
    account_names: Collection[str] = (),
    tuning: QueryTuning | None = None,
) -> dict[str, JsonValue]:
    scope("development", profile)
    text = unicodedata.normalize("NFC", query.text)
    if (
        tuning is not None and tuning.analyzer not in {None, "default"}
        and (profile in ENTITY_PROFILES or profile == "pipeline-entity-hybrid")
    ):
        raise InputError("Analyzer comparison requires a content-only retrieval profile.")
    analyzer = tuning.analyzer if tuning else None
    content_field = "content"
    if analyzer is not None and analyzer != "default":
        content_field += "_" + analyzer
    body: dict[str, JsonValue] = {
        "search": text,
        "queryType": "simple",
        "searchMode": tuning.search_mode if tuning else "any",
        "searchFields": content_field,
        "select": "id",
        "top": 50,
        "minimumCoverage": 100,
    }
    if profile not in LEXICAL_PROFILES:
        if vector is None:
            raise InputError("The retrieval profile requires a shared query vector.")
        body["vectorFilterMode"] = "preFilter"
        body["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": [number for number in vector],
                "fields": "embedding",
                "k": profile_vector_k(profile, tuning=tuning),
                "weight": tuning.vector_weight
                if tuning is not None and tuning.vector_weight is not None else
                0.5 if profile in {"hybrid-lexical", "semantic-hybrid-lexical"} else
                2.0 if profile in {"hybrid-vector", "semantic-hybrid-vector"} else 1.0,
                "exhaustive": tuning.vector_exhaustive if tuning else False,
            }
        ]
    if profile == "vector":
        body.pop("search")
        body.pop("queryType")
        body.pop("searchMode")
        body.pop("searchFields")
    if profile in ENTITY_PROFILES:
        escaped = re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", text)
        names = sorted(referenced_entities(text, account_names))
        clauses = [
            '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"^4'
            for name in names
        ]
        body["search"] = "(" + escaped + ")" + (
            " OR (" + " OR ".join(clauses) + ")" if clauses else ""
        )
        body["queryType"] = "full"
        body["searchFields"] = "content,title,account_names"
        body["scoringProfile"] = "source-context"
    if profile == "pipeline-entity-hybrid":
        body["searchFields"] = "content,entity_data/entities"
        body["scoringProfile"] = "pipeline-entities"
    if profile in SEMANTIC_PROFILES:
        body["semanticQuery"] = text
        body["semanticConfiguration"] = (
            "source-context" if profile == "entity-semantic" else "content-only"
        )
        body["semanticErrorHandling"] = "fail"
    return body
