from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


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
        self, collection: str, *, vector_size: int, distance: str = "Cosine"
    ) -> dict[str, Any]:
        if vector_size < 1:
            raise ValueError("vector_size must be positive")
        name = quote(collection, safe="")
        return self._request(
            "PUT",
            f"/collections/{name}",
            {"vectors": {"dense": {"size": vector_size, "distance": distance}}},
        )

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
        if query_filter is None:
            raise ValueError("query_filter is mandatory")
        if limit < 1:
            raise ValueError("limit must be positive")
        name = quote(collection, safe="")
        response = self._request(
            "POST",
            f"/collections/{name}/points/query",
            {
                "query": vector,
                "using": "dense",
                "filter": query_filter,
                "limit": limit,
                "with_payload": True,
            },
        )
        result = response.get("result", {})
        return list(result.get("points", []))
