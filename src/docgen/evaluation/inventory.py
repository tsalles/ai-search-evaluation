import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from filelock import FileLock, Timeout
from pydantic import JsonValue, ValidationError

from docgen.errors import InputError, IntegrityError
from docgen.evaluation.models import ARMS
from docgen.evaluation.state import StoredJson, json_bytes
from docgen.persistence import atomic_write, safe_child, temporary_path

RESOURCE_KINDS = {
    "indexes": "index", "skillsets": "skillset", "indexers": "indexer", "datasources": "datasource",
}
SECRET_KEYS = {
    "apikey", "accountkey", "password", "clientsecret", "authorization",
    "accesstoken", "refreshtoken", "sharedaccesssignature", "authtoken", "authenticationkey",
}
RESOURCE_ID_CONNECTION = re.compile(
    r"ResourceId=/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[^;]+/providers/"
    r"Microsoft\.Storage/storageAccounts/[a-z0-9]{3,24};?",
    re.IGNORECASE,
)


def object_value(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise IntegrityError("Recorded Search configuration must be a JSON object.")
    return value


def checked_directory(path: Path) -> Path:
    resolved = path.absolute()
    if any(parent.is_symlink() or parent.is_junction() for parent in (resolved, *resolved.parents)):
        raise IntegrityError("Configuration inventory paths cannot contain filesystem links.")
    return resolved


def discover_experiments(root: Path) -> list[Path]:
    root = checked_directory(root)
    if not root.is_dir():
        raise InputError("The experiment inventory source directory does not exist.")
    if (root / "protocol.json").exists():
        return [root]
    result: list[Path] = []
    for category in sorted(root.iterdir()):
        if not category.is_dir():
            continue
        checked_directory(category)
        if category.name.startswith("experiment-"):
            result.append(category)
            continue
        for experiment in sorted(category.iterdir()):
            if experiment.is_dir() and experiment.name.startswith("experiment-"):
                result.append(checked_directory(experiment))
    if not result:
        raise InputError("No experiment workspaces were found for configuration inventory.")
    return result


def read_records(path: Path) -> tuple[dict[str, JsonValue], str, dict[str, tuple[JsonValue, str]]]:
    protocol_file = safe_child(path, "protocol.json")
    database_file = safe_child(path, "evaluation.sqlite3")
    try:
        raw_protocol = protocol_file.read_bytes()
        protocol = object_value(StoredJson.model_validate_json(raw_protocol).root)
        protocol_hash = hashlib.sha256(raw_protocol).hexdigest()
        with closing(sqlite3.connect(
            database_file.as_uri() + "?mode=ro", uri=True,
        )) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            saved = connection.execute("SELECT hash FROM protocol").fetchone()
            if saved is None or saved[0] != protocol_hash:
                raise IntegrityError("Inventory source protocol checksum differs.")
            if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
                raise IntegrityError("Inventory source evaluation state version is unsupported.")
            selected = connection.execute(
                "SELECT name,payload,hash FROM records WHERE "
                "name LIKE 'create:resource:%' OR name LIKE 'resource:%' OR "
                "name LIKE 'ingested-resources:%' OR name LIKE 'index-epoch-state:%' OR "
                "name LIKE 'index-epoch-applied:%' OR name LIKE 'index-epoch-intent:%' OR "
                "name LIKE 'index-epoch-candidate:%' OR name LIKE 'collection-plan:%' OR "
                "name LIKE 'query-cohort:%' OR name LIKE 'section-study:resource-repair:%' OR "
                "name IN ('section-study:design','section-study:metadata-selection',"
                "'section-study:evidence-plan') OR name='invalidated' ORDER BY name"
            ).fetchall()
            records: dict[str, tuple[JsonValue, str]] = {}
            for name, payload, expected in selected:
                if (
                    not isinstance(payload, bytes)
                    or hashlib.sha256(payload).hexdigest() != expected
                ):
                    raise IntegrityError("Inventory source record checksum differs: " + name)
                records[name] = StoredJson.model_validate_json(payload).root, expected
        return protocol, protocol_hash, records
    except (OSError, sqlite3.Error, ValidationError) as error:
        raise IntegrityError(
            f"Cannot read recorded Search configurations ({type(error).__name__})."
        ) from error


def public_configuration(value: JsonValue, pointer: str = "") -> tuple[JsonValue, list[str]]:
    redactions: list[str] = []
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            location = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            sensitive = normalized in SECRET_KEYS or (
                normalized == "connectionstring" and isinstance(item, str)
                and RESOURCE_ID_CONNECTION.fullmatch(item) is None
            )
            if sensitive and item is not None and item != "":
                result[key] = "<redacted>"
                redactions.append(location)
            else:
                result[key], nested = public_configuration(item, location)
                redactions.extend(nested)
        return result, redactions
    if isinstance(value, list):
        items: list[JsonValue] = []
        for index, item in enumerate(value):
            public, nested = public_configuration(item, pointer + "/" + str(index))
            items.append(public)
            redactions.extend(nested)
        return items, redactions
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        try:
            parsed = urlsplit(value)
            sensitive_url = parsed.username is not None or any(
                key.lower() in {"sig", "token", "apikey", "api-key", "access_token"}
                for key, _ in parse_qsl(parsed.query)
            )
        except ValueError:
            sensitive_url = True
        if sensitive_url:
            return "<redacted>", [pointer]
    return value, []


def directory(root: Path, *parts: str) -> Path:
    destination = root
    for part in parts:
        destination = safe_child(destination, part)
        destination.mkdir(exist_ok=True)
    return destination


def write_immutable(path: Path, value: JsonValue) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2,
    ).encode("utf-8") + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            raise IntegrityError("Existing inventory configuration export differs: " + str(path))
    else:
        temporary_path(path).unlink(missing_ok=True)
        atomic_write(path, raw)
    return hashlib.sha256(raw).hexdigest()


