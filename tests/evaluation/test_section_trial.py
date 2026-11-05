import json
from contextlib import closing
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from docgen.cli import main
from docgen.errors import InputError, IntegrityError
from docgen.evaluation.section_trial import (
    SectionTrialSettings,
    run_section_trial,
    select_markdown_sources,
)
from docgen.evaluation.sectioning import heading_plan, markdown_source
from tests.test_azure_provider import ExpiringCredential

TEXT = "# Title\n\nPreface.\n\n## Conditions\n\nThe rule and its exception stay together.\n"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


def trial_settings(**kwargs):
    defaults = {
        "base_url": "https://offline.openai.azure.com/openai/v1/",
        "deployment": "gpt-5.4-mini", "subscription": SUBSCRIPTION, "sample_size": 1,
    }
    return SectionTrialSettings(**(defaults | kwargs))


def source_files(tmp_path, count=1):
    directory = tmp_path / "sources"
    directory.mkdir()
    for index in range(count):
        (directory / f"raw-{index:04d}.md").write_bytes(TEXT.encode())
    return directory


def model_body(request, *, damage=None):
    payload = json.loads(json.loads(request.content)["messages"][1]["content"])
    source = markdown_source("".join(block["text"] for block in payload["blocks"]))
    data = heading_plan(source).model_dump(mode="json")
    if damage is not None:
        damage(data)
    return {
        "id": "chat-test", "model": "gpt-5.4-mini-test",
        "choices": [{
            "message": {"role": "assistant", "content": json.dumps(data), "refusal": None},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def load(path):
    return json.loads(path.read_bytes())


def test_offline_trial_emits_controls_and_exact_requests_without_credentials_or_network(
    tmp_path, monkeypatch,
):
    directory = source_files(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Offline section trials cannot create an Azure credential or HTTP client.")

    monkeypatch.setattr("docgen.evaluation.section_trial.AzureCliCredential", forbidden)
    monkeypatch.setattr("docgen.evaluation.section_trial.httpx.Client", forbidden)
    result = run_section_trial(
        directory, tmp_path / "trials", SectionTrialSettings(sample_size=1),
    )
    trial = Path(result["trial_path"])
    assert result["status"] == "ready"
    assert result["accepted_model_plans"] == result["attempts"] == 0
    assert result["retrieval_quality"] == "not_measured"
    assert result["search_pipeline_integration"] == "not_executed"
    manifest = load(trial / "trial.json")
    assert manifest["source_metadata_uploaded"] is False
    assert manifest["azure_resources_created"] is False
    assert (trial / "document-0000" / "source.md").read_bytes() == TEXT.encode()
    controls = load(trial / "document-0000" / "controls.json")
    assert controls["baseline"]["section_count"] == 1
    assert controls["native_headings"]["section_count"] == 2
    assert all(value["exact_source_coverage"] for value in controls.values())
    assert not (trial / "document-0000" / "attempt-intent.json").exists()
    assert load(trial / "summary.json") == result


def test_live_local_trial_records_requests_raw_outputs_usage_and_separate_treatments(tmp_path):
    directory = source_files(tmp_path)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url == "https://offline.openai.azure.com/openai/v1/chat/completions"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["max_completion_tokens"] == 2048
        assert request.headers["authorization"].startswith("Bearer sentinel-token")
        return httpx.Response(200, json=model_body(request), headers={
            "x-request-id": "recorded-request", "x-ms-model-version": "version-one",
        })

    credential = ExpiringCredential()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(), live=True,
            credential=credential, http_client=client,
        )
    trial = Path(result["trial_path"])
    document = trial / "document-0000"
    assert result["status"] == "complete"
    assert result["attempts"] == result["accepted_model_plans"] == len(calls) == 1
    assert result["observed_total_tokens"] == 150
    assert result["unknown_usage_attempts"] == 0
    assert credential.closed is False
    assert credential.scopes == [("https://cognitiveservices.azure.com/.default",)]
    assert load(document / "attempt-intent.json")["attempt"] == 1
    assert load(document / "response-metadata.json")["request_id"] == "recorded-request"
    assert load(document / "response-body.json")["id"] == "chat-test"
    treatments = load(document / "llm-treatments.json")
    controls = load(document / "controls.json")
    assert treatments["metadata_only"]["chunks"] == controls["baseline"]["chunks"]
    assert treatments["metadata_only"]["title"] == "Title"
    assert treatments["metadata_only"]["section_metadata_enabled"] is False
    assert treatments["sections_only"]["title"] is None
    assert treatments["metadata_and_sections"]["title"] == "Title"
    assert all(treatment["exact_source_coverage"] for treatment in treatments.values())
    for path in document.iterdir():
        assert "sentinel-token" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("damage", [
    lambda p: p.update(title_block="b9999"),
    lambda p: p.update(source_sha256="f" * 64),
    lambda p: p["sections"].reverse(),
])
def test_bad_model_plans_are_retained_but_never_repaired_or_marked_accepted(tmp_path, damage):
    directory = source_files(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=model_body(request, damage=damage)),
    )) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    document = Path(result["trial_path"]) / "document-0000"
    assert result["status"] == "incomplete"
    assert result["outcomes"][0]["status"] == "rejected_output"
    assert result["accepted_model_plans"] == 0
    assert result["observed_total_tokens"] == 150
    assert (document / "response-body.json").is_file()
    assert not (document / "accepted-plan.json").exists()
    assert not (document / "llm-treatments.json").exists()


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500, 503])
def test_http_errors_do_not_retry_fall_back_or_dispatch_later_documents(tmp_path, status):
    directory = source_files(tmp_path, 3)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": {"message": "provider-secret-sentinel"}},
            headers={"Location": "https://unexpected.example"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(sample_size=3), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert len(calls) == result["attempts"] == 1
    assert result["status"] == "incomplete"
    assert result["unknown_usage_attempts"] == 1
    assert result["observed_total_tokens"] == 0
    assert [row["status"] for row in result["outcomes"]] == [
        "failed", "not_dispatched", "not_dispatched",
    ]
    assert "provider-secret-sentinel" not in json.dumps(result)


def test_transport_unknown_outcome_blocks_later_calls_and_is_preserved(tmp_path):
    directory = source_files(tmp_path, 2)

    def handler(request):
        raise httpx.ReadTimeout("unsafe transport detail", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(sample_size=2), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert result["blocked_reason"] == "transport_unknown_outcome"
    assert result["attempts"] == 1
    assert result["unknown_usage_attempts"] == 1
    assert "unsafe transport detail" not in json.dumps(result)
    assert result["outcomes"][1]["status"] == "not_dispatched"


@pytest.mark.parametrize("damage", [
    lambda r: r["usage"].update(total_tokens=149),
    lambda r: r.pop("usage"),
    lambda r: r["usage"].update(total_tokens=True),
    lambda r: r.update(choices=[]),
])
def test_invalid_envelope_or_usage_stops_the_trial_without_fabricated_totals(tmp_path, damage):
    directory = source_files(tmp_path, 2)

    def handler(request):
        body = model_body(request)
        damage(body)
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(sample_size=2), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert result["attempts"] == result["unknown_usage_attempts"] == 1
    assert result["observed_total_tokens"] == 0
    assert result["blocked_reason"] == "invalid_response"
    assert result["accepted_model_plans"] == 0


@pytest.mark.parametrize("damage,reason", [
    (lambda r: r["choices"][0]["message"].update(refusal="declined"), "refusal"),
    (lambda r: r["choices"][0].update(finish_reason="length"), "incomplete_response"),
    (lambda r: r["choices"][0]["message"].update(content=None), "incomplete_response"),
])
def test_refusals_and_truncations_are_explicit_failures_not_missing_titles(
    tmp_path, damage, reason,
):
    directory = source_files(tmp_path)

    def handler(request):
        body = model_body(request)
        damage(body)
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert result["outcomes"][0]["reason"] == reason
    assert result["observed_total_tokens"] == 150
    assert result["unknown_usage_attempts"] == 0
    assert result["status"] == "incomplete"


def test_token_budget_prevents_dispatch_instead_of_running_then_claiming_success(tmp_path):
    directory = source_files(tmp_path)

    def forbidden(request):
        pytest.fail("An unaffordable request was dispatched.")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials",
            trial_settings(max_observed_total_tokens=1), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert result["blocked_reason"] == "token_budget"
    assert result["attempts"] == result["accepted_model_plans"] == 0


def test_model_drift_is_detected_before_accepting_the_changed_model_plan(tmp_path):
    directory = source_files(tmp_path, 2)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        body = model_body(request)
        body["model"] = "model-one" if calls == 1 else "model-two"
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(sample_size=2), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert result["accepted_model_plans"] == 1
    assert result["blocked_reason"] == "model_drift"
    assert result["observed_total_tokens"] == 300


def test_live_gate_requires_explicit_subscription_endpoint_and_deployment(tmp_path):
    directory = source_files(tmp_path)
    with pytest.raises(InputError, match="subscription"):
        run_section_trial(
            directory, tmp_path / "trials", SectionTrialSettings(sample_size=1), live=True,
        )
    assert not (tmp_path / "trials").exists()


def test_sources_are_seeded_reproducible_raw_markdown_only_without_sidecar_access(tmp_path):
    directory = source_files(tmp_path, 4)
    (directory / "canonical.json").write_text("do not read", encoding="utf-8")
    (directory / "question.txt").write_text("do not read", encoding="utf-8")
    first = select_markdown_sources(directory, sample_size=2, seed=7)
    assert first == select_markdown_sources(directory, sample_size=2, seed=7)
    assert len(first) == 2
    assert all(path.suffix == ".md" for path in first)
    with pytest.raises(InputError, match="fewer"):
        select_markdown_sources(directory, sample_size=5, seed=7)


def test_unsafe_output_and_redirecting_http_clients_are_rejected(tmp_path):
    directory = source_files(tmp_path)
    with pytest.raises(InputError, match="outside"):
        run_section_trial(directory, directory / "trial", SectionTrialSettings(sample_size=1))
    with httpx.Client(follow_redirects=True) as client:
        with pytest.raises(InputError, match="redirect"):
            run_section_trial(
                directory, tmp_path / "trials", trial_settings(), http_client=client,
            )


def test_linked_source_directories_are_rejected(tmp_path):
    directory = source_files(tmp_path)
    link = tmp_path / "linked-sources"
    try:
        link.symlink_to(directory, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows identity cannot create symlinks.")
    with pytest.raises(IntegrityError, match="links"):
        select_markdown_sources(link, sample_size=1, seed=42)


def test_markdown_input_bytes_are_preserved_without_newline_normalization(tmp_path):
    directory = source_files(tmp_path)
    raw = "# T\u00edtulo\r\n\r\nPar\u00e1grafo.\r\n".encode()
    (directory / "raw-0000.md").write_bytes(raw)
    result = run_section_trial(
        directory, tmp_path / "trials", SectionTrialSettings(sample_size=1),
    )
    copied = Path(result["trial_path"]) / "document-0000" / "source.md"
    assert copied.read_bytes() == raw
    source = load(copied.with_name("source.json"))
    assert source["text"].encode() == raw


def test_local_trial_cli_does_not_require_or_open_a_search_workspace(tmp_path, capsys):
    directory = source_files(tmp_path)
    assert main([
        "experiment", "section-trial", "--source", str(directory),
        "--output", str(tmp_path / "trials"), "--sample-size", "1", "--json",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["operation"] == "experiment:section-trial"
    assert result["status"] == "ready"
    assert result["accepted_count"] == 0
    assert result["details"]["attempts"] == 0
    assert Path(result["reports"]["section_trial"]).is_file()


def test_interrupted_dispatched_attempt_is_recorded_unknown_not_undispatched(tmp_path):
    directory = source_files(tmp_path)

    def handler(request):
        raise KeyboardInterrupt

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(KeyboardInterrupt):
            run_section_trial(
                directory, tmp_path / "trials", trial_settings(), live=True,
                credential=ExpiringCredential(), http_client=client,
            )
    trial = next((tmp_path / "trials").iterdir())
    outcome = load(trial / "document-0000" / "outcome.json")
    assert outcome["status"] == "unknown"
    assert outcome["reason"] == "interrupted_after_dispatch"
    assert (trial / "document-0000" / "attempt-intent.json").exists()


def test_local_trial_cli_incomplete_status_has_a_visible_top_level_failure(
    tmp_path, monkeypatch, capsys,
):
    directory = source_files(tmp_path)
    client_type = httpx.Client
    with closing(client_type(transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={"error": {"message": "hidden"}}),
    ))) as client:
        monkeypatch.setattr(
            "docgen.evaluation.section_trial.AzureCliCredential",
            lambda **kwargs: closing(ExpiringCredential()),
        )
        monkeypatch.setattr("docgen.evaluation.section_trial.httpx.Client",
                            lambda **kwargs: client)
        assert main([
            "experiment", "section-trial", "--source", str(directory),
            "--output", str(tmp_path / "trials"), "--sample-size", "1",
            "--base-url", "https://offline.openai.azure.com/openai/v1/",
            "--deployment", "gpt-5.4-mini", "--subscription", SUBSCRIPTION, "--live", "--json",
        ]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete"
    assert result["failures"][0]["code"] == "section_trial_incomplete"
    assert Path(result["reports"]["section_trial"]).is_file()


def test_owned_cli_credential_is_pinned_to_the_requested_subscription_and_closed(
    tmp_path, monkeypatch,
):
    directory = source_files(tmp_path)
    credential = ExpiringCredential()
    options = []

    def credential_factory(**kwargs):
        options.append(kwargs)
        class ManagedCredential:
            def __enter__(self):
                return credential

            def __exit__(self, *args):
                credential.close()

        return ManagedCredential()

    monkeypatch.setattr(
        "docgen.evaluation.section_trial.AzureCliCredential", credential_factory,
    )
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=model_body(request)),
    )) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(), live=True, http_client=client,
        )
    assert result["status"] == "complete"
    assert options == [{"subscription": SUBSCRIPTION, "process_timeout": 60}]
    assert credential.closed is True


