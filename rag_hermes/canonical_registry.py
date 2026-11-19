"""Registre documentaire canonique de la V1 (SEC-01).

Le chemin V1 (`app_factory.build_service`) passait un `QdrantChunkRepository`
nu à `RagService` : l'index Qdrant était alors sa propre autorité ACL. Ce
module fournit l'autorité **canonique locale** qui manquait, alimentée par les
imports authentifiés et **indépendante de l'index**, plus le câblage qui la
place en barrière de lecture (`CanonicalAclSearch`) devant le générateur.

Ordre d'écriture imposé : le registre canonique **d'abord**, l'index ensuite.
Un document que l'index connaîtrait sans que le registre le connaisse serait
refusé à la lecture (donc abstention) ; l'inverse — registre en avance sur
l'index — échoue fermé sur la divergence de provenance. On préfère cet ordre :
il ne peut pas servir un passage dont l'autorité n'a pas la politique.

Limites assumées (ne pas sur-promettre) :

- L'autorité canonique indexe par `document_id` SEUL (`CanonicalAclAuthority`),
  alors que le service indexe par `(tenant_id, document_id)`. Deux locataires
  utilisant le même `document_id` sont donc refusés à l'enregistrement, faute
  de quoi la politique de l'un remplacerait celle de l'autre.
- Le verrou est un `threading.Lock` **intra-processus** : il ne sérialise pas
  deux serveurs V1 écrivant dans le même répertoire.
- Une désynchronisation registre/index se lit en abstention (document inconnu
  = non autorisé), pas en erreur : direction sûre, mais non diagnostique.
- Ce registre atteste ce qu'un import authentifié a déclaré ; il ne prouve pas
  l'origine des octets du document.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from typing import Any, Iterable, Mapping

from .acl_authority import AclPolicy, CanonicalAclAuthority
from .ingestion import Document
from .retrieval import CanonicalAclSearch

_STORE_FILENAME = "canonical_documents.jsonl"

_TEXT_FIELDS = (
    "document_id",
    "content",
    "tenant_id",
    "visibility",
    "owner_id",
    "source_uri",
)
_LIST_FIELDS = ("allowed_groups", "allowed_users")
_INT_FIELDS = ("classification", "doc_version", "acl_version")
_IDENTITY_FIELDS = ("document_id", "tenant_id", "owner_id", "visibility")
_RECORD_KEYS = frozenset(_TEXT_FIELDS + _LIST_FIELDS + _INT_FIELDS)


def _check_exact_str(value: object, field: str) -> str:
    if type(value) is not str:
        raise ValueError(f"canonical document field {field} must be an exact str")
    return value


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value)


def _validated_document(document: Any) -> Document:
    """Refuser tout document dont un champ d'autorité n'a pas le type exact.

    Les comparaisons de l'autorité canonique sont faites en Python : `True == 1`
    et une sous-classe de `str` peut surcharger `__eq__`/`__ne__`. Un contrôle
    de type ABSOLU (jamais `isinstance`) est donc la seule garde utile ici.
    """
    if type(document) is not Document:
        raise ValueError("canonical registry requires an exact Document instance")
    for field in _TEXT_FIELDS:
        _check_exact_str(getattr(document, field), field)
    for field in _LIST_FIELDS:
        value = getattr(document, field)
        if type(value) is not tuple or any(type(item) is not str for item in value):
            raise ValueError(
                f"canonical document field {field} must be a tuple of exact str"
            )
    for field in _INT_FIELDS:
        value = getattr(document, field)
        # `type(x) is int` exclut déjà bool, qui passerait un isinstance().
        if type(value) is not int:
            raise ValueError(f"canonical document field {field} must be an exact int")
        if value < 0:
            raise ValueError(f"canonical document field {field} must not be negative")
    for field in _IDENTITY_FIELDS:
        value = getattr(document, field)
        if not value:
            raise ValueError(f"canonical document field {field} must not be empty")
        if _has_control_characters(value):
            raise ValueError(
                f"canonical document field {field} must not contain control characters"
            )
    return document


def _record_from_document(document: Document) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "content": document.content,
        "tenant_id": document.tenant_id,
        "visibility": document.visibility,
        "owner_id": document.owner_id,
        "allowed_groups": list(document.allowed_groups),
        "allowed_users": list(document.allowed_users),
        "classification": document.classification,
        "doc_version": document.doc_version,
        "acl_version": document.acl_version,
        "source_uri": document.source_uri,
    }


def _document_from_record(record: Any) -> Document:
    """Relecture STRICTE : aucune coercition (`int()`/`tuple()`) n'est tolérée.

    `dataset._build_document` coerce (`int(True) == 1`) : acceptable pour un
    corpus de bench, inacceptable pour une autorité de sécurité relue à chaud.
    """
    if type(record) is not dict:
        raise ValueError("canonical record must be a JSON object")
    keys = set(record)
    if keys != _RECORD_KEYS:
        missing = sorted(_RECORD_KEYS - keys)
        extra = sorted(keys - _RECORD_KEYS)
        raise ValueError(
            f"canonical record key set mismatch (missing={missing}, unexpected={extra})"
        )
    for field in _LIST_FIELDS:
        if type(record[field]) is not list:
            raise ValueError(f"canonical record field {field} must be a JSON array")
    return _validated_document(
        Document(
            document_id=record["document_id"],
            content=record["content"],
            tenant_id=record["tenant_id"],
            visibility=record["visibility"],
            owner_id=record["owner_id"],
            allowed_groups=tuple(record["allowed_groups"]),
            allowed_users=tuple(record["allowed_users"]),
            classification=record["classification"],
            doc_version=record["doc_version"],
            source_uri=record["source_uri"],
            acl_version=record["acl_version"],
        )
    )


def _policy_from_document(document: Document) -> AclPolicy:
    return AclPolicy(
        tenant_id=document.tenant_id,
        visibility=document.visibility,
        owner_id=document.owner_id,
        allowed_groups=document.allowed_groups,
        allowed_users=document.allowed_users,
        classification=document.classification,
        acl_version=document.acl_version,
    )


class _LiveCanonicalAclAuthority(CanonicalAclAuthority):
    """Vue VIVANTE du registre : `CanonicalAclSearch` garde l'autorité à vie.

    La barrière reçoit l'autorité une fois, à la construction ; une autorité
    figée ignorerait tout import ultérieur. Hériter de `CanonicalAclAuthority`
    conserve son `authorize()` (donc ses contrôles de types de politique) et
    satisfait les appelants qui vérifient le type.
    """

    def __init__(self, registry: "CanonicalDocumentRegistry") -> None:
        super().__init__({})
        self._registry = registry

    def policy_for(self, document_id: str) -> AclPolicy | None:
        document = self._registry.source(document_id)
        return None if document is None else _policy_from_document(document)


class CanonicalDocumentRegistry:
    """Autorité documentaire locale, persistée hors de Qdrant.

    Fichier `canonical_documents.jsonl` en APPEND seul : la dernière ligne d'un
    `document_id` fait foi. Les invariants (collision de locataire, monotonie
    des versions) sont rejoués à la relecture, donc un fichier trafiqué refuse
    le démarrage au lieu de servir une politique affaiblie.
    """

    def __init__(self, store_dir: str | Path) -> None:
        path = Path(store_dir)
        if not path.is_absolute():
            raise ValueError("canonical store directory must be an absolute path")
        if not path.is_dir():
            # Créer le répertoire masquerait une faute de frappe de déploiement :
            # l'opérateur doit l'avoir créé délibérément.
            raise ValueError("canonical store directory must exist and be a directory")
        self._store_dir = path
        self._path = path / _STORE_FILENAME
        self._lock = threading.Lock()
        self._documents: dict[str, Document] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def authority(self) -> CanonicalAclAuthority:
        return self._authority

    def _load(self) -> None:
        self._authority = _LiveCanonicalAclAuthority(self)
        if not self._path.exists():
            return
        payload = self._path.read_bytes().decode("utf-8")
        for number, line in enumerate(payload.splitlines(), 1):
            if not line.strip():
                continue
            try:
                document = _document_from_record(json.loads(line))
                self._check_against_previous(document)
            except (ValueError, PermissionError) as exc:
                # Au démarrage, toute violation d'invariant est un refus de
                # démarrage : on uniformise en ValueError.
                raise ValueError(
                    f"invalid canonical document record at line {number}: {exc}"
                ) from exc
            self._documents[document.document_id] = document

    def _check_against_previous(self, document: Document) -> None:
        previous = self._documents.get(document.document_id)
        if previous is None:
            return
        if previous.tenant_id != document.tenant_id:
            raise ValueError(
                "canonical document_id already registered by another tenant"
            )
        if previous.owner_id != document.owner_id:
            # Écriture canonique AVANT l'index : sans ce refus, une tentative de
            # reprise rejetée ensuite par le dépôt laisserait le registre
            # attribuer le document à l'usurpateur (index et autorité divergents,
            # donc échec fermé pour le vrai propriétaire). La V1 ne transfère
            # jamais la propriété : `RagService.import_document` et le dépôt
            # Qdrant la refusent tous deux.
            # PermissionError (et non ValueError) : c'est un refus d'autorisation,
            # que la couche HTTP rend en 403 forbidden, pas en 400.
            raise PermissionError("canonical owner_id must not change")
        if document.doc_version < previous.doc_version:
            raise ValueError("canonical doc_version must not regress")
        if document.acl_version < previous.acl_version:
            raise ValueError("canonical acl_version must not regress")

    def source(self, document_id: str) -> Document | None:
        if type(document_id) is not str:
            return None
        return self._documents.get(document_id)

    def documents(self) -> Mapping[str, Document]:
        return dict(self._documents)

    def register(self, document: Any) -> Document:
        """Enregistrer la révision canonique AVANT toute écriture d'index.

        Échoue fermé : rien n'est publié en mémoire avant que la ligne ne soit
        écrite, relue à l'identique et `fsync`-ée.
        """
        validated = _validated_document(document)
        line = json.dumps(
            _record_from_document(validated),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=True,
        )
        # Valider la PROJECTION réellement persistée, pas seulement l'objet :
        # c'est elle que relira le prochain démarrage.
        if _document_from_record(json.loads(line)) != validated:
            raise ValueError("canonical record does not round-trip")
        with self._lock:
            self._check_against_previous(validated)
            with self._path.open("ab") as handle:
                handle.write(line.encode("ascii") + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._documents[validated.document_id] = validated
        return validated


class CanonicalWriteThrough:
    """Écrit la révision canonique, PUIS l'index. Jamais l'inverse."""

    def __init__(self, repository: Any, registry: CanonicalDocumentRegistry) -> None:
        if type(registry) is not CanonicalDocumentRegistry:
            raise ValueError(
                "write-through requires an exact CanonicalDocumentRegistry registry"
            )
        if not callable(getattr(repository, "replace_document", None)) or not callable(
            getattr(repository, "search", None)
        ):
            raise ValueError("repository must expose replace_document and search")
        self._repository = repository
        self._registry = registry

    def replace_document(self, document: Any, chunks: Iterable[Any]) -> Any:
        materialized = list(chunks)
        if not materialized:
            # Une révision vide n'est PAS une demande de suppression.
            raise ValueError("a replacement must carry at least one passage")
        self._registry.register(document)
        return self._repository.replace_document(document, materialized)

    def search(self, query: str, *, context: Any, limit: int = 10) -> Any:
        return self._repository.search(query, context=context, limit=limit)


def wrap_repository_with_canonical_barrier(
    repository: Any,
    registry: CanonicalDocumentRegistry,
    *,
    minimum_score: float,
) -> CanonicalAclSearch:
    """Câbler écriture canonique + barrière de lecture autour d'un dépôt.

    Le `minimum_score` doit être celui du `RagService` : `RagService` vérifie
    cette égalité, sans quoi un candidat autorisé mais sous le seuil de la
    barrière transformerait une erreur ACL en abstention.
    """
    if type(registry) is not CanonicalDocumentRegistry:
        raise ValueError(
            "canonical barrier requires an exact CanonicalDocumentRegistry registry"
        )
    return CanonicalAclSearch(
        CanonicalWriteThrough(repository, registry),
        registry.authority,
        minimum_score=minimum_score,
        source=registry.source,
    )