def export_experiment(source: Path, output: Path) -> dict[str, JsonValue]:
    protocol, protocol_hash, records = read_records(source)
    identifier = protocol.get("id")
    if not isinstance(identifier, str) or identifier != source.name:
        raise IntegrityError("Inventory source experiment identity differs from its directory.")
    search = object_value(object_value(protocol.get("config"))["search"])
    base = directory(output, "experiments", identifier)
    entries: list[JsonValue] = []

    def export(
        value: JsonValue, *, name: str, kind: str, phase: str,
        arm: str | None, source_hash: str, sequence: int | None = None,
    ) -> None:
        original = object_value(value)
        public, redactions = public_configuration(original)
        resource_hash = hashlib.sha256(json_bytes(original)).hexdigest()
        parent = directory(base, arm or "shared", phase)
        destination = safe_child(parent, kind + "-" + resource_hash[:16] + ".json")
        exported_hash = write_immutable(destination, public)
        entry: dict[str, JsonValue] = {
            "kind": kind, "arm": arm, "phase": phase, "source_record": name,
            "source_record_sha256": source_hash, "configuration_sha256": resource_hash,
            "file": str(destination.relative_to(output)), "file_sha256": exported_hash,
            "redacted_json_pointers": [pointer for pointer in redactions],
        }
        if kind in RESOURCE_KINDS.values():
            resource_name = original.get("name")
            if not isinstance(resource_name, str) or not resource_name:
                raise IntegrityError("Recorded Search resource has no name.")
            entry["resource_name"] = resource_name
            api = search.get("cu_api_version" if kind == "skillset" else "query_api_version")
            if not isinstance(api, str):
                raise IntegrityError("Recorded Search resource lacks its frozen API version.")
            entry["api_version"] = api
        if sequence is not None:
            entry["epoch"] = sequence
        entries.append(entry)

    export(
        search, name="protocol.json#/config/search", kind="search-settings", phase="protocol",
        arm=None, source_hash=protocol_hash,
    )
    for name, (value, source_hash) in records.items():
        if name.startswith(("create:resource:", "resource:")):
            parts = name.split(":")
            submitted = parts[0] == "create"
            arm, resource = parts[-2:]
            if arm not in ARMS or resource not in RESOURCE_KINDS:
                raise IntegrityError("Unrecognized recorded Search resource identity: " + name)
            export(
                value, name=name, kind=RESOURCE_KINDS[resource],
                phase="submitted" if submitted else "observed-initial",
                arm=arm, source_hash=source_hash,
            )
        elif name.startswith("ingested-resources:"):
            arm = name.split(":")[-1]
            if arm not in ARMS:
                raise IntegrityError("Unrecognized post-ingestion arm.")
            for resource, configuration in object_value(value).items():
                if resource not in RESOURCE_KINDS:
                    raise IntegrityError("Unrecognized post-ingestion resource kind.")
                export(
                    configuration, name=name, kind=RESOURCE_KINDS[resource],
                    phase="observed-ingested", arm=arm, source_hash=source_hash,
                )
        elif name.startswith("section-study:resource-repair:"):
            parts = name.split(":")
            if len(parts) not in {3, 4} or not parts[2].isdecimal():
                raise IntegrityError("Recorded pilot resource-repair identity is invalid.")
            repair_sequence = int(parts[2])
            state = object_value(value)
            if len(parts) == 4:
                if parts[3] != "intent":
                    raise IntegrityError("Unrecognized pilot resource-repair phase.")
                for resource, configuration in object_value(state.get("before")).items():
                    if resource not in RESOURCE_KINDS:
                        raise IntegrityError("Unrecognized pre-repair resource kind.")
                    export(
                        configuration, name=name, kind=RESOURCE_KINDS[resource],
                        phase="observed-pre-repair", arm="de_split", source_hash=source_hash,
                        sequence=repair_sequence,
                    )
                for key, resource in (
                    ("submitted_index", "indexes"), ("submitted_skillset", "skillsets"),
                ):
                    export(
                        state.get(key), name=name, kind=RESOURCE_KINDS[resource],
                        phase="submitted-pilot-repair", arm="de_split", source_hash=source_hash,
                        sequence=repair_sequence,
                    )
            else:
                for resource, configuration in object_value(state.get("after")).items():
                    if resource not in RESOURCE_KINDS:
                        raise IntegrityError("Unrecognized observed repair resource kind.")
                    export(
                        configuration, name=name, kind=RESOURCE_KINDS[resource],
                        phase="observed-pilot-repair", arm="de_split", source_hash=source_hash,
                        sequence=repair_sequence,
                    )
        elif name.startswith("index-epoch-state:"):
            state = object_value(value)
            sequence = state.get("sequence")
            if type(sequence) is not int or sequence < 0:
                raise IntegrityError("Recorded index epoch sequence is invalid.")
            for arm, configuration in object_value(state.get("definitions")).items():
                if arm not in ARMS:
                    raise IntegrityError("Unrecognized index epoch arm.")
                export(
                    configuration, name=name, kind="index", phase=f"epoch-{sequence:06d}",
                    arm=arm, source_hash=source_hash, sequence=sequence,
                )
        elif name.startswith("index-epoch-applied:"):
            sequence_text, arm = name.split(":")[-2:]
            if not sequence_text.isdecimal() or arm not in ARMS:
                raise IntegrityError("Recorded applied index epoch identity is invalid.")
            export(
                value, name=name, kind="index", phase="observed-epoch-write",
                arm=arm, source_hash=source_hash, sequence=int(sequence_text),
            )
        elif name != "invalidated":
            export(
                value, name=name, kind="query-policy" if name.startswith("index-epoch-candidate:")
                else "query-plan" if name.startswith("collection-plan:")
                else "epoch-or-cohort-plan",
                phase="query-configurations", arm=None, source_hash=source_hash,
            )
    resource_entries = [object_value(entry) for entry in entries if object_value(entry)["arm"]]
    coverage: dict[str, JsonValue] = {}
    latest_observed: dict[str, JsonValue] = {}
    for arm in ARMS:
        phases: dict[str, JsonValue] = {}
        for phase in ("submitted", "observed-initial", "observed-ingested"):
            available = {
                str(entry["kind"]) for entry in resource_entries
                if entry["arm"] == arm and entry["phase"] == phase
            }
            phases[phase] = {
                "available": [kind for kind in sorted(available)],
                "not_recorded": [
                    kind for kind in sorted(set(RESOURCE_KINDS.values()) - available)
                ],
            }
        coverage[arm] = phases
        latest: dict[str, JsonValue] = {}
        for kind in RESOURCE_KINDS.values():
            observed = [
                entry for entry in resource_entries
                if entry["arm"] == arm and entry["kind"] == kind
                and not str(entry["phase"]).startswith("submitted")
            ]
            if not observed:
                continue

            def rank(entry: dict[str, JsonValue]) -> tuple[int, int, int]:
                phase = str(entry["phase"])
                if phase.startswith("epoch-") or phase == "observed-epoch-write":
                    sequence = entry.get("epoch")
                    if type(sequence) is not int:
                        raise IntegrityError("Observed epoch configuration lacks its sequence.")
                    return 2, sequence, int(phase.startswith("epoch-"))
                if phase == "observed-pilot-repair":
                    sequence = entry.get("epoch")
                    if type(sequence) is not int:
                        raise IntegrityError("Observed pilot repair lacks its sequence.")
                    return 0, sequence, 1
                return int(phase == "observed-ingested"), 0, 0

            latest[kind] = max(observed, key=rank)
        latest_observed[arm] = latest
    return {
        "experiment_id": identifier, "source_path": str(source),
        "protocol_sha256": protocol_hash, "protocol_schema_version": protocol.get("schema_version"),
        "enrichment_policy": protocol.get("enrichment_policy"),
        "invalidated": "invalidated" in records,
        "configuration_records_present": bool(resource_entries),
        "resource_coverage": coverage, "latest_observed_resources": latest_observed,
        "configurations": entries,
    }


