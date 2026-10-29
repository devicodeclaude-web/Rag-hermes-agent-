"""Authentification de la V1 locale : contexte d'autorisation dérivé côté serveur.

RÈGLE DE SÉCURITÉ : le contexte d'autorisation (tenant, utilisateur, groupes,
clearance) n'est JAMAIS lu dans le corps de la requête. Il est dérivé côté
serveur d'un jeton porteur (`Authorization: Bearer <token>`), vérifié contre un
registre de principaux chargé au démarrage. C'est le palier local en attendant
un fournisseur d'identité (Keycloak/OIDC) : l'interface de résolution reste la
même (`Authenticator.authenticate(environ) -> AuthorizationContext`), seule la
source du jeton changera.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from typing import Any, Mapping

from .acl import AuthorizationContext


class AuthenticationError(Exception):
    """L'appelant n'a pas présenté un jeton valide. Jamais détaillée au client."""


def _sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _parse_bearer(environ: Mapping[str, Any]) -> str:
    header = str(environ.get("HTTP_AUTHORIZATION", "")).strip()
    if not header:
        raise AuthenticationError("missing Authorization header")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise AuthenticationError("Authorization header must be a Bearer token")
    return value.strip()


@dataclass(frozen=True)
class TokenAuthenticator:
    """Associe un jeton porteur à un contexte d'autorisation fixé côté serveur.

    Les comparaisons se font en temps constant sur le condensé SHA-256 du jeton
    (pas d'égalité de chaîne directe, qui fuit par timing). Le jeton en clair
    n'est jamais stocké : seul son condensé l'est.
    """

    _by_digest: tuple[tuple[bytes, AuthorizationContext], ...]

    @classmethod
    def from_principals(
        cls, principals: Mapping[str, AuthorizationContext]
    ) -> "TokenAuthenticator":
        if not principals:
            raise ValueError("au moins un principal (jeton -> contexte) est requis")
        entries: list[tuple[bytes, AuthorizationContext]] = []
        seen: set[bytes] = set()
        for token, context in principals.items():
            if not isinstance(token, str) or len(token) < 16:
                raise ValueError("un jeton doit être une chaîne d'au moins 16 caractères")
            digest = _sha256(token)
            if digest in seen:
                raise ValueError("jeton en double dans le registre de principaux")
            seen.add(digest)
            entries.append((digest, context))
        return cls(tuple(entries))

    def authenticate(self, environ: Mapping[str, Any]) -> AuthorizationContext:
        presented = _sha256(_parse_bearer(environ))
        # Balaie TOUTES les entrées avec compare_digest pour ne pas court-circuiter
        # (temps constant indépendant du jeton correct trouvé ou non).
        matched: AuthorizationContext | None = None
        for digest, context in self._by_digest:
            if hmac.compare_digest(presented, digest):
                matched = context
        if matched is None:
            raise AuthenticationError("unknown bearer token")
        return matched


def _context_from_entry(entry: Mapping[str, Any]) -> AuthorizationContext:
    try:
        tenant_id = str(entry["tenant_id"]).strip()
        user_id = str(entry["user_id"]).strip()
        clearance = entry["clearance"]
        groups_raw = entry.get("groups", [])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"principal invalide : {exc}") from exc
    if not tenant_id or not user_id:
        raise ValueError("principal invalide : tenant_id et user_id requis")
    if type(clearance) is not int or clearance < 0:
        raise ValueError("principal invalide : clearance doit être un entier >= 0")
    if not isinstance(groups_raw, list) or not all(
        isinstance(g, str) for g in groups_raw
    ):
        raise ValueError("principal invalide : groups doit être une liste de chaînes")
    return AuthorizationContext(
        tenant_id=tenant_id,
        user_id=user_id,
        groups=tuple(g.strip() for g in groups_raw),
        clearance=clearance,
    )


def load_authenticator_from_file(path: str | Path) -> TokenAuthenticator:
    """Charge un registre de principaux depuis un fichier JSON.

    Format attendu :
        {"principals": [
            {"token": "<secret>", "tenant_id": "...", "user_id": "...",
             "groups": ["..."], "clearance": 1}
        ]}
    """
    raw = Path(path).read_text(encoding="utf-8")
    document = json.loads(raw)
    if not isinstance(document, dict) or not isinstance(
        document.get("principals"), list
    ):
        raise ValueError("le fichier de principaux doit contenir une liste 'principals'")
    principals: dict[str, AuthorizationContext] = {}
    for entry in document["principals"]:
        if not isinstance(entry, dict):
            raise ValueError("chaque principal doit être un objet JSON")
        token = entry.get("token")
        if not isinstance(token, str):
            raise ValueError("chaque principal doit porter un 'token' (chaîne)")
        principals[token] = _context_from_entry(entry)
    return TokenAuthenticator.from_principals(principals)


def generate_dev_authenticator() -> tuple[str, TokenAuthenticator]:
    """Fabrique un authentificateur de DÉVELOPPEMENT avec un jeton éphémère.

    Utilisé quand aucun fichier de principaux n'est fourni : le serveur reste
    fail-closed (un jeton est TOUJOURS exigé), mais le jeton est généré et
    imprimé au démarrage pour l'ergonomie locale. Il ne survit pas au process.
    """
    token = secrets.token_urlsafe(32)
    context = AuthorizationContext(
        tenant_id="local",
        user_id="admin",
        groups=("owners",),
        clearance=1_000,
    )
    return token, TokenAuthenticator.from_principals({token: context})
