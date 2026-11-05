from importlib.metadata import version

import httpx
from azure.core.credentials import TokenCredential
from pydantic import JsonValue

from docgen.config import Config
from docgen.errors import InputError, ProviderError
from docgen.planning import base_result, create_plan
from docgen.providers.azure import AzureProvider
from docgen.structure_models import LAYOUT_CAPABILITIES


def doctor(
    config: Config, *, live: bool = False, credential: TokenCredential | None = None,
    http_client: httpx.Client | None = None,
) -> dict[str, JsonValue]:
    if config.generation is None or config.generation.provider is None:
        raise InputError("Doctor requires generation.provider configuration.")
    create_plan(
        config, run_id="doctor-preview",
        operation="run" if config.rendering is not None else "generate",
    )
    result = base_result("doctor", "ready")
    details: dict[str, JsonValue] = {
        "scope": "local", "live_verified": False, "api": "responses",
        "deployment": config.generation.provider.deployment,
        "openai_version": version("openai"), "azure_identity_version": version("azure-identity"),
        "wire_schema_version": "1", "max_live_requests": 1 if live else 0,
        "warnings": ["Local readiness does not prove Azure authentication or model compatibility."],
        "structure_catalog_version": "1",
        "layout_capabilities": {
            format: list(names) for format, names in LAYOUT_CAPABILITIES.items()
        },
    }
    result["details"] = details
    if not live:
        return result
    details["scope"] = "live"
    prompt = (
        "Return a minimal fictional Portuguese draft using the supplied JSON schema. "
        "Title: Teste de capacidade. Include one short paragraph block with id intro, text "
        "Conteudo ficticio, level null and table_id null. Keep list_items, columns, cells "
        "and facts empty. Do not generate real banking advice."
    )
    try:
        with AzureProvider(
            config.generation.provider, limits=config.generation.limits,
            credential=credential, http_client=http_client,
        ) as provider:
            response = provider.request(
                prompt,
                max_output_tokens=min(2048, config.generation.limits.max_output_tokens_per_request),
            )
    except ProviderError as exc:
        result["status"] = "incomplete"
        result["failures"] = [{
            "code": exc.code, "phase": "doctor", "retryable": exc.retryable, "message": str(exc),
        }]
        result["usage"] = exc.usage.model_dump(mode="json") if exc.usage is not None else None
        return result
    details.update(
        live_verified=True, warnings=[], reported_model=response.reported_model,
        model_version=response.model_version, wire_schema_validated=True,
        response_id=response.response_id, request_id=response.request_id,
        storage_requested=False, output_tokens_limit=min(
            2048, config.generation.limits.max_output_tokens_per_request
        ),
    )
    result["usage"] = response.usage.model_dump(mode="json") if response.usage is not None else None
    return result
