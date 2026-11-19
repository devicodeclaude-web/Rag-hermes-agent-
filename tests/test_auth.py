from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from rag_hermes.acl import AuthorizationContext
from rag_hermes.auth import (
    AuthenticationError,
    TokenAuthenticator,
    generate_dev_authenticator,
    load_authenticator_from_file,
)


ALICE = AuthorizationContext(
    tenant_id="alpha", user_id="alice", groups=("support",), clearance=1
)
BOB = AuthorizationContext(
    tenant_id="beta", user_id="bob", groups=(), clearance=5
)

ALICE_TOKEN = "tok-auth-alice-0123456789"
BOB_TOKEN = "tok-auth-bob-01234567890"


def _env(token: str | None) -> dict[str, str]:
    if token is None:
        return {}
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class TokenAuthenticatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = TokenAuthenticator.from_principals(
            {ALICE_TOKEN: ALICE, BOB_TOKEN: BOB}
        )

    def test_valid_token_resolves_bound_context(self) -> None:
        self.assertEqual(self.auth.authenticate(_env(ALICE_TOKEN)), ALICE)
        self.assertEqual(self.auth.authenticate(_env(BOB_TOKEN)), BOB)

    def test_missing_header_raises(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.auth.authenticate(_env(None))

    def test_wrong_scheme_raises(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.auth.authenticate({"HTTP_AUTHORIZATION": f"Basic {ALICE_TOKEN}"})

    def test_unknown_token_raises(self) -> None:
        with self.assertRaises(AuthenticationError):
            self.auth.authenticate(_env("tok-unknown-000000000000"))

    def test_empty_principals_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TokenAuthenticator.from_principals({})

    def test_short_token_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TokenAuthenticator.from_principals({"short": ALICE})

    def test_plaintext_token_is_not_stored(self) -> None:
        # Le jeton en clair ne doit apparaître nulle part dans l'objet.
        blob = repr(self.auth)
        self.assertNotIn(ALICE_TOKEN, blob)
        self.assertNotIn(BOB_TOKEN, blob)


class LoadFromFileTests(unittest.TestCase):
    def _write(self, document: dict) -> str:
        path = Path(tempfile.mkdtemp()) / "principals.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return str(path)

    def test_load_valid_file(self) -> None:
        path = self._write(
            {
                "principals": [
                    {
                        "token": ALICE_TOKEN,
                        "tenant_id": "alpha",
                        "user_id": "alice",
                        "groups": ["support"],
                        "clearance": 1,
                    }
                ]
            }
        )
        auth = load_authenticator_from_file(path)
        self.assertEqual(auth.authenticate(_env(ALICE_TOKEN)), ALICE)

    def test_missing_principals_key_rejected(self) -> None:
        path = self._write({"nope": []})
        with self.assertRaises(ValueError):
            load_authenticator_from_file(path)

    def test_negative_clearance_rejected(self) -> None:
        path = self._write(
            {
                "principals": [
                    {
                        "token": ALICE_TOKEN,
                        "tenant_id": "alpha",
                        "user_id": "alice",
                        "groups": [],
                        "clearance": -1,
                    }
                ]
            }
        )
        with self.assertRaises(ValueError):
            load_authenticator_from_file(path)

    def test_reserved_public_tenant_is_refused(self) -> None:
        # `tenant_id == "public"` est le tenant GLOBAL lisible par tous les
        # tenants (acl.py `is_global_public`, qdrant_filter.py). Un principal
        # porteur de ce tenant écrirait donc dans le corpus commun : le
        # registre doit le refuser à la lecture du fichier (fail-closed), y
        # compris quand la valeur n'est réservée qu'après `strip()`.
        for raw_tenant in ("public", "  public  "):
            with self.subTest(tenant=raw_tenant):
                path = self._write(
                    {
                        "principals": [
                            {
                                "token": ALICE_TOKEN,
                                "tenant_id": raw_tenant,
                                "user_id": "alice",
                                "groups": [],
                                "clearance": 1,
                            }
                        ]
                    }
                )
                with self.assertRaises(ValueError):
                    load_authenticator_from_file(path)

    def test_tenant_only_prefixed_by_public_stays_accepted(self) -> None:
        # Seule la valeur exacte est réservée : "public-corp" est un tenant
        # ordinaire et ne doit pas être bloqué par le garde.
        path = self._write(
            {
                "principals": [
                    {
                        "token": ALICE_TOKEN,
                        "tenant_id": "public-corp",
                        "user_id": "alice",
                        "groups": [],
                        "clearance": 1,
                    }
                ]
            }
        )
        auth = load_authenticator_from_file(path)
        self.assertEqual(auth.authenticate(_env(ALICE_TOKEN)).tenant_id, "public-corp")


class DevAuthenticatorTests(unittest.TestCase):
    def test_generated_token_authenticates(self) -> None:
        token, auth = generate_dev_authenticator()
        self.assertGreaterEqual(len(token), 16)
        context = auth.authenticate(_env(token))
        self.assertEqual(context.tenant_id, "local")
        self.assertEqual(context.user_id, "admin")

    def test_each_call_yields_a_fresh_token(self) -> None:
        token_a, _ = generate_dev_authenticator()
        token_b, _ = generate_dev_authenticator()
        self.assertNotEqual(token_a, token_b)


if __name__ == "__main__":
    unittest.main()
