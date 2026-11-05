from typing import Literal, get_args

Profile = Literal[
    "hybrid", "bm25", "vector", "hybrid-lexical", "hybrid-vector",
    "entity-hybrid", "semantic-hybrid", "entity-semantic",
    "pipeline-entity-hybrid",
    "hybrid-wide", "semantic-hybrid-lexical", "semantic-hybrid-vector", "semantic-hybrid-wide",
    "semantic-bm25",
]
PROFILES: tuple[Profile, ...] = get_args(Profile)
