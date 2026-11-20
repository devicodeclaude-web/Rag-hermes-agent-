from __future__ import annotations

import base64
import json
import time
from unittest import TestCase

from rag_hermes.qdrant_identity import (
    collection_access_claims,
    mint_collection_token,
    validate_service_tokens,
)

SECRET = "operator-admin-secret"
COLLECTION = "hermes_chunks_v1"


def _token(payload: dict, *, secret: str = SECRET) -> str:
    import hashlib
    import hmac

    def encode(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    data = f"{encode({'alg': 'HS256', 'typ': 'JWT'})}.{encode(payload)}"
    signature = hmac.new(secret.encode("utf-8"), data.encode("ascii"), hashlib.sha256).digest()
    return data + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


class MintCollectionTokenTests(TestCase):
    def test_minted_token_carries_only_the_requested_collection_access(self) -> None:
        token = mint_collection_token(SECRET, collection=COLLECTION, access="r", ttl_seconds=3600)
        self.assertEqual(len(token.split(".")), 3)
        self.assertEqual(collection_access_claims(token), ((COLLECTION, "r"),))
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        self.assertGreater(payload["exp"], time.time())

    def test_mint_refuses_unknown_access_modes_and_empty_inputs(self) -> None:
        for kwargs in (
            {"collection": COLLECTION, "access": "m", "ttl_seconds": 60},
            {"collection": COLLECTION, "access": "rw", "ttl_seconds": 60},
            {"collection": "", "access": "r", "ttl_seconds": 60},
            {"collection": COLLECTION, "access": "r", "ttl_seconds": 0},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                mint_collection_token(SECRET, **kwargs)
        with self.assertRaises(ValueError):
            mint_collection_token("", collection=COLLECTION, access="r", ttl_seconds=60)


class ValidateServiceTokensTests(TestCase):
    def setUp(self) -> None:
        self.query = mint_collection_token(SECRET, collection=COLLECTION, access="r", ttl_seconds=3600)
        self.write = mint_collection_token(SECRET, collection=COLLECTION, access="prw", ttl_seconds=3600)

    def accept(self, **override: str) -> None:
        keys = {"query_key": self.query, "write_key": self.write, "collection": COLLECTION}
        keys.update(override)
        validate_service_tokens(**keys)

    def reject(self, *, secret_free: tuple[str, ...] = (), **override: str) -> str:
        keys = {"query_key": self.query, "write_key": self.write, "collection": COLLECTION}
        keys.update(override)
        with self.assertRaises(ValueError) as caught:
            validate_service_tokens(**keys)
        message = str(caught.exception)
        for value in (*secret_free, SECRET, self.query, self.write):
            self.assertNotIn(value, message)
        return message

    def test_accepts_read_only_query_and_points_write_tokens(self) -> None:
        self.accept()

    def test_rejects_a_raw_admin_api_key_naming_the_variable_only(self) -> None:
        message = self.reject(query_key="operator-admin-secret-raw",
                              secret_free=("operator-admin-secret-raw",))
        self.assertIn("RAG_QDRANT_QUERY_API_KEY", message)
        write_message = self.reject(write_key="operator-admin-secret-raw",
                                    secret_free=("operator-admin-secret-raw",))
        self.assertIn("RAG_QDRANT_WRITE_API_KEY", write_message)

    def test_rejects_a_write_capable_token_as_the_query_identity(self) -> None:
        self.assertIn("RAG_QDRANT_QUERY_API_KEY", self.reject(query_key=self.write))
        other_write = mint_collection_token(
            SECRET, collection=COLLECTION, access="prw", ttl_seconds=7200
        )
        self.assertNotEqual(other_write, self.write)
        self.assertIn("RAG_QDRANT_QUERY_API_KEY", self.reject(query_key=other_write))

    def test_rejects_a_read_only_token_as_the_write_identity(self) -> None:
        other_read = mint_collection_token(
            SECRET, collection=COLLECTION, access="r", ttl_seconds=7200
        )
        self.assertIn("RAG_QDRANT_WRITE_API_KEY", self.reject(write_key=other_read))

    def test_rejects_global_access_manage_and_missing_access_claim(self) -> None:
        for payload in (
            {"access": "m", "exp": int(time.time()) + 60},
            {"access": "r", "exp": int(time.time()) + 60},
            {"exp": int(time.time()) + 60},
            {"access": [{"collection": COLLECTION, "access": "rw"}], "exp": int(time.time()) + 60},
            {"access": [{"collection": COLLECTION, "access": "m"}], "exp": int(time.time()) + 60},
        ):
            with self.subTest(payload=payload):
                self.reject(query_key=_token(payload))

    def test_rejects_tokens_scoped_to_another_or_to_extra_collections(self) -> None:
        now = int(time.time()) + 60
        foreign = _token({"access": [{"collection": "other", "access": "r"}], "exp": now})
        wide = _token({
            "access": [{"collection": COLLECTION, "access": "r"},
                       {"collection": "other", "access": "r"}],
            "exp": now,
        })
        self.assertIn("RAG_QDRANT_QUERY_API_KEY", self.reject(query_key=foreign))
        self.assertIn("RAG_QDRANT_QUERY_API_KEY", self.reject(query_key=wide))

    def test_rejects_identical_tokens_and_malformed_structures(self) -> None:
        self.reject(write_key=self.query, query_key=self.query)
        for broken in ("", "   ", "a.b", "a.b.c.d", "not-base64url.$$$.sig",
                       self.query.split(".")[0] + "..sig"):
            with self.subTest(broken=broken):
                self.reject(query_key=broken)

    def test_rejects_an_expired_token_without_revealing_it(self) -> None:
        stale = _token({"access": [{"collection": COLLECTION, "access": "r"}],
                        "exp": int(time.time()) - 1})
        self.assertIn("RAG_QDRANT_QUERY_API_KEY", self.reject(query_key=stale))
