import json
import os
from functools import lru_cache

import azure.functions as func
from azure.core.exceptions import AzureError
from runtime import BlobModelLedger

from docgen.errors import InputError, IntegrityError, ProviderError
from docgen.evaluation.section_service import handle_skill_request

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@lru_cache(maxsize=1)
def planner() -> BlobModelLedger:
    return BlobModelLedger()


@app.route(route="sections", methods=["POST"])
def sections(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    # Easy Auth validates issuer/audience and strips caller-supplied principal headers.
    expected = os.environ["SECTION_SEARCH_PRINCIPAL_ID"]
    if req.headers.get("X-MS-CLIENT-PRINCIPAL-ID", "").lower() != expected.lower():
        return func.HttpResponse('{"error":"caller_not_allowed"}', status_code=403)
    if len(req.get_body()) > 1000000:
        return func.HttpResponse('{"error":"request_too_large"}', status_code=413)
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse('{"error":"invalid_json"}', status_code=400)
    try:
        ledger = planner()
        ledger.receipt(context.invocation_id, {
            "caller_principal_id": expected, "payload": payload,
        })
        result = handle_skill_request(
            payload, deployment=ledger.settings.deployment, model_call=ledger,
        )
    except InputError:
        return func.HttpResponse('{"error":"invalid_skill_request"}', status_code=400)
    except (AzureError, IntegrityError, ProviderError):
        return func.HttpResponse('{"error":"audit_or_model_unavailable"}', status_code=503)
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False), mimetype="application/json",
    )