@pytest.mark.parametrize("subscription", ["-" * 36, "bad", "a" * 36])
def test_malformed_subscription_selectors_are_rejected(subscription):
    with pytest.raises(ValidationError):
        trial_settings(subscription=subscription)


def test_raw_string_model_output_is_rejected_after_preserving_observed_usage(tmp_path):
    directory = source_files(tmp_path)

    def handler(request):
        body = model_body(request)
        body["choices"][0]["message"]["content"] = '"not a structured plan"'
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert result["status"] == "incomplete"
    assert result["outcomes"][0]["status"] == "rejected_output"
    assert result["observed_total_tokens"] == 150


def test_input_token_limit_rejects_before_dispatch_without_truncating_the_source(tmp_path):
    directory = source_files(tmp_path)

    def forbidden(request):
        pytest.fail("The over-limit input must never be dispatched.")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(max_input_tokens=1024),
            live=True, credential=ExpiringCredential(), http_client=client,
        )
    assert result["attempts"] == 0
    assert result["outcomes"][0]["status"] == "rejected_input"
    assert result["outcomes"][0]["reason"] == "input_token_limit"


def test_observed_budget_overrun_is_reported_and_blocks_later_requests(tmp_path):
    directory = source_files(tmp_path, 2)

    def handler(request):
        body = model_body(request)
        body["usage"] = {
            "prompt_tokens": 100000, "completion_tokens": 50, "total_tokens": 100050,
        }
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_section_trial(
            directory, tmp_path / "trials", trial_settings(sample_size=2), live=True,
            credential=ExpiringCredential(), http_client=client,
        )
    assert result["status"] == "incomplete"
    assert result["attempts"] == 1
    assert result["blocked_reason"] == "token_budget"
    assert result["observed_total_tokens"] == 100050
    assert result["unknown_usage_attempts"] == 0


def test_invalid_utf8_or_unsupported_native_format_is_not_a_valid_empty_source(tmp_path):
    directory = source_files(tmp_path)
    (directory / "raw-0000.md").write_bytes(b"\xff")
    with pytest.raises(InputError, match="UTF-8"):
        run_section_trial(directory, tmp_path / "trials", SectionTrialSettings(sample_size=1))
    assert not (tmp_path / "trials").exists()
    pdf = tmp_path / "document.pdf"
    pdf.write_bytes(b"not used")
    with pytest.raises(InputError, match="fewer raw Markdown"):
        select_markdown_sources(pdf, sample_size=1, seed=42)


def test_bad_root_source_and_sample_bounds_are_rejected(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        select_markdown_sources(tmp_path / "missing", sample_size=1, seed=42)
    for sample_size in (True, 0, 25):
        with pytest.raises(InputError, match="sample size"):
            select_markdown_sources(tmp_path, sample_size=sample_size, seed=42)
