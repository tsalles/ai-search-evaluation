import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Never

from docgen import __version__


class ArgumentsError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        if "invalid choice" in message:
            safe = "invalid choice; use --help for supported commands and options."
        elif "required" in message:
            safe = "Required command options are missing; use --help."
        else:
            safe = "Invalid command options; use --help."
        raise ArgumentsError(safe)


def parser() -> Parser:
    root = Parser(prog="docgen", description="Generate controlled synthetic document corpora.")
    root.add_argument("--version", action="version", version=f"docgen {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    for operation in (
        "plan", "doctor", "generate", "render", "run", "resume", "validate", "push", "clear",
    ):
        command = commands.add_parser(operation)
        command.add_argument("--json", action="store_true", help="Emit the versioned JSON result.")
        if operation in {"plan", "doctor", "generate", "render", "run"}:
            command.add_argument("--config", type=Path, required=True)
        if operation in {"generate", "run"}:
            command.add_argument("--output", type=Path, required=True)
        if operation in {"render", "resume", "validate"}:
            command.add_argument("--run", type=Path, required=True)
        if operation == "plan":
            command.add_argument("--phase", choices=["generate", "render", "run"], default="run")
            command.add_argument("--run", type=Path)
        if operation == "doctor":
            command.add_argument(
                "--live",
                action="store_true",
                help="Authorize one bounded paid Azure capability request.",
            )
        if operation == "resume":
            command.add_argument("--max-requests", type=int)
            command.add_argument("--max-observed-total-tokens", type=int)
            command.add_argument("--max-candidates-per-item", type=int)
        if operation in {"push", "clear"}:
            command.add_argument("--container", required=True)
            auth = command.add_mutually_exclusive_group()
            auth.add_argument("--connection-string")
            auth.add_argument(
                "--account-url",
                help="Use Microsoft Entra authentication through the logged-in Azure CLI user.",
            )
            command.add_argument("--env-file", type=Path)
            command.add_argument("--prefix", default="")
            if operation == "push":
                command.add_argument("--corpus", type=Path, required=True)
                command.add_argument("--overwrite", action="store_true")
                command.add_argument("--create-container", action="store_true")
            else:
                mode = command.add_mutually_exclusive_group()
                mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
                mode.add_argument("--yes", action="store_true", help="Authorize deletion.")
                command.add_argument("--include-snapshots", action="store_true")
                command.add_argument("--max-blobs", type=int, default=10000)
    experiment = commands.add_parser(
        "experiment", help="Generate, review and compare fresh DE/CU retrieval experiments.",
    )
    phases = experiment.add_subparsers(dest="experiment_action", required=True)
    for action in (
        "plan", "init", "generate", "reference-build", "review", "reference-validate",
        "release", "prepare", "ingest", "snapshot", "collect", "score", "status", "fork",
        "inventory", "section-trial",
    ):
        phase = phases.add_parser(action)
        phase.add_argument("--json", action="store_true")
        if action in {"plan", "init", "fork"}:
            phase.add_argument("--config", type=Path, required=True)
        if action not in {"plan", "init", "inventory", "section-trial"}:
            phase.add_argument("--experiment", type=Path, required=True)
        if action in {"init", "fork"}:
            phase.add_argument("--output", type=Path, required=True)
        if action == "inventory":
            source = phase.add_mutually_exclusive_group()
            source.add_argument("--experiment", type=Path)
            source.add_argument("--root", type=Path, default=Path("evaluations"))
            phase.add_argument(
                "--output", type=Path, default=Path("evaluations") / "inventory" / "ai-search",
            )
        if action == "section-trial":
            phase.add_argument("--source", type=Path, required=True)
            phase.add_argument("--output", type=Path, required=True)
            phase.add_argument("--live", action="store_true")
            phase.add_argument("--base-url")
            phase.add_argument("--deployment")
            phase.add_argument("--subscription")
            phase.add_argument("--sample-size", type=int, default=12)
            phase.add_argument("--seed", type=int, default=42)
            phase.add_argument("--max-input-tokens", type=int, default=12000)
            phase.add_argument("--max-completion-tokens", type=int, default=2048)
            phase.add_argument("--max-total-tokens", type=int, default=100000)
            phase.add_argument("--max-chunk-characters", type=int, default=2000)
            phase.add_argument("--timeout-seconds", type=int, default=30)
        if action in {"generate", "prepare", "ingest", "snapshot", "collect"}:
            phase.add_argument("--live", action="store_true")
        if action == "review":
            phase.add_argument("--intent", required=True)
            phase.add_argument("--reviewer", required=True)
            phase.add_argument("--certify-scope", action="store_true", required=True)
        if action == "reference-validate":
            phase.add_argument("--for-release", action="store_true")
        if action == "release":
            assurance = phase.add_mutually_exclusive_group()
            assurance.add_argument(
                "--provisional", action="store_true",
                help="Release automated-only labels for an all-test smoke of at most 12 documents.",
            )
            assurance.add_argument(
                "--provisional-pilot", action="store_true",
                help="Release exploratory-only labels for 18 to 300 documents in 3 to 50 families.",
            )
            assurance.add_argument(
                "--provisional-study", action="store_true",
                help="Release unreviewed raw-only study labels for 306 to 996 documents.",
            )
        if action == "ingest":
            phase.add_argument("--wait-seconds", type=int, default=0)
        if action == "snapshot":
            phase.add_argument(
                "--arm", choices=["de_split", "content_understanding"], required=True,
            )
            phase.add_argument("--audit", type=Path)
        if action in {"collect", "score"}:
            from docgen.evaluation.profile_names import PROFILES

            phase.add_argument("--profile", choices=PROFILES, default="hybrid")
            phase.add_argument("--cohort", type=Path)
            phase.add_argument(
                "--split", choices=["calibration", "development", "test"], default="test",
            )
    return root


