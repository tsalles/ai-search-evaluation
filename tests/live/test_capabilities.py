import json
from pathlib import Path

import pytest

from docgen.config import load_config
from docgen.doctor import doctor

pytestmark = pytest.mark.live


def test_selected_deployment_supports_the_required_wire_contract() -> None:
    config = load_config(Path(__file__).resolve().parents[2] / "examples" / "banking.yaml")
    result = doctor(config, live=True)
    print(json.dumps(result, ensure_ascii=False))
    assert result["status"] == "ready", result
    assert result["details"]["live_verified"] is True
    assert result["details"]["wire_schema_validated"] is True
    assert result["details"]["storage_requested"] is False
    assert result["details"]["max_live_requests"] == 1
    assert result["details"]["output_tokens_limit"] <= 2048
