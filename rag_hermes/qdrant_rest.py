from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .acl import AuthorizationContext
from .qdrant_filter import build_qdrant_filter
from .qdrant_store import lexical_weights_to_sparse_vector


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_qdrant_endpoint(base_url: str, api_key: str) -> str:
    # Never let urlsplit silently discard control characters, or let a
    # redirect forward the credential to an endpoint we did not configure.
    if (type(base_url) is not str or not base_url
        or any(ord(char) <= 32 or ord(char) == 127 for char in base_url)
        or "\\" in base_url or "?" in base_url or "#" in base_url):
        raise ValueError("Qdrant URL is invalid")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        # urlsplit/port errors may quote the operator-supplied URL (including
        # accidental credentials); never surface them in a logged traceback.
        raise ValueError("Qdrant URL is invalid") from None
    if (parsed.scheme not in {"http", "https"} or not hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.scheme == "http" and hostname.lower() not in
            {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Qdrant URL requires HTTPS or explicit loopback HTTP, without URL credentials or path")
    if (type(api_key) is not str or any(
        ord(char) < 33 or ord(char) > 126 for char in api_key
    )):
        raise ValueError("api_key must contain visible ASCII characters only")
    return base_url.rstrip("/")


class QdrantHttpTransport:
    """Credential-carrying HTTP plumbing, with no Qdrant operation on it.

    Separated from the read/write client so that an audit reader can hold a
    transport without holding any mutation method (SEC-03).
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0, api_key: str = ""):
        self.base_url = _validate_qdrant_endpoint(base_url, api_key)
        self.timeout = timeout
        self._api_key = api_key
        # Environment proxies can exfiltrate api-key even for a loopback URL.
        # This transport never inherits proxy settings implicitly.
        self._opener = build_opener(ProxyHandler({}), _NoRedirectHandler())

    def request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["api-key"] = self._api_key
        request = Request(
            self.base_url + path,
            data=encoded,
            method=method,
            headers=headers,
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            raise RuntimeError(f"Qdrant HTTP {exc.code}") from None
        except URLError as exc:
            raise RuntimeError("Qdrant unavailable") from None


def _is_canonical_uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


class QdrantRestClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0, api_key: str = ""):
        self._transport = QdrantHttpTransport(base_url, timeout=timeout, api_key=api_key)
        self.base_url = self._transport.base_url
        self.timeout = self._transport.timeout
        self._api_key = api_key

    def _request(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._transport.request(method, path, body)

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

    def list_collections(self) -> tuple[str, ...]:
        """Read physical collection names, not names resolved through aliases.

        This is one observation, not proof that a collection cannot be deleted
        and recreated while a reconciliation operation is running.
        """
        response = self._request("GET", "/collections", {})
        result = response.get("result")
        if response.get("status") != "ok" or type(result) is not dict:
            raise RuntimeError("Qdrant returned an invalid collection list")
        entries = result.get("collections")
        if type(entries) is not list or any(
            type(entry) is not dict or set(entry) != {"name"}
            or type(entry["name"]) is not str or not entry["name"]
            for entry in entries
        ):
            raise RuntimeError("Qdrant returned an invalid collection list")
        names = tuple(entry["name"] for entry in entries)
        if len(names) != len(set(names)):
            raise RuntimeError("Qdrant returned an invalid collection list")
        return names

    def create_collection(
        self, collection: str, *, vector_size: int, distance: str = "Cosine",
        sparse: bool = False, generation_uuid: str | None = None,
    ) -> dict[str, Any]:
        if vector_size < 1:
            raise ValueError("vector_size must be positive")
        if type(sparse) is not bool:
            raise ValueError("sparse must be a boolean")
        if generation_uuid is not None:
            try:
                valid_generation = (
                    type(generation_uuid) is str
                    and str(UUID(generation_uuid)) == generation_uuid
                    and UUID(generation_uuid).version == 4
                )
            except (ValueError, AttributeError, TypeError):
                valid_generation = False
            if not valid_generation:
                raise ValueError("generation_uuid must be a canonical UUIDv4")
        name = quote(collection, safe="")
        body: dict[str, Any] = {
            "vectors": {"dense": {"size": vector_size, "distance": distance}}
        }
        if sparse:
            body["sparse_vectors"] = {"sparse": {}}
        if generation_uuid is not None:
            # Provisioner-only field. Merely writing it is NOT proof of an
            # original, independent operator receipt or an immutable instance.
            body["metadata"] = {"hermes_generation_uuid": generation_uuid}
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

    def scroll_filtered_page(
        self,
        collection: str,
        *,
        query_filter: dict[str, Any] | None,
        limit: int = 1,
        offset: int | str | None = None,
    ) -> tuple[list[dict[str, Any]], int | str | None]:
        """Read one filtered page, retaining Qdrant's completion cursor."""
        if not query_filter:
            raise ValueError("query_filter is mandatory")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be positive")
        if offset is not None and (
            type(offset) not in (int, str)
            or isinstance(offset, int) and offset < 0
            or isinstance(offset, str) and not offset
        ):
            raise ValueError("offset must be a point identifier")
        name = quote(collection, safe="")
        body: dict[str, Any] = {
            "filter": query_filter, "limit": limit, "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        response = self._request("POST", f"/collections/{name}/points/scroll", body)
        if response.get("status") != "ok":
            raise RuntimeError("Qdrant returned invalid scroll status")
        result = response.get("result")
        if (
            type(result) is not dict
            or type(result.get("points")) is not list
            or "next_page_offset" not in result
        ):
            raise RuntimeError("Qdrant returned malformed scroll result")
        points = result["points"]
        cursor = result["next_page_offset"]
        if len(points) > limit or (
            cursor is not None and (
                type(cursor) not in (int, str)
                or isinstance(cursor, int) and cursor < 0
                or isinstance(cursor, str) and not cursor
            )
        ):
            raise RuntimeError("Qdrant returned malformed scroll page")
        return points, cursor

    def mark_points_tombstoned(self, collection: str, ids: list[str]) -> None:
        """Low-level ID-bounded payload write; caller must prove authorization.

        A completed operation is NOT proof that these IDs existed or belonged to
        the document. The caller must scan ownership first and reread afterwards.
        This method is not wired into an API or the deletion flow (#71, B1).
        """
        if type(ids) is not list or not ids or any(
            type(point_id) is not str or len(point_id) != 36
            or not _is_canonical_uuid(point_id) for point_id in ids
        ) or len(set(ids)) != len(ids):
            raise ValueError("tombstone requires unique canonical UUID point ids")
        name = quote(collection, safe="")
        response = self._request(
            "POST", f"/collections/{name}/points/payload?wait=true",
            {"payload": {"tombstone": True}, "points": ids},
        )
        result = response.get("result") if type(response) is dict else None
        operation_id = result.get("operation_id") if type(result) is dict else None
        if (type(response) is not dict or response.get("status") != "ok"
            or type(result) is not dict
            or result.get("status") != "completed"
            or operation_id is not None and (
                type(operation_id) is not int or not 0 <= operation_id < 2**64
            )):
            raise RuntimeError("Qdrant did not confirm tombstone completion")

    def upsert(
        self, collection: str, points: list[dict[str, Any]], *,
        update_filter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not points:
            raise ValueError("at least one point is required")
        if update_filter is not None and (type(update_filter) is not dict or not update_filter):
            raise ValueError("update_filter must be a nonempty filter")
        name = quote(collection, safe="")
        body: dict[str, Any] = {"points": points}
        if update_filter is not None:
            body["update_filter"] = update_filter
        return self._request("PUT", f"/collections/{name}/points?wait=true", body)

    def retrieve_points(
        self, collection: str, ids: list[str | int], *, with_vector: bool = True,
    ) -> list[dict[str, Any]]:
        if type(with_vector) is not bool:
            raise ValueError("with_vector must be a boolean")
        if (
            type(ids) is not list or not ids
            or any(
                type(point_id) not in (str, int)
                or isinstance(point_id, str) and not point_id
                or isinstance(point_id, int) and point_id < 0
                for point_id in ids
            )
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("retrieve ids must be unique point identifiers")
        name = quote(collection, safe="")
        response = self._request(
            "POST", f"/collections/{name}/points",
            {"ids": ids, "with_payload": True, "with_vector": with_vector},
        )
        result = response.get("result")
        if response.get("status") != "ok" or type(result) is not list or len(result) > len(ids):
            raise RuntimeError("Qdrant returned malformed retrieve result")
        seen: set[str | int] = set()
        for point in result:
            point_id = point.get("id") if type(point) is dict else None
            if type(point_id) not in (str, int) or point_id not in ids or point_id in seen:
                raise RuntimeError("Qdrant returned malformed retrieve point")
            seen.add(point_id)
        return result

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


class QdrantAuditClient:
    """Audit-operator reader: unfiltered scrolling, and nothing else.

    It holds a transport, not a read/write client, so no mutation method
    exists anywhere in its object graph. Give it its own read-only operator
    credential and never inject it into a user request handler. Python object
    composition is still not an authorization boundary: Qdrant must enforce
    the credential's rights.
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0, api_key: str = ""):
        self._transport = QdrantHttpTransport(base_url, timeout=timeout, api_key=api_key)

    @property
    def base_url(self) -> str:
        return self._transport.base_url

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
        response = self._transport.request("POST", f"/collections/{name}/points/scroll", body)
        if "status" in response and response["status"] != "ok":
            raise RuntimeError("Qdrant returned invalid audit scroll status")
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