def export_inventory(source_root: Path, output: Path) -> dict[str, JsonValue]:
    sources = discover_experiments(source_root)
    output = checked_directory(output)
    if any(output == source or output.is_relative_to(source) for source in sources):
        raise InputError("Place the inventory outside every immutable experiment workspace.")
    try:
        output.mkdir(parents=True, exist_ok=True)
        with FileLock(safe_child(output, ".inventory.lock"), timeout=0):
            latest = safe_child(output, "inventory.json")
            if latest.exists():
                try:
                    saved = object_value(StoredJson.model_validate_json(latest.read_bytes()).root)
                except ValidationError as error:
                    raise IntegrityError("Existing inventory catalog is invalid.") from error
                previous_root = saved.get("source_root")
                if (
                    saved.get("scope")
                    != "recorded_experimental_search_configurations_not_current_live_state"
                    or not isinstance(previous_root, str)
                    or Path(previous_root).absolute() != source_root.absolute()
                ):
                    raise InputError(
                        "The existing inventory belongs to another source; choose another output."
                    )
            experiments: list[JsonValue] = [
                export_experiment(source, output) for source in sources
            ]
            total = 0
            for item in experiments:
                configurations = object_value(item)["configurations"]
                if not isinstance(configurations, list):
                    raise IntegrityError("Exported inventory configuration list is invalid.")
                total += len(configurations)
            inventory: dict[str, JsonValue] = {
                "schema_version": "1", "source_root": str(source_root.absolute()),
                "scope": "recorded_experimental_search_configurations_not_current_live_state",
                "source_access": "read_only_checksummed_sqlite_snapshot",
                "missing_configuration_policy": "explicit_not_recorded_no_reconstruction",
                "secret_policy": "visible_redaction_with_original_and_exported_checksums",
                "experiment_count": len(experiments), "configuration_count": total,
                "experiments": experiments,
            }
            fingerprint = hashlib.sha256(json_bytes(inventory)).hexdigest()
            versioned = safe_child(output, "inventory-" + fingerprint[:16] + ".json")
            write_immutable(versioned, inventory)
            raw = versioned.read_bytes()
            if not latest.exists() or latest.read_bytes() != raw:
                temporary_path(latest).unlink(missing_ok=True)
                atomic_write(latest, raw, overwrite=True)
            return {
                "inventory_path": str(latest), "versioned_inventory_path": str(versioned),
                "inventory_sha256": hashlib.sha256(raw).hexdigest(),
                "experiment_count": len(experiments), "configuration_count": total,
                "live_calls": 0, "source_workspaces_modified": False,
            }
    except Timeout:
        raise IntegrityError("Configuration inventory is locked by another writer.") from None
    except OSError as error:
        raise IntegrityError(
            f"Cannot export recorded Search inventory ({type(error).__name__})."
        ) from error
