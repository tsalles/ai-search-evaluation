import json

from docgen.evaluation.models import ExperimentConfig
from docgen.evaluation.state import Workspace, new_protocol
from docgen.facts import canonical_fact
from docgen.families import scoped_facts
from docgen.models import Content
from tests.fixtures.factories import structured_content
from tests.test_planning import configuration


def experiment_config() -> ExperimentConfig:
    data = configuration(12)
    data["generation"].update(
        language="pt",
        locale="pt-BR",
        structure={"length_aware": True},
        quality={"word_band_tolerance": 0.05},
        provider={
            "base_url": "https://offline.openai.azure.com/openai/v1/",
            "deployment": "offline-author",
        },
    )
    data["rendering"] = {
        "weights": {
            "pdf": 0.20,
            "docx": 0.20,
            "xlsx": 0.15,
            "pptx": 0.15,
            "html": 0.15,
            "md": 0.15,
        },
        "allocation": "stratified",
    }
    return ExperimentConfig.model_validate(
        {
            "family_count": 2,
            "generation": data["generation"],
            "rendering": data["rendering"],
            "split_weights": {"calibration": 0, "development": 0, "test": 1},
            "search": {
                "endpoint": "https://offline.search.windows.net",
                "ai_services_endpoint": "https://offline.cognitiveservices.azure.com",
                "embedding": {
                    "base_url": "https://offline.openai.azure.com/openai/v1/",
                    "deployment": "text-embedding-3-large",
                },
                "dimensions": 3,
            },
            "storage": {
                "resource_id": "/subscriptions/00000000-0000-0000-0000-000000000000/"
                "resourceGroups/offline/providers/Microsoft.Storage/storageAccounts/offline",
                "container": "documents",
            },
            "bootstrap_resamples": 100,
        }
    )


class FamilyProvider:
    def __init__(self):
        self.calls = []

    def generate(self, blueprint, config):
        self.calls.append(blueprint.content_id)
        content = structured_content(blueprint)
        facts = tuple(
            canonical_fact(fact, blueprint.locale) for fact in scoped_facts(blueprint, config)
        )
        data = json.loads(content.model_dump_json())
        paragraph = next(block for block in data["blocks"] if block["kind"] == "paragraph")
        paragraph["text"] = (
            " ".join(fact.entity + ": " + fact.display + "." for fact in facts)
            + " "
            + paragraph["text"]
        )
        paragraph["fact_refs"] = [fact.id for fact in facts]
        qualitative = next((fact for fact in facts if fact.kind == "text"), None)
        lists = [block for block in data["blocks"] if block["items"]]
        tables = [
            block["table"]
            for block in data["blocks"]
            if block["table"] and len(block["table"]["columns"]) >= 2
        ]
        if qualitative is not None and (lists or tables):
            paragraph["text"] = paragraph["text"].replace(
                qualitative.entity + ": " + qualitative.display + ". ",
                "",
                1,
            )
            paragraph["fact_refs"].remove(qualitative.id)
            if tables and (not lists or blueprint.ordinal % 2 == 0):
                table = tables[0]
                table["columns"][0]["name"] = "Conta"
                table["columns"][1]["name"] = "Regra aplicavel"
                table["rows"][0][0]["value"] = qualitative.entity
                table["rows"][0][1].update(
                    value=qualitative.value,
                    fact_id=qualitative.id,
                )
            else:
                item = lists[0]["items"][0]
                item["text"] = qualitative.entity + ": " + qualitative.display + ". " + item["text"]
                item["fact_refs"] = [qualitative.id]
        data["facts"] = [fact.model_dump(mode="json") for fact in facts]
        return Content.model_validate(data)


def fresh_workspace(tmp_path):
    return Workspace.create(tmp_path, new_protocol(experiment_config()))
