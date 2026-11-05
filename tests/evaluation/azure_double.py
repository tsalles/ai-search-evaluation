import base64
import copy
import hashlib
import json
import struct
from urllib.parse import parse_qs, unquote, urlsplit
from xml.etree import ElementTree as ET

import httpx
from azure.core.credentials import AccessToken
from azure.core.pipeline.transport import HttpTransport

from docgen.text import business_units
from tests.test_blob_push import StorageResponse


class Credential:
    def __init__(self):
        self.scopes = []

    def get_token(self, *scopes, **kwargs):
        self.scopes.extend(scopes)
        return AccessToken("offline-token-do-not-log", 4102444800)


class DownloadStream:
    def __init__(self, response):
        self.response = response
        self.content_length = int(response.headers["content-length"])
        self.chunks = iter((response.payload,))

    def __len__(self):
        return self.content_length

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.chunks)


class DownloadResponse(StorageResponse):
    def stream_download(self, pipeline, **kwargs):
        return DownloadStream(self)


class BlobTransport(HttpTransport):
    def __init__(self):
        self.blobs = {}
        self.requests = []
        self.closed = False
        self.after_upload = None

    def open(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def send(self, request, **kwargs):
        parsed = urlsplit(request.url)
        name = unquote(parsed.path).split("/", 2)[-1]
        self.requests.append(request)
        if request.method == "HEAD":
            if name not in self.blobs:
                return StorageResponse(request, 404, "BlobNotFound")
            item = self.blobs[name]
            response = StorageResponse(request, 200)
            response.headers["content-length"] = str(len(item["body"]))
            response.headers["etag"] = item["etag"]
            response.headers["x-ms-blob-type"] = "BlockBlob"
            for key, value in item["metadata"].items():
                response.headers["x-ms-meta-" + key] = value
            return response
        if request.method == "GET":
            query = parse_qs(parsed.query)
            if query.get("comp") != ["list"]:
                if name not in self.blobs:
                    return StorageResponse(request, 404, "BlobNotFound")
                item = self.blobs[name]
                headers = httpx.Headers(request.headers)
                if headers.get("if-match") != item["etag"]:
                    return StorageResponse(request, 412, "ConditionNotMet")
                interval = headers.get("x-ms-range", headers.get("range", "bytes=0-")).split("=")[1]
                start, end = interval.split("-", 1)
                start = int(start)
                end = min(int(end) if end else len(item["body"]) - 1, len(item["body"]) - 1)
                response = DownloadResponse(request, 206)
                response.payload = item["body"][start : end + 1]
                response.headers.update(
                    {
                        "content-type": "application/octet-stream",
                        "content-length": str(len(response.payload)),
                        "content-range": f"bytes {start}-{end}/{len(item['body'])}",
                        "etag": item["etag"],
                        "x-ms-blob-type": "BlockBlob",
                        "content-md5": base64.b64encode(
                            hashlib.md5(response.payload).digest()
                        ).decode(),
                    }
                )
                return response
            assert query["comp"] == ["list"]
            root = ET.Element("EnumerationResults")
            blobs = ET.SubElement(root, "Blobs")
            for blob_name, item in sorted(self.blobs.items()):
                if not blob_name.startswith(query["prefix"][0]):
                    continue
                blob = ET.SubElement(blobs, "Blob")
                ET.SubElement(blob, "Name").text = blob_name
                properties = ET.SubElement(blob, "Properties")
                ET.SubElement(properties, "Content-Length").text = str(len(item["body"]))
                ET.SubElement(properties, "Etag").text = item["etag"]
                ET.SubElement(properties, "Last-Modified").text = "Mon, 26 Oct 2026 12:00:00 GMT"
                ET.SubElement(properties, "BlobType").text = "BlockBlob"
            ET.SubElement(root, "NextMarker")
            response = StorageResponse(request, 200)
            response.payload = ET.tostring(root)
            return response
        assert request.method == "PUT"
        headers = httpx.Headers(request.headers)
        assert headers["if-none-match"] == "*"
        if name in self.blobs:
            return StorageResponse(request, 409, "BlobAlreadyExists")
        body = request.body.read() if hasattr(request.body, "read") else request.body
        self.blobs[name] = {
            "body": bytes(body),
            "etag": '"' + hashlib.sha256(body).hexdigest()[:20] + '"',
            "metadata": {
                key.removeprefix("x-ms-meta-"): value
                for key, value in headers.items()
                if key.startswith("x-ms-meta-")
            },
        }
        response = StorageResponse(request)
        response.headers["etag"] = self.blobs[name]["etag"]
        if self.after_upload is not None:
            self.after_upload()
        return response


class SearchTransport:
    def __init__(self, workspace, reference, contents):
        self.protocol = workspace.protocol
        self.requests = []
        self.resources = {}
        self.chunks = {}
        self.statuses = {}
        self.rankings = {}
        self.query_rankings = {}
        self.query_count = 0
        self.fail_after_queries = None
        self.query_coverage = 100
        self.page_size = 1000
        self.failures = {}
        self.normalize_resources = False
        self.embedding_model = "text-embedding-3-large"
        self.embedding_vector = [0.1, 0.2, 0.3]
        self.quantize_written_vectors = False
        self.fail_index_batch = False
        self.semantic_failure = None
        self.delay_context_visibility = False
        self.stale_context_rows = None
        by_id = {content.blueprint.content_id: content for content in contents}
        for arm in ("de_split", "content_understanding"):
            self.chunks[arm] = [
                {
                    "id": f"chunk-{index:04}",
                    "parent_id": "opaque-" + document.id,
                    "content_path": (
                        self.protocol.config.storage.account_url
                        + "/"
                        + self.protocol.config.storage.container
                        + "/"
                        + self.protocol.source_prefix
                        + "/"
                        + document.filename
                    ),
                    "content": " ".join(business_units(by_id[document.id])),
                    "embedding": [0.1, 0.2, 0.3],
                }
                for index, document in enumerate(reference.documents)
            ]
            if self.protocol.entity_extraction is not None:
                for chunk in self.chunks[arm]:
                    chunk["entity_data"] = {"entities": []}
            self.statuses[arm] = {
                "status": "running",
                "lastResult": {
                    "status": "success",
                    "startTime": "2026-10-28T10:00:00Z",
                    "endTime": "2026-10-28T10:01:00Z",
                    "errorMessage": None,
                    "itemsProcessed": len(reference.documents),
                    "itemsFailed": 0,
                    "errors": [],
                    "warnings": [],
                },
            }

    def __call__(self, request):
        self.requests.append(request)
        path = unquote(request.url.path).lstrip("/")
        if path in self.failures:
            return httpx.Response(self.failures[path], json={"error": "sentinel-sensitive-body"})
        if path == "openai/v1/embeddings":
            data = json.loads(request.content)
            assert data["encoding_format"] == "float"
            return httpx.Response(
                200,
                json={
                    "model": self.embedding_model,
                    "data": [
                        {"index": index, "embedding": self.embedding_vector}
                        for index in range(len(data["input"]))
                    ],
                    "usage": {"prompt_tokens": 25, "total_tokens": 25},
                },
            )
        if path.endswith("/search.status"):
            arm = "de_split" if "-de-" in path else "content_understanding"
            return httpx.Response(200, json=self.statuses[arm])
        if path.endswith("/docs/index"):
            arm = "de_split" if "-de-" in path else "content_understanding"
            body = json.loads(request.content)
            if self.fail_index_batch:
                self.fail_index_batch = False
                return httpx.Response(200, json={"value": [
                    {"key": item["id"], "status": False} for item in body["value"]
                ]})
            indexed = {item["id"]: item for item in self.chunks[arm]}
            if (
                self.delay_context_visibility and arm == "de_split"
                and self.stale_context_rows is None
            ):
                self.stale_context_rows = copy.deepcopy(self.chunks[arm])
            values = []
            for item in body["value"]:
                assert item["@search.action"] == "merge"
                indexed[item["id"]].update({
                    key: value for key, value in item.items() if key != "@search.action"
                })
                if self.quantize_written_vectors and "embedding" in item:
                    indexed[item["id"]]["embedding"] = [
                        0.0 if number == 0 else
                        struct.unpack("!f", struct.pack("!f", number))[0]
                        for number in item["embedding"]
                    ]
                values.append({"key": item["id"], "status": True})
            return httpx.Response(200, json={"value": values})
        if path.endswith("/docs/search"):
            arm = "de_split" if "-de-" in path else "content_understanding"
            body = json.loads(request.content)
            if body.get("search") == "*":
                last = body.get("filter", "").removeprefix("id gt '").removesuffix("'")
                source_rows = self.chunks[arm]
                if (
                    arm == "de_split" and self.delay_context_visibility
                    and self.stale_context_rows is not None
                ):
                    source_rows = self.stale_context_rows
                    self.delay_context_visibility = False
                values = [item for item in source_rows if item["id"] > last][
                    : min(self.page_size, body["top"])
                ]
            else:
                self.query_count += 1
                if (
                    self.fail_after_queries is not None
                    and self.query_count > self.fail_after_queries
                ):
                    return httpx.Response(403, json={"error": "sentinel-sensitive-body"})
                values = [
                    {"id": item["id"], "@search.score": float(100 - index)}
                    for index, item in enumerate(
                        self.query_rankings.get(
                            (arm, body.get("search", "")), self.rankings.get(arm, self.chunks[arm])
                        )[:50]
                    )
                ]
            result = {
                "value": values,
                "@search.coverage": 100 if body.get("search") == "*" else self.query_coverage,
            }
            if "semanticQuery" in body:
                for index, value in enumerate(values):
                    value["@search.rerankerScore"] = 4 - index / 100
                if self.semantic_failure == "partial":
                    result["@search.semanticPartialResponseReason"] = "CapacityOverloaded"
                if self.semantic_failure == "missing":
                    values[0].pop("@search.rerankerScore")
            return httpx.Response(200, json=result)
        if request.method == "GET":
            value = self.resources.get(path)
            return httpx.Response(404 if value is None else 200, json=value or {})
        assert request.method == "PUT"
        if "if-match" in request.headers:
            original = self.resources.get(path)
            if original is None or original["@odata.etag"] != request.headers["if-match"]:
                return httpx.Response(412, json={})
            body = json.loads(request.content)
            self.resources[path] = copy.deepcopy(body)
            self.resources[path]["@odata.etag"] = (
                '"version-updated-' + str(len(self.requests)) + '"'
            )
            return httpx.Response(200, json=self.resources[path])
        assert request.headers["if-none-match"] == "*"
        if path in self.resources:
            return httpx.Response(412, json={})
        body = json.loads(request.content)
        self.resources[path] = copy.deepcopy(body)
        if self.normalize_resources and path.startswith("skillsets/"):
            cognitive = self.resources[path]["cognitiveServices"]
            cognitive.pop("identity", None)
            cognitive["subdomainUrl"] = cognitive["subdomainUrl"].rstrip("/") + "/"
            for skill in self.resources[path]["skills"]:
                if "resourceUri" in skill:
                    skill["resourceUri"] = skill["resourceUri"].rstrip("/") + "/"
                if skill.get("name") == "pipeline-entities" and "commonModelParameters" in skill:
                    parameters = skill["commonModelParameters"]
                    parameters["temperature"] = int(parameters["temperature"])
        self.resources[path]["@odata.etag"] = '"version-one"'
        return httpx.Response(201, json=self.resources[path])