def main(argv: Sequence[str] | None = None) -> int:
    root = parser()
    try:
        args = root.parse_args(argv)
    except ArgumentsError as error:
        from docgen.planning import base_result

        result = base_result("cli", "invalid_input")
        result["failures"] = [
            {
                "code": "invalid_arguments",
                "phase": "cli",
                "retryable": False,
                "message": str(error),
            }
        ]
        print(json.dumps(result))
        print(str(error), file=sys.stderr)
        return 2
    from pydantic import ValidationError

    from docgen.budgets import BudgetOverride
    from docgen.config import load_config
    from docgen.doctor import doctor
    from docgen.errors import InputError, IntegrityError, ProviderError
    from docgen.pipeline import clear, generate, push, render, resume, run, validate
    from docgen.planning import base_result, preview, preview_render

    try:
        if args.command == "experiment":
            from docgen.evaluation.cli import execute

            result = execute(args)
        elif args.command == "plan":
            config = load_config(args.config)
            if args.phase == "render":
                if args.run is None:
                    raise InputError("Phase 2 preview requires --run.")
                result = preview_render(args.run, config)
            else:
                result = preview(config, operation=args.phase)
        elif args.command == "doctor":
            result = doctor(load_config(args.config), live=args.live)
        elif args.command in {"generate", "run"}:
            operation = generate if args.command == "generate" else run
            result = operation(load_config(args.config), args.output).model_dump(mode="json")
        elif args.command == "render":
            config = load_config(args.config)
            config.require_phase("render")
            if config.rendering is None:
                raise InputError("Rendering configuration is required.")
            result = render(args.run, config.rendering).model_dump(mode="json")
        elif args.command == "resume":
            values = {
                "max_requests": args.max_requests,
                "max_observed_total_tokens": args.max_observed_total_tokens,
                "max_candidates_per_item": args.max_candidates_per_item,
            }
            override = (
                BudgetOverride.model_validate(values)
                if any(value is not None for value in values.values())
                else None
            )
            result = resume(args.run, budget_override=override).model_dump(mode="json")
        elif args.command == "push":
            result = push(
                args.corpus, container=args.container, connection_string=args.connection_string,
                account_url=args.account_url,
                env_file=args.env_file, prefix=args.prefix, overwrite=args.overwrite,
                create_container=args.create_container,
            )
        elif args.command == "clear":
            result = clear(
                container=args.container, connection_string=args.connection_string,
                account_url=args.account_url, env_file=args.env_file, prefix=args.prefix,
                confirm=args.yes, include_snapshots=args.include_snapshots,
                max_blobs=args.max_blobs,
            )
        else:
            result = validate(args.run).model_dump(mode="json")
    except (InputError, ValidationError) as error:
        result = base_result(args.command, "invalid_input")
        result["failures"] = [
            {
                "code": "invalid_configuration",
                "phase": args.command,
                "retryable": False,
                "message": "Invalid typed command configuration."
                if isinstance(error, ValidationError)
                else str(error),
            }
        ]
    except (IntegrityError, OSError, sqlite3.Error) as error:
        result = base_result(args.command, "integrity_error")
        result["failures"] = [
            {
                "code": "integrity_error",
                "phase": args.command,
                "retryable": False,
                "message": str(error),
            }
        ]
    except KeyboardInterrupt:
        result = base_result(args.command, "cancelled")
        result["failures"] = [
            {
                "code": "cancelled",
                "phase": args.command,
                "retryable": True,
                "message": "Operation cancelled; verified work was retained.",
            }
        ]
    except ProviderError as error:
        result = base_result(args.command, "incomplete")
        result["failures"] = [
            {
                "code": error.code, "phase": args.command,
                "retryable": error.retryable, "message": str(error),
            }
        ]
    codes = {
        "planned": 0,
        "ready": 0,
        "valid": 0,
        "content_ready": 0,
        "complete": 0,
        "invalid_input": 2,
        "integrity_error": 4,
        "cancelled": 130,
        "incomplete": 3,
    }
    status = str(result["status"])
    if status not in codes:
        result = base_result(args.command, "integrity_error")
        result["failures"] = [
            {
                "code": "unexpected_status",
                "phase": args.command,
                "retryable": False,
                "message": "Operation returned an unsupported status.",
            }
        ]
        status = "integrity_error"
    print(json.dumps(result, ensure_ascii=True))
    return codes[status]
