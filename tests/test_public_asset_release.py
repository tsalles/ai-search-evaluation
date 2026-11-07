"""Public-interface regression coverage for offline release boundaries."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from experimental_assets import extract_archive, release_assets, verify_archive
from public_asset_release import (
    Exporter,
    Policy,
    ReleaseError,
    file_hash,
    numeric_shape,
    safe_name,
    sha256,
)


def policy() -> Policy:
    return Policy(
        {"private-alias": "example-alias", r"C:\Users\researcher\project": "."},
        ["client-canary"],
        ["private-alias"],
    )


def test_json_preserves_values_shape_ranking_and_public_role_ids() -> None:
    role = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
    original = {
        "endpoint": "https://private-alias.search.windows.net",
        "subscription_id": "11111111-1111-1111-1111-111111111111",
        "roleDefinitionId": role,
        "rankings": [{"id": "a", "score": 0.127, "rank": 1}],
        "seed": 2026,
        "quota": 42,
        "null": None,
    }
    exporter = Exporter(policy())
    public = json.loads(exporter.json_data(json.dumps(original).encode()))
    assert numeric_shape(public) == numeric_shape(original)
    assert public["rankings"] == original["rankings"]
    assert public["roleDefinitionId"] == role
    assert public["subscription_id"] != original["subscription_id"]
    assert public["endpoint"] == "https://example-alias.search.windows.net"
    assert exporter.json_data(json.dumps(public).encode()) == json.dumps(public).encode()


@pytest.mark.parametrize("name", ["../escape", "C:/escape", "a\\escape", "/absolute", "NUL.txt"])
def test_rejects_unsafe_archive_paths(name: str) -> None:
    with pytest.raises(ReleaseError):
        safe_name(name)


def test_rejects_client_term_in_utf16_escaped_json() -> None:
    data = json.dumps({"text": "client-canary"}).encode("utf-16")
    with pytest.raises(ReleaseError, match="client"):
        Exporter(policy()).json_data(data)


def test_rejects_client_hidden_inside_an_escaped_json_string() -> None:
    data = json.dumps({"embedded": r'{"text":"\u0063lient-canary"}'}).encode()
    with pytest.raises(ReleaseError, match="client"):
        Exporter(policy()).json_data(data)


@pytest.mark.parametrize(
    "text",
    [
        "ClïentCanary",
        "CLI\u0301ENTCANARY",
        r"\u0043l\u00efentCanary",
        "CLIENTCANARY",
        "prefix_ClientCanary_deck.pptx",
        "ClientCanaryDeck",
    ],
)
def test_client_detection_preserves_unicode_normalization_coverage(text: str) -> None:
    with pytest.raises(ReleaseError, match="client"):
        Policy({}, ["clientcanary"], []).audit(text)


def test_client_matching_classifies_word_boundaries_without_anonymizing_prose() -> None:
    public_policy = Policy({}, ["ara"], [])
    public_policy.audit("comparará")
    public_policy.audit("COMPARARA")
    for text in ("ara_report", "AraReport", "customerAraToken", "fooARAbar"):
        with pytest.raises(ReleaseError, match="client"):
            public_policy.audit(text)
    with pytest.raises(ReleaseError, match="client"):
        public_policy.audit("comparara.json", filename=True)


def test_audit_reuse_is_invalidated_by_policy_changes_and_keeps_filename_checks() -> None:
    public_policy = Policy({}, [], [])
    public_policy.audit("canary")
    public_policy.audit("canary")
    public_policy.clients.append("canary")
    with pytest.raises(ReleaseError, match="client"):
        public_policy.audit("canary")
    public_policy = Policy({}, ["ara"], [])
    public_policy.audit("comparara")
    with pytest.raises(ReleaseError, match="client"):
        public_policy.audit("comparara", filename=True)
    identifier = "11111111-1111-1111-1111-111111111111"
    text = 'subscription_id="' + identifier + '"'
    public_policy.identities["historical-value"] = identifier
    public_policy.audit(text)
    public_policy.identities["historical-value"] = "22222222-2222-2222-2222-222222222222"
    with pytest.raises(ReleaseError, match="identity"):
        public_policy.audit(text)


def test_client_substring_in_emitted_filename_blocks_before_creating_output(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b'{"score":0.125}')
    output = tmp_path / "payload"
    with pytest.raises(ReleaseError, match="client"):
        Exporter(policy()).emit(source, "prefixclient-canarysuffix.json", output)
    assert not output.exists()
    assert source.read_bytes() == b'{"score":0.125}'


def test_review_projection_keeps_numerical_values_caveats_and_full_archive(tmp_path: Path) -> None:
    from summarize_experiment_release import SOURCE, create_review_report

    original = {
        "automated_evidence": {"default": {"score": 0.125, "queries": 20}},
        "evidence_caveat": "Automated assessment, not human certification.",
        "human_review_certified": False,
        "source_readback": {
            "cases": [{"score": 0.25}],
            "document_feature_donor": {"tokens": 42},
            "numeric_caveat": "No claim beyond the recorded evidence.",
        },
    }
    data = json.dumps(original).encode()
    archive = tmp_path / "experiments-001.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(SOURCE, data)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "verified_local_derivative",
                "historical_seal_semantics": "Historical hashes do not verify public bytes.",
                "producer_version_caveat": {"status": "unresolved_historical_producer_version"},
                "files": [
                    {
                        "path": SOURCE,
                        "bytes": len(data),
                        "sha256": sha256(data),
                        "archive": archive.name,
                    }
                ],
            }
        )
    )
    output = tmp_path / "review.json"
    create_review_report(manifest, tmp_path, output)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["results"]["automated_evidence"] == original["automated_evidence"]
    assert report["results"]["human_review_certified"] is False
    assert report["results"]["evidence_caveat"] == original["evidence_caveat"]
    assert report["results"]["source_readback"] == {
        "numeric_caveat": original["source_readback"]["numeric_caveat"]
    }
    assert report["public_source_sha256"] == sha256(data)
    with zipfile.ZipFile(archive) as stream:
        assert stream.read(SOURCE) == data
    with pytest.raises(ReleaseError, match="new destination"):
        create_review_report(manifest, tmp_path, output)
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(SOURCE, data + b" ")
    with pytest.raises(ReleaseError, match="checksum"):
        create_review_report(manifest, tmp_path, tmp_path / "tampered-review.json")


def test_refuses_output_inside_selected_source_before_creating_it(tmp_path: Path) -> None:
    from public_asset_release import run

    source = tmp_path / "original"
    source.mkdir()
    config = tmp_path / "scope.json"
    config.write_text(json.dumps({"roots": [{"source": str(source), "public": "."}]}))
    output = source / "unsafe-release"
    with pytest.raises(ReleaseError, match="source directory"):
        run(config, tmp_path / "unused-policy.json", output, tmp_path / "manifest.json")
    assert not output.exists()
    assert not list(source.iterdir())


def test_rejects_duplicate_json_keys_instead_of_discarding_data() -> None:
    with pytest.raises(ReleaseError, match="duplicate"):
        Exporter(policy()).json_data(b'{"score": 0.1, "score": 0.2}')


def test_does_not_anonymize_synthetic_business_account_paths() -> None:
    assert policy().text("/accounts/synthetic-account-42") == "/accounts/synthetic-account-42"


def test_private_cross_file_identifiers_are_consistently_mapped() -> None:
    public_policy = policy()
    identifier = "12345678-abcd-1234-abcd-123456789012"
    public_policy.learn('{"operator_object_id": "' + identifier + '"}')
    exporter = Exporter(public_policy)
    reference = json.loads(exporter.json_data(json.dumps({"reference": identifier}).encode()))
    context = json.loads(
        exporter.json_data(json.dumps({"operator_object_id": identifier}).encode())
    )
    assert reference["reference"] == context["operator_object_id"]
    assert reference["reference"] != identifier


def test_sqlite_overflow_framing_distinguishes_public_endpoint_fragments(tmp_path: Path) -> None:
    from public_asset_release import sqlite_overflow_pages

    root = tmp_path / "payload"
    root.mkdir()
    path = root / "ledger.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA page_size=512")
    connection.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, text TEXT, score REAL)")
    host = "https://example-resource-123abc.search.windows.net"
    for index in range(240):
        connection.execute(
            "INSERT INTO evidence VALUES (?, ?, ?)",
            (index, "x" * (index * 7) + " " + host + " " + "y" * 1800, 0.125),
        )
    connection.execute("CREATE INDEX evidence_text ON evidence(text)")
    connection.commit()
    roots = [1] + [
        row[0] for row in connection.execute("SELECT rootpage FROM sqlite_master WHERE rootpage>1")
    ]
    connection.close()
    data = path.read_bytes()
    page_size, overflow = sqlite_overflow_pages(data, roots)
    assert page_size == 512 and overflow
    exporter = Exporter(policy())
    exporter.entries = [{"path": path.name, "bytes": len(data), "sha256": sha256(data)}]
    exporter.verify(root)
    assert exporter.counts["classified_sqlite_overflow_endpoint_fragments"] > 0
    assert path.read_bytes() == data
    damaged = bytearray(data)
    number = next(iter(overflow))
    start = (number - 1) * page_size
    damaged[start : start + 4] = number.to_bytes(4, "big")
    with pytest.raises(ReleaseError, match="overflow"):
        sqlite_overflow_pages(bytes(damaged), roots)
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO evidence VALUES (?, ?, ?)", (999, "https://private.search.windows.net", 0.125)
    )
    connection.commit()
    connection.close()
    exporter.entries[0].update(bytes=path.stat().st_size, sha256=file_hash(path))
    with pytest.raises(ReleaseError, match="endpoint"):
        exporter.verify(root)


def test_sqlite_overflow_pointer_cannot_create_a_synthetic_client_name(tmp_path: Path) -> None:
    from public_asset_release import sqlite_overflow_pages

    path = tmp_path / "ledger.sqlite3"
    body = "neutral " * 100000
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA page_size=512")
        connection.execute("CREATE TABLE evidence(body TEXT)")
        connection.execute("INSERT INTO evidence VALUES (?)", (body,))
        roots = [1, 2]
    original = path.read_bytes()
    size, overflow = sqlite_overflow_pages(original, roots)
    protected = None
    for number in sorted(overflow):
        start = (number - 1) * size
        pointer = original[start : start + 4]
        fragment = original[start + 4 : start + 12].split(b" ", 1)[0]
        if (
            pointer[:3] == b"\0\0\0"
            and (65 <= pointer[3] <= 90 or 97 <= pointer[3] <= 122)
            and fragment.isalpha()
            and 2 <= len(fragment) < len("neutral")
        ):
            candidate = (pointer[3:] + fragment).decode("ascii")
            if candidate.casefold() not in body:
                protected = candidate
                break
    assert protected is not None
    public_policy = Policy({}, [protected], [])
    public_policy.audit(body)
    exporter = Exporter(public_policy)
    exporter.entries = [{"path": path.name, "bytes": len(original), "sha256": sha256(original)}]
    exporter.verify(tmp_path)
    assert path.read_bytes() == original
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO evidence VALUES (?)", (protected,))
    exporter.entries[0].update(bytes=path.stat().st_size, sha256=file_hash(path))
    with pytest.raises(ReleaseError, match="client"):
        exporter.verify(tmp_path)


def test_checkpoint_recovery_rechecks_archives_and_preserves_invariants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from public_asset_release import resume_verification, run

    source = tmp_path / "input" / "source.json"
    source.parent.mkdir()
    source.write_text(
        '{"subscription_id":"11111111-1111-1111-1111-111111111111","score":0.125}',
        encoding="utf-8",
    )
    config = tmp_path / "scope.json"
    config.write_text(
        json.dumps({"roots": [], "files": [{"source": str(source), "public": "result.json"}]}),
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps({"replacements": {}, "clients": [], "private_terms": []}), encoding="utf-8"
    )
    output = tmp_path / "release"
    manifest = tmp_path / "manifest.json"
    actual_verify = Exporter.verify

    def blocked_verify(*args: object, **kwargs: object) -> None:
        raise ReleaseError("synthetic final-validation interruption")

    monkeypatch.setattr(Exporter, "verify", blocked_verify)
    with pytest.raises(ReleaseError, match="blocked"):
        run(config, policy_path, output, manifest)
    assert not manifest.exists()
    checkpoint = json.loads((output / "verification-checkpoint.json").read_text())
    assert checkpoint["status"] == "unverified_local_derivative"
    assert checkpoint["invariants"]["json_numeric_and_null_values"] == 1
    monkeypatch.setattr(Exporter, "verify", actual_verify)
    archive_path = output / checkpoint["archives"][0]["name"]
    original = archive_path.read_bytes()
    archive_path.write_bytes(original + b"unclassified")
    with pytest.raises(ReleaseError, match="archive changed"):
        resume_verification(config, policy_path, output, manifest, ({}, {}))
    assert not manifest.exists()
    archive_path.write_bytes(original)
    monkeypatch.setattr(Exporter, "verify", blocked_verify)
    with pytest.raises(ReleaseError, match="checkpoint verification blocked"):
        resume_verification(config, policy_path, output, manifest, ({}, {}))
    failure = json.loads((output / "BLOCKED.json").read_text())
    assert failure["reason"] == "synthetic final-validation interruption"
    assert not manifest.exists()
    monkeypatch.setattr(Exporter, "verify", actual_verify)
    resume_verification(config, policy_path, output, manifest, ({}, {}))
    report = json.loads(manifest.read_text())
    assert report["status"] == "verified_local_derivative"
    assert report["invariants"] == checkpoint["invariants"]
    assert report["counts"]["verified_final_archive_files"] == 1
    assert not (output / "BLOCKED.json").exists()
    assert source.read_text().endswith('"score":0.125}')
    configured = config.read_text()
    config.write_text(configured + "\n")
    with pytest.raises(ReleaseError, match="input changed"):
        resume_verification(config, policy_path, output, manifest, ({}, {}))


def test_linked_frozen_distribution_source_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "package.whl"
    source.write_bytes(b"not opened")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == source or original(path))
    with pytest.raises(ReleaseError, match="distribution source"):
        Exporter(policy()).frozen_distribution(source, "package.whl", tmp_path / "payload")
    assert source.read_bytes() == b"not opened"
    assert not (tmp_path / "payload").exists()


def test_parallel_checkpoint_resume_rechecks_complete_scope_before_clearance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    import public_asset_release

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for index in range(2):
        (inputs / f"{index}.json").write_text(json.dumps({"score": index + 0.125}))
    config = tmp_path / "scope.json"
    config.write_text(json.dumps({"roots": [{"source": str(inputs), "public": "evaluations"}]}))
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({"replacements": {}, "clients": [], "private_terms": []}))
    output = tmp_path / "release"
    manifest = tmp_path / "manifest.json"
    monkeypatch.setattr(public_asset_release, "ProcessPoolExecutor", ThreadPoolExecutor)
    original_verify = Exporter.verify

    def interrupted(*args: object, **kwargs: object) -> None:
        raise ReleaseError("synthetic validation interruption")

    monkeypatch.setattr(Exporter, "verify", interrupted)
    with pytest.raises(ReleaseError, match="parallel export blocked"):
        public_asset_release.run_parallel(config, policy_path, output, manifest, 2)
    assert not manifest.exists()
    assert len(list(output.glob("part-*/verification-checkpoint.json"))) == 2
    monkeypatch.setattr(Exporter, "verify", original_verify)
    public_asset_release.run_parallel(config, policy_path, output, manifest, 2, resume=True)
    report = json.loads(manifest.read_text())
    assert report["selected_inputs"]["direct_files"] == 2
    assert report["counts"]["verified_final_archive_files"] == 2
    assert report["invariants"]["json_numeric_and_null_values"] == 2
    assert len(report["archives"]) == 2
    assert not list(output.rglob("BLOCKED.json"))
    assert not list(output.rglob("verification-checkpoint.json"))
    release_assets(manifest, output, download=False, extract=tmp_path / "restored", workers=2)
    assert len(list((tmp_path / "restored" / "evaluations").glob("*.json"))) == 2
    with pytest.raises(ReleaseError, match="uncleared"):
        public_asset_release.run_parallel(config, policy_path, output, manifest, 2, resume=True)


def test_python_credential_variable_reference_is_not_a_literal_secret() -> None:
    source = (
        b"def call(content_understanding_api_key):\n"
        b" return client(api_key=content_understanding_api_key)\n"
    )
    assert Exporter(policy()).transform(source, "producer.py") == source
    with pytest.raises(ReleaseError, match="credential"):
        policy().audit(source.decode())


def test_python_resource_substitution_preserves_names_and_numeric_literals() -> None:
    public_policy = policy()
    public_policy.resources["account"] = "example-resource-123abc"
    source = b"def call(account):\n return account, 42, 'https://account.search.windows.net'\n"
    exporter = Exporter(public_policy)
    public = exporter.transform(source, "producer.py")
    assert b"def call(account)" in public
    assert b"return account, 42," in public
    assert b"https://example-resource-123abc.search.windows.net" in public
    assert exporter.counts["python_numeric_and_null_constants"] == 1


def test_trec_preserves_numeric_tokens_and_ranking_order() -> None:
    source = b"q1 Q0 doc-a 1 0.125 private-alias\nq1 Q0 doc-b 2 1.25e-2 private-alias\n"
    exporter = Exporter(policy())
    public = exporter.transform(source, "ranking.trec")
    assert public == source.replace(b"private-alias", b"example-alias")
    assert exporter.counts["plain_text_numeric_tokens"] == 4
    with pytest.raises(ReleaseError, match="numeric token"):
        Exporter(Policy({"0.125": "0.5"}, [], [])).transform(source, "ranking.trec")


def test_short_malformed_binary_test_literal_is_preserved_and_audited() -> None:
    source = b"payload = b'\\xff\\xfeinvalid'\n"
    assert Exporter(policy()).transform(source, "fixture.py") == source
    with pytest.raises(ReleaseError, match="credential"):
        Exporter(policy()).transform(b"api_key=b'short-secret'\n", "producer.py")
    with pytest.raises(ReleaseError, match="credential"):
        Exporter(policy()).transform(b"def call(api_key=b'short-secret'): pass\n", "producer.py")


@pytest.mark.parametrize(
    "source",
    [
        "api_key = 'abcdefghijklmnopqrstuvwxyz0123456789'",
        "def f(abcdefghijklmnopqrstuvwxyz0123456789):\n"
        " return 'api_key=abcdefghijklmnopqrstuvwxyz0123456789'",
        "def f(content_understanding_api_key):\n"
        " client(api_key=content_understanding_api_key)\n"
        "api_key='abcdefghijklmnpqrstuvwxyz0123456789'",
    ],
)
def test_python_reference_exception_never_permits_literal_credentials(source: str) -> None:
    with pytest.raises(ReleaseError, match="credential"):
        Exporter(policy()).transform(source.encode(), "producer.py")


@pytest.mark.parametrize(
    ("name", "xml"),
    [
        ("ppt/commentAuthors.xml", '<cmAuthor id="0" name="Private Researcher" initials="PR"/>'),
        (
            "xl/comments/comment1.xml",
            "<comments><authors><author>Private Researcher</author></authors></comments>",
        ),
        (
            "xl/persons/person.xml",
            '<person displayName="Private Researcher" userId="researcher@example.org"/>',
        ),
    ],
)
def test_office_comment_person_metadata_becomes_generic(name: str, xml: str) -> None:
    exporter = Exporter(policy())
    public = exporter.xml_data(xml.encode(), name, office=True)
    assert b"Private Researcher" not in public
    assert b"researcher@example.org" not in public
    assert b"Public Study" in public
    assert exporter.xml_data(public, name, office=True) == public


def test_rejects_client_split_across_xml_nodes() -> None:
    data = b"<root><text>client-</text><text>canary</text></root>"
    with pytest.raises(ReleaseError, match="client"):
        Exporter(policy()).xml_data(data, "document.xml", office=True)


def test_nested_zip_names_and_comments_are_sanitized() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.comment = b"private-alias evidence"
        member = zipfile.ZipInfo("private-alias.json")
        member.comment = b"private-alias provenance"
        archive.writestr(member, b'{"score": 0.125}')
    exporter = Exporter(policy())
    public = exporter.transform(buffer.getvalue(), "evidence.zip")
    with zipfile.ZipFile(io.BytesIO(public)) as archive:
        assert archive.namelist() == ["example-alias.json"]
        assert archive.comment == b"example-alias evidence"
        assert archive.getinfo("example-alias.json").comment == b"example-alias provenance"
    assert exporter.transform(public, "evidence.zip") == public


@pytest.mark.parametrize("location", ["archive", "member"])
def test_client_in_zip_comments_blocks_release(location: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        member = zipfile.ZipInfo("data.json")
        if location == "archive":
            archive.comment = b"client-canary"
        else:
            member.comment = b"client-canary"
        archive.writestr(member, b"{}")
    with pytest.raises(ReleaseError, match="client"):
        Exporter(policy()).transform(buffer.getvalue(), "evidence.zip")


def test_zip_unclassified_preamble_or_trailer_blocks_release() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.json", b"{}")
    for data in (b"opaque" + buffer.getvalue(), buffer.getvalue() + b"opaque"):
        with pytest.raises(ReleaseError, match="unclassified ZIP"):
            Exporter(policy()).transform(data, "evidence.zip")


def test_preserves_namespace_bound_only_by_office_compatibility_attribute() -> None:
    from xml.etree import ElementTree

    data = (
        b'<w:document xmlns:w="urn:word" xmlns:mc="urn:compatibility" '
        b'xmlns:w14="urn:word14" mc:Ignorable="w14"><w:text>'
        b"private-alias</w:text></w:document>"
    )
    public = Exporter(policy()).xml_data(data, "document.xml", office=True)
    namespaces = dict(
        declaration
        for _, declaration in ElementTree.iterparse(io.BytesIO(public), events=("start-ns",))
    )
    assert namespaces["w14"] == "urn:word14"
    assert ElementTree.fromstring(public).attrib["{urn:compatibility}Ignorable"] == "w14"
    assert b"example-alias" in public


def test_rejects_unbound_office_namespace_and_preserves_dublin_core_type() -> None:
    from public_asset_release import validate_xml_qnames

    invalid = (
        b'<root xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        b'mc:Ignorable="w14"/>'
    )
    with pytest.raises(ReleaseError, match="unbound"):
        validate_xml_qnames(invalid)
    original = (
        b'<root xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        b'xmlns:dcterms="http://purl.org/dc/terms/">'
        b'<created xsi:type="dcterms:W3CDTF">2026-11-04</created>'
        b"<creator>Private author</creator></root>"
    )
    public = Exporter(policy()).xml_data(original, "core.xml", office=True)
    assert b"xmlns:dcterms=" in public
    validate_xml_qnames(public)


def test_rejects_secret_and_unknown_binary() -> None:
    exporter = Exporter(policy())
    with pytest.raises(ReleaseError, match="credential"):
        exporter.transform(b"AccountKey=" + b"a" * 48, "data.txt")
    with pytest.raises(ReleaseError, match="unsupported"):
        exporter.transform(b"\x00\x99", "opaque.bin")
    with pytest.raises(ReleaseError, match="credential"):
        exporter.json_data(json.dumps({"AZURE_AI_SEARCH_API_KEY": "a" * 48}).encode())
    with pytest.raises(ReleaseError, match="credential"):
        exporter.json_data(b'{"password":"abc"}')
    with pytest.raises(ReleaseError, match="credential"):
        exporter.transform(b'AZURE_AI_SEARCH_API_KEY="abc"', "producer.py")
    assert exporter.transform(b'api_key="<redacted>"\n', "config.txt") == b'api_key="<redacted>"\n'


def test_credential_hint_preserves_detection_of_every_credential_family() -> None:
    candidates = [
        "-----BEGIN " + prefix + "PRIVATE KEY-----" for prefix in ("", "RSA ", "EC ", "OPENSSH ")
    ]
    candidates.extend("gh" + kind + "_" + "x" * 40 for kind in "pousr")
    candidates.extend(
        [
            "github_pat_" + "x" * 48,
            "eyJ" + "x" * 16 + "." + "x" * 16 + "." + "x" * 16,
            "Bearer " + "x" * 40,
            "?sig=" + "x" * 40,
            "&sig=" + "x" * 40,
            'api_key="abc"',
        ]
    )
    for key in (
        "AccountKey",
        "SharedAccessSignature",
        "api_key",
        "client-secret",
        "subscriptionkey",
        "access_token",
        "refresh-token",
        "password",
    ):
        candidates.append("AZURE_" + key + "=" + "x" * 48)
    for candidate in candidates:
        with pytest.raises(ReleaseError, match="credential"):
            policy().audit(candidate)
    policy().audit(json.dumps([0.125, -0.5, 0, None] * 10000))


def test_preserves_and_sanitizes_framed_printer_metadata_without_opaque_fallback() -> None:
    import plistlib
    import struct

    sections = (
        {
            "DeviceName": "private-alias",
            "Source": r"C:\Users\researcher\project\doc",
            "PageWidth": 595.25,
        },
        {"Copies": 1, "Duplex": False},
    )
    data = struct.pack("<I", 2)
    for kind, section in enumerate(sections, 1):
        value = plistlib.dumps(section, sort_keys=False)
        data += struct.pack("<II", kind, len(value)) + value
    exporter = Exporter(policy())
    public = exporter.transform(data, "ppt/printerSettings/printerSettings1.bin")
    assert len(public) != len(data)
    offset = 4
    for original in sections:
        _, size = struct.unpack_from("<II", public, offset)
        offset += 8
        value = plistlib.loads(public[offset : offset + size])
        offset += size
        assert numeric_shape(original) == numeric_shape(value)
    assert offset == len(public)
    assert exporter.transform(public, "ppt/printerSettings/printerSettings1.bin") == public
    with pytest.raises(ReleaseError, match="framing"):
        exporter.transform(b"opaque", "ppt/printerSettings/printerSettings1.bin")


def test_keeps_unmodified_qrels_and_rankings_byte_identical() -> None:
    data = b"q1 Q0 doc-a 1 0.7321428571 baseline\nq1 Q0 doc-b 2 -0.0123 baseline\n"
    assert Exporter(policy()).transform(data, "ranking.trec") == data


def test_identical_content_reuse_preserves_physical_file_invariant_counts(tmp_path: Path) -> None:
    exporter = Exporter(policy())
    source = tmp_path / "source.json"
    source.write_bytes(b'{"label":"private-alias","scores":[0.125,42,null]}')
    output = tmp_path / "payload"
    exporter.emit(source, "first.json", output)
    original_invariants = (exporter.json_documents, exporter.numeric_values)
    exporter.emit(source, "second.json", output)
    assert (output / "first.json").read_bytes() == (output / "second.json").read_bytes()
    assert (exporter.json_documents, exporter.numeric_values) == tuple(
        value * 2 for value in original_invariants
    )
    assert exporter.counts["reused_emitted_source_contents"] == 1
    assert exporter.counts["format:.json"] == 2
    assert exporter.counts["distinct_cached_source_contents"] == 1
    assert exporter.counts["distinct_transformed_source_contents"] == 1
    exporter.verify(output)
    assert exporter.counts["verified_export_files"] == 2


def test_accepts_long_nonendpoint_tokens_without_changing_them() -> None:
    value = "a" * 100000
    assert policy().text(value) == value


def test_pdf_metadata_cleanup_preserves_experimental_text() -> None:
    from pypdf import PdfReader
    from reportlab.pdfgen.canvas import Canvas

    output = io.BytesIO()
    canvas = Canvas(output)
    canvas.setAuthor("Private author")
    canvas.drawString(10, 800, "Synthetic score 0.125; quota 42; seed 2026")
    canvas.save()
    original = output.getvalue()
    public = Exporter(policy()).transform(original, "corpus.pdf")
    reader = PdfReader(io.BytesIO(public))
    assert reader.metadata.author == "Public Study"
    assert reader.pages[0].extract_text() == PdfReader(io.BytesIO(original)).pages[0].extract_text()


def test_pdf_unicode_map_is_declarative_and_rejects_encoded_client_text() -> None:
    exporter = Exporter(policy())
    prefix = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def "
        b"/CMapName /AAAAAA+Synthetic def /CMapType 2 def "
        b"1 begincodespacerange <00> <FF> endcodespacerange "
    )
    suffix = b" endcmap CMapName currentdict /CMap defineresource pop end end"
    exporter.audit_pdf_unicode_map(prefix + b"1 beginbfchar <01> <0041> endbfchar" + suffix)
    encoded = "client-canary".encode("utf-16-be").hex().encode()
    with pytest.raises(ReleaseError, match="client"):
        exporter.audit_pdf_unicode_map(
            prefix + b"1 beginbfchar <01> <" + encoded + b"> endbfchar" + suffix
        )
    with pytest.raises(ReleaseError, match="operator"):
        exporter.audit_pdf_unicode_map(prefix + b"(file) run" + suffix)


def test_rejects_opaque_and_invalid_truetype_font_programs() -> None:
    exporter = Exporter(policy())
    with pytest.raises(ReleaseError, match="font"):
        exporter.audit_truetype_font(b"opaque")
    with pytest.raises(ReleaseError, match="directory"):
        exporter.audit_truetype_font(b"\x00\x01\x00\x00\xff\xff" + b"\x00" * 8)


def test_truetype_name_records_are_audited_without_changing_numeric_tables() -> None:
    import struct

    def font(name: str) -> bytes:
        head = bytearray(54)
        struct.pack_into(">I", head, 12, 0x5F0F3CF5)
        hhea = bytearray(36)
        struct.pack_into(">H", hhea, 34, 1)
        encoded = name.encode("utf-16-be")
        names = (
            struct.pack(">HHH", 0, 1, 18)
            + struct.pack(">HHHHHH", 3, 1, 0x409, 1, len(encoded), 0)
            + encoded
        )
        tables = {
            b"head": bytes(head),
            b"hhea": bytes(hhea),
            b"hmtx": struct.pack(">HH", 500, 0),
            b"maxp": struct.pack(">IH", 0x10000, 1),
            b"loca": b"\0" * 4,
            b"glyf": b"",
            b"name": names,
            b"cmap": struct.pack(">HH", 0, 0),
            b"post": struct.pack(">I", 0x30000) + b"\0" * 28,
        }
        directory = struct.pack(">IHHHH", 0x10000, len(tables), 0, 0, 0)
        contents = b""
        offset = 12 + len(tables) * 16
        for tag, value in sorted(tables.items()):
            directory += struct.pack(">4sIII", tag, 0, offset, len(value))
            contents += value
            offset += len(value)
        return directory + contents

    exporter = Exporter(policy())
    public = font("Synthetic font")
    before = sha256(public)
    exporter.audit_truetype_font(public)
    assert sha256(public) == before
    assert exporter.counts["validated_truetype_tables"] == 9
    with pytest.raises(ReleaseError, match="client"):
        exporter.audit_truetype_font(font("client-canary"))
    with pytest.raises(ReleaseError, match="private"):
        exporter.audit_truetype_font(font("private-alias"))


def test_download_preserves_preexisting_partial_file_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    name = "experiments-001.zip"
    partial = tmp_path / (name + ".partial")
    partial.write_bytes(b"user-owned incomplete download")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "verified_local_derivative",
                "files": [{"path": "data.json", "archive": name, "bytes": 1, "sha256": "0" * 64}],
                "archives": [
                    {
                        "name": name,
                        "bytes": 1,
                        "sha256": "0" * 64,
                        "files": 1,
                        "url": "https://github.com/tsalles/ai-search-evaluation/"
                        "releases/download/v0.1.0-experiments/" + name,
                    }
                ],
            }
        )
    )

    def forbid_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network must not be used for an existing partial")

    monkeypatch.setattr(urllib.request, "urlopen", forbid_network)
    with pytest.raises(ReleaseError, match="partial"):
        release_assets(manifest, tmp_path, download=True, extract=None)
    assert partial.read_bytes() == b"user-owned incomplete download"


def test_rejects_unreferenced_private_pdf_object_and_opaque_stream() -> None:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, TextStringObject

    for candidate in (
        TextStringObject("client-canary"),
        DecodedStreamObject(),
    ):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer._add_object(candidate)
        output = io.BytesIO()
        writer.write(output)
        with pytest.raises(ReleaseError, match="client|opaque"):
            Exporter(policy()).transform(output.getvalue(), "corpus.pdf")


def test_rebuilds_database_preserving_rows_and_removing_deleted_private_residue(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    target = tmp_path / "public.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE records(id INTEGER PRIMARY KEY,payload BLOB,score REAL)")
    connection.execute(
        "INSERT INTO records VALUES(1,?,0.125)",
        (json.dumps({"path": "private-alias", "quota": 4}).encode(),),
    )
    connection.execute("INSERT INTO records VALUES(2,?,0.0)", (b'"private-alias-deleted"',))
    connection.execute("DELETE FROM records WHERE id=2")
    connection.commit()
    connection.close()
    exporter = Exporter(policy())
    exporter.database(source, target)
    public = sqlite3.connect(target)
    row = public.execute("SELECT * FROM records").fetchone()
    assert row[0] == 1 and row[2] == 0.125
    assert json.loads(row[1]) == {"path": "example-alias", "quota": 4}
    assert public.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert b"private-alias" not in target.read_bytes()
    public.close()


def test_rejects_unknown_embedded_image_and_external_office_link() -> None:
    exporter = Exporter(policy())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("ppt/media/image.png", b"unreviewed")
    with pytest.raises(ReleaseError, match="unreviewed"):
        exporter.transform(output.getvalue(), "document.pptx")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "_rels/.rels",
            '<Relationships><Relationship Target="https://example.com" '
            'TargetMode="External"/></Relationships>',
        )
    with pytest.raises(ReleaseError, match="external"):
        exporter.transform(output.getvalue(), "document.pptx")


def test_removes_approved_thumbnail_with_valid_relationship_updates() -> None:
    image = b"approved-thumbnail"
    approved = policy()
    approved.approved_images.add(sha256(image))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("docProps/thumbnail.jpeg", image)
        archive.writestr(
            "[Content_Types].xml", '<Types><Override PartName="/docProps/thumbnail.jpeg"/></Types>'
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships><Relationship Target="docProps/thumbnail.jpeg"/></Relationships>',
        )
    data = Exporter(approved).transform(output.getvalue(), "document.docx")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "docProps/thumbnail.jpeg" not in archive.namelist()
        assert b"thumbnail" not in archive.read("_rels/.rels")
        assert b"thumbnail" not in archive.read("[Content_Types].xml")


@pytest.mark.parametrize("existing_checkout", [False, True])
def test_end_to_end_offline_pack_verify_and_extract(
    tmp_path: Path, existing_checkout: bool,
) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"metric": 0.5, "seed": 19}', encoding="utf-8")
    output = tmp_path / "release"
    output.mkdir()
    root = output / "payload"
    exporter = Exporter(policy())
    exporter.emit(source, "evaluations/study/metrics.json", root)
    exporter.verify(root)
    archives = exporter.pack(root, output)
    exporter.verify(root, output)
    assert exporter.counts["verified_final_archive_files"] == 1
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {"status": "verified_local_derivative", "files": exporter.entries, "archives": archives}
        ),
        encoding="utf-8",
    )
    extracted = tmp_path / "extracted"
    index = extracted / "evaluations" / "README.md"
    index_content = "# Evaluation release index\n"
    if existing_checkout:
        index.parent.mkdir(parents=True)
        index.write_text(index_content, encoding="utf-8")
    release_assets(manifest, output, download=False, extract=extracted)
    assert (extracted / "evaluations/study/metrics.json").read_bytes() == source.read_bytes()
    if existing_checkout:
        assert index.read_text(encoding="utf-8") == index_content
    assert file_hash(source) == exporter.entries[0]["sha256"]
    with pytest.raises(ReleaseError, match="overwrite"):
        extract_archive(output / archives[0]["name"], extracted, exporter.entries)
    archive = output / archives[0]["name"]
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(ReleaseError, match="checksum"):
        verify_archive(archive, archives[0], exporter.entries)


def test_emitted_content_reuse_preserves_physical_file_invariant_counts(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text('{"score":0.25,"quota":4}', encoding="utf-8")
    exporter = Exporter(policy())
    root = tmp_path / "payload"
    exporter.emit(source, "evaluations/a.json", root)
    exporter.emit(source, "evaluations/b.json", root)
    assert exporter.numeric_values == 4
    assert exporter.json_documents == 2
    assert exporter.counts["source_files"] == 2
    assert exporter.counts["reused_emitted_source_contents"] == 1
    exporter.verify(root)


def test_parallel_release_merges_verified_partitions_without_private_paths(tmp_path: Path) -> None:
    from public_asset_release import run_parallel

    source = tmp_path / "source"
    source.mkdir()
    (source / "first.json").write_text('{"score":0.125,"seed":7}', encoding="utf-8")
    (source / "second.json").write_bytes((source / "first.json").read_bytes())
    (source / "notes.md").write_text("# Public study\n", encoding="utf-8")
    config = tmp_path / "scope.json"
    config.write_text(json.dumps({"roots": [{"source": str(source), "public": "evaluations"}]}))
    rules = tmp_path / "policy.json"
    rules.write_text(
        json.dumps(
            {
                "replacements": {},
                "clients": ["client-canary"],
                "private_terms": [],
            }
        )
    )
    output = tmp_path / "release"
    manifest = tmp_path / "manifest.json"
    run_parallel(config, rules, output, manifest, workers=2)
    report = json.loads(manifest.read_text())
    assert report["selected_inputs"]["direct_files"] == 3
    assert report["invariants"]["json_numeric_and_null_values"] == 4
    assert report["counts"]["verified_final_archive_files"] == 3
    assert str(tmp_path) not in manifest.read_text()
    assert not list((output / "control").glob("scope-*.json"))
    restored = tmp_path / "restored"
    release_assets(manifest, output, download=False, extract=restored, workers=2)
    assert len(list(restored.rglob("*.*"))) == 3
    report["archives"][-1]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(report))
    blocked = tmp_path / "blocked-restore"
    with pytest.raises(ReleaseError, match="checksum"):
        release_assets(manifest, output, download=False, extract=blocked, workers=2)
    assert not blocked.exists()
