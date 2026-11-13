from __future__ import annotations

import json
import math
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .acl import AuthorizationContext
from .qdrant_filter import build_qdrant_filter
from .qdrant_store import lexical_weights_to_sparse_vector


class QdrantRestClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=encoded,
            method=method,
            headers={"content-type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Qdrant HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Qdrant unavailable: {exc.reason}") from exc

    def collection_exists(self, collection: str) -> bool:
        name = quote(collection, safe="")
        response = self._request("GET", f"/collections/{name}/exists", {})
        result = response.get("result")
        if not isinstance(result, dict) or type(result.get("exists")) is not bool:
            raise RuntimeError("Qdrant returned malformed collection existence result")
        return result["exists"]

    def get_collection(self, collection: str) -> dict[str, Any]:
        name = quote(collection, safe="")
        response = self._request("GET", f"/collections/{name}", {})
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Qdrant returned malformed collection metadata")
        return result

    def create_collection(
        self, collection: str, *, vector_size: int, distance: str = "Cosine",
        sparse: bool = False,
    ) -> dict[str, Any]:
        if vector_size < 1:
            raise ValueError("vector_size must be positive")
        if type(sparse) is not bool:
            raise ValueError("sparse must be a boolean")
        name = quote(collection, safe="")
        body: dict[str, Any] = {
            "vectors": {"dense": {"size": vector_size, "distance": distance}}
        }
        if sparse:
            body["sparse_vectors"] = {"sparse": {}}
        return self._request("PUT", f"/collections/{name}", body)

    def delete_collection(self, collection: str) -> dict[str, Any]:
        name = quote(collection, safe="")
        return self._request("DELETE", f"/collections/{name}", {})

    def create_payload_index(
        self, collection: str, field_name: str, field_schema: str | dict[str, Any]
    ) -> dict[str, Any]:
        name = quote(collection, safe="")
        return self._request(
            "PUT",
            f"/collections/{name}/index?wait=true",
            {"field_name": field_name, "field_schema": field_schema},
        )

    def scroll(
        self,
        collection: str,
        *,
        query_filter: dict[str, Any] | None,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        if not query_filter:
            raise ValueError("query_filter is mandatory")
        if limit < 1:
            raise ValueError("limit must be positive")
        name = quote(collection, safe="")
        response = self._request(
            "POST",
            f"/collections/{name}/points/scroll",
            {
                "filter": query_filter,
                "limit": limit,
                "with_payload": True,
            },
        )
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list):
            raise RuntimeError("Qdrant returned malformed scroll result")
        return list(result["points"])

    def upsert(
        self, collection: str, points: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not points:
            raise ValueError("at least one point is required")
        name = quote(collection, safe="")
        return self._request(
            "PUT", f"/collections/{name}/points?wait=true", {"points": points}
        )

    def delete_points(
        self, collection: str, query_filter: dict[str, Any] | None
    ) -> dict[str, Any]:
        if not query_filter:
            raise ValueError("query_filter is mandatory")
        name = quote(collection, safe="")
        return self._request(
            "POST",
            f"/collections/{name}/points/delete?wait=true",
            {"filter": query_filter},
        )

    def query(
        self,
        collection: str,
        vector: list[float],
        *,
        query_filter: dict[str, Any] | None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return self._query_named(collection, vector, using="dense",
                                 query_filter=query_filter, limit=limit)

    def query_sparse(
        self,
        collection: str,
        lexical_weights: object,
        *,
        context: AuthorizationContext,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if (type(context) is not AuthorizationContext
            or type(context.tenant_id) is not str or not context.tenant_id
            or type(context.user_id) is not str or not context.user_id
            or type(context.groups) is not tuple
            or any(type(group) is not str or not group for group in context.groups)
            or type(context.clearance) is not int or context.clearance < 0):
            raise ValueError("valid authorization context is required")
        sparse = lexical_weights_to_sparse_vector(lexical_weights)
        return self._query_named(collection, sparse, using="sparse",
                                 query_filter=build_qdrant_filter(context), limit=limit)

    def _query_named(
        self,
        collection: str,
        vector: Any,
        *,
        using: str,
        query_filter: dict[str, Any] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not query_filter:
            raise ValueError("query_filter is mandatory")
        if limit < 1:
            raise ValueError("limit must be positive")
        name = quote(collection, safe="")
        response = self._request(
            "POST",
            f"/collections/{name}/points/query",
            {
                "query": vector,
                "using": using,
                "filter": query_filter,
                "limit": limit,
                "with_payload": True,
            },
        )
        if "status" in response and response["status"] != "ok":
            raise RuntimeError("Qdrant returned invalid query status")
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list):
            raise RuntimeError("Qdrant returned malformed query result")
        if len(result["points"]) > limit:
            raise RuntimeError("Qdrant returned more points than requested")
        for point in result["points"]:
            if not isinstance(point, dict) or (
                type(point.get("score")) not in (int, float)
                or not math.isfinite(point["score"])
            ):
                raise RuntimeError("Qdrant returned invalid query score")
        return list(result["points"])


class QdrantAuditRestClient(QdrantRestClient):
    """Audit-operator client; only this variant exposes unfiltered scrolling.

    Use separate operator credentials and never inject this class into a user
    request handler. Python class separation is not an authorization boundary.
    """

    def scroll_page(
        self, collection: str, *, limit: int = 100, offset: str | int | None = None
    ) -> tuple[list[dict[str, Any]], str | int | None]:
        if not 1 <= limit <= 1000:
            raise ValueError("bounded scroll limit is required")
        if offset is not None and type(offset) not in (str, int):
            raise ValueError("invalid scroll offset")
        name = quote(collection, safe="")
        body: dict[str, Any] = {
            "limit": limit, "with_payload": True, "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        response = self._request("POST", f"/collections/{name}/points/scroll", body)
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("points"), list) or "next_page_offset" not in result:
            raise RuntimeError("Qdrant returned malformed paginated scroll result")
        if len(result["points"]) > limit:
            raise RuntimeError("Qdrant returned more points than the requested limit")
        cursor = result["next_page_offset"]
        if cursor is not None and type(cursor) not in (str, int):
            raise RuntimeError("Qdrant returned malformed scroll cursor")
        if cursor is not None and offset is not None and cursor == offset:
            # A cursor pointing at the page just read would loop forever; the
            # caller cannot distinguish it from progress.
            raise RuntimeError("Qdrant returned a self-referential scroll cursor")
        return list(result["points"]), cursor
