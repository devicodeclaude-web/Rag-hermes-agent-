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
- Un second verrou `flock` local bloque les lectures coopérantes pendant
  registre + remplacement Qdrant, et les imports pendant génération/citation.
  Ni Qdrant directement, ni les autres hôtes ne sont couverts.
- Une désynchronisation registre/index se lit en abstention (document inconnu
  = non autorisé), pas en erreur : direction sûre, mais non diagnostique.
- Ce registre atteste ce qu'un import authentifié a déclaré ; il ne prouve pas
  l'origine des octets du document.
"""

from __future__ import annotations

from contextlib import contextmanager
import contextlib
import ctypes
from dataclasses import replace
import hashlib
import json
import errno
import fcntl
import os
from pathlib import Path
import stat
import threading
import weakref
from typing import Any, Callable, Iterable, Mapping

from .acl_authority import AclPolicy, CanonicalAclAuthority
from .ingestion import Document
from .ingestion_events import validate_event
from .retrieval import CanonicalAclSearch

_STORE_FILENAME = "canonical_documents.jsonl"
_TRANSACTION_LOCK_FILENAME = "canonical_transaction.lock"
_ANCHOR_FILENAME = "canonical_anchor.json"
_TRANSACTION_LEASES = threading.local()
_ACTIVE_TRANSACTION_FDS_LOCK = threading.Lock()
# token -> descriptor for every open file description carrying an flock lease.
_ACTIVE_TRANSACTION_FDS: dict[int, int] = {}
_NEXT_LEASE_TOKEN = 0
_LIVE_REGISTRIES: "weakref.WeakSet[CanonicalDocumentRegistry]" = weakref.WeakSet()


def _after_fork_in_child() -> None:
    # flock locks an open file description, which is inherited across fork.
    # Even a child forked by a DIFFERENT thread can keep a parent's lease
    # alive. Close every tracked descriptor, then discard inherited TLS state.
    for file_fd in _ACTIVE_TRANSACTION_FDS.values():
        try:
            os.close(file_fd)
        except OSError:
            pass
    _ACTIVE_TRANSACTION_FDS.clear()
    _TRANSACTION_LEASES.held = {}
    # Only the forking thread survives in the child, so a mutex another
    # thread held is inherited locked and would deadlock the child forever.
    # The state it guarded is re-verified from the file under flock anyway.
    for registry in _LIVE_REGISTRIES:
        registry._lock = threading.Lock()
    _ACTIVE_TRANSACTION_FDS_LOCK.release()


os.register_at_fork(
    before=_ACTIVE_TRANSACTION_FDS_LOCK.acquire,
    after_in_parent=_ACTIVE_TRANSACTION_FDS_LOCK.release,
    after_in_child=_after_fork_in_child,
)

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

# Suppression logique réversible (issue #71, Découpage A).
_STATE_ACTIVE = "active"
_STATE_INACTIVE = "inactive"
_VALID_STATES = frozenset({_STATE_ACTIVE, _STATE_INACTIVE})
# Jeu de clés d'un enregistrement MODERNE : les 11 clés legacy + `state`. Un
# enregistrement legacy (sans `state`) se relit comme actif, mais toute NOUVELLE
# écriture émet toujours `state` (y compris `active`) : une clé perdue par un
# bug ne doit jamais se relire silencieusement comme `active`.
_MODERN_RECORD_KEYS = _RECORD_KEYS | {"state"}
# Version du schéma d'ancre moderne. Une ancre legacy (sans `schema_version`)
# reste vérifiable mais ne peut attester QUE des historiques entièrement legacy.
_ANCHOR_SCHEMA_VERSION = 3


class CanonicalStoreError(RuntimeError):
    """The canonical storage is unavailable or rolled back, not a client error."""


def _file_identity(fd: int) -> tuple[int, int, int, int, int]:
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _open_private_dir(path: Path) -> int:
    """Ouvrir le répertoire de stockage et contrôler le descripteur RÉEL.

    `Path.is_dir`/`stat` suivis d'un `open` seraient sensibles aux échanges
    de chemin. `O_NOFOLLOW` protège le dernier composant et `dir_fd` ancre
    ensuite toutes les opérations sur le même répertoire vérifié.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ValueError("canonical store directory must not be a symlink") from exc
        raise
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o7077:
            raise ValueError("canonical store directory has unsafe owner or permissions")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_private_file(
    dir_fd: int, *, write: bool, create: bool = True, name: str = _STORE_FILENAME
) -> int:
    """Créer en 0600 même avec umask 022, ou refuser un fichier déjà exposé.

    La validation par fstat précède TOUTE lecture/écriture ; une vieille
    installation en 0644 n'est jamais réparée silencieusement (la divulgation
    éventuelle a déjà eu lieu et exige une décision de l'opérateur).

    `O_NONBLOCK` est indispensable AVANT la validation : `O_NOFOLLOW` n'arrête
    pas un FIFO, et l'ouverture d'un FIFO sans lecteur bloquerait pour
    toujours — y compris en tenant les verrous — au lieu d'échouer fermé. Le
    drapeau est retiré après le contrôle `S_ISREG`, pour ne pas changer la
    sémantique des lectures/écritures sur un fichier régulier.
    """
    flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    flags |= (
        (os.O_RDWR | os.O_APPEND | (os.O_CREAT if create else 0))
        if write else os.O_RDONLY
    )
    try:
        fd = os.open(name, flags, 0o600, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ValueError("canonical store file must not be a symlink") from exc
        if exc.errno == errno.ENXIO:
            # FIFO sans lecteur, ouvert en écriture non bloquante.
            raise ValueError("canonical store file must be a regular file") from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("canonical store file must be a regular file")
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o7077:
            raise ValueError("canonical store file has unsafe owner or permissions")
        current = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, current & ~os.O_NONBLOCK)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _open_tracked_private_file(
    dir_fd: int, *, write: bool, create: bool = True, name: str = _STORE_FILENAME
) -> tuple[int, int]:
    """Open a lease-carrying file and track it against `fork`.

    Returns the descriptor plus a unique token. Both the transaction lock and
    the registry JSONL hold `flock` leases that a child would inherit, so the
    registration must be indivisible with `register_at_fork(before=...)`.
    The token is what identifies this open: after a child closes the inherited
    descriptors, the numeric fd can be reused by a NEW open in that child, and
    unwinding the inherited context must not close that unrelated descriptor.
    """
    with _ACTIVE_TRANSACTION_FDS_LOCK:
        file_fd = _open_private_file(dir_fd, write=write, create=create, name=name)
        global _NEXT_LEASE_TOKEN
        token = _NEXT_LEASE_TOKEN
        _NEXT_LEASE_TOKEN += 1
        _ACTIVE_TRANSACTION_FDS[token] = file_fd
        return file_fd, token


def _close_tracked_private_file(token: int) -> None:
    with _ACTIVE_TRANSACTION_FDS_LOCK:
        file_fd = _ACTIVE_TRANSACTION_FDS.pop(token, None)
        if file_fd is None:
            # Already closed by the at-fork handler in this child process.
            return
        os.close(file_fd)


def _anchor_from_documents(
    documents: Mapping[str, Document], *, records: int, digest: str
) -> dict[str, Any]:
    """Ancre MODERNE : versionnée, et chaque marque porte l'état du document.

    L'état devient un fait de sécurité de première classe de l'ancre, en plus
    du compte de lignes, du digest de préfixe et des versions. Un `inactive`
    ancré ne peut donc pas être « déschuchoté » par un retour en arrière du
    seul JSONL.
    """
    return {
        "schema_version": _ANCHOR_SCHEMA_VERSION,
        "records": records,
        "digest": digest,
        "documents": {
            document_id: {
                "doc_version": document.doc_version,
                "acl_version": document.acl_version,
                "state": document.state,
            }
            for document_id, document in documents.items()
        },
    }


def _validated_anchor(
    payload: Any,
) -> tuple[int, str, dict[str, tuple[int, int, str]], int]:
    """Relire l'ancre aussi strictement que le registre : aucune coercition.

    Deux formats, sans réinterprétation de l'un vers l'autre :

    - LEGACY (ancre d'avant ce lot) : clés exactes ``{records, digest,
      documents}``, chaque marque ``{doc_version, acl_version}``. Normalisée à
      l'état ``active`` (le masquage n'existait pas), mais le drapeau legacy
      remonté interdit à ``_check_against_anchor`` d'attester un historique
      moderne avec elle.
    - MODERNE : clés exactes ``{schema_version, records, digest, documents}``
      avec ``schema_version == 2`` ou ``3`` (int exact, pas ``bool``), chaque marque
      ``{doc_version, acl_version, state}`` avec ``state`` dans le jeu autorisé.

    Un format MIXTE (legacy avec un ``state`` dans une marque, ou moderne sans
    ``state``) est refusé, jamais deviné.

    Retourne ``(records, digest, marks, schema_version)`` (0 pour legacy) où ``marks`` associe
    chaque ``document_id`` à ``(doc_version, acl_version, state)``.
    """
    if type(payload) is not dict:
        raise ValueError("canonical anchor must be a JSON object")
    keys = set(payload)
    if keys == {"records", "digest", "documents"}:
        is_legacy = True
        mark_keys = {"doc_version", "acl_version"}
    elif keys == {"schema_version", "records", "digest", "documents"}:
        is_legacy = False
        mark_keys = {"doc_version", "acl_version", "state"}
        version = payload["schema_version"]
        # `type(x) is int` exclut bool, que isinstance() accepterait.
        if type(version) is not int or version not in (2, _ANCHOR_SCHEMA_VERSION):
            raise ValueError("canonical anchor schema_version is unsupported")
    else:
        raise ValueError(
            "canonical anchor must carry a legacy or versioned key set"
        )
    records = payload["records"]
    if type(records) is not int or records < 0:
        raise ValueError("canonical anchor records must be a non-negative exact int")
    digest = payload["digest"]
    if type(digest) is not str or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("canonical anchor digest must be a lowercase sha256 hex digest")
    entries = payload["documents"]
    if type(entries) is not dict:
        raise ValueError("canonical anchor documents must be a JSON object")
    marks: dict[str, tuple[int, int, str]] = {}
    for document_id, mark in entries.items():
        if type(document_id) is not str or not document_id:
            raise ValueError("canonical anchor document_id must be a non-empty str")
        if type(mark) is not dict or set(mark) != mark_keys:
            raise ValueError("canonical anchor mark must match its schema exactly")
        # `type(x) is int` exclut bool, que isinstance() accepterait.
        if any(
            type(mark[field]) is not int or mark[field] < 0
            for field in ("doc_version", "acl_version")
        ):
            raise ValueError("canonical anchor versions must be non-negative exact ints")
        if is_legacy:
            state = _STATE_ACTIVE
        else:
            state = mark["state"]
            if type(state) is not str or state not in _VALID_STATES:
                raise ValueError("canonical anchor state is unknown")
        marks[document_id] = (mark["doc_version"], mark["acl_version"], state)
    return records, digest, marks, 0 if is_legacy else payload["schema_version"]


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
    # Garde d'état en DÉFENSE EN PROFONDEUR, mutuellement redondante avec celle
    # de `_document_from_record` (chemin de relecture) et avec le refus de
    # `register` (chemin d'import) : retirer l'une SEULE échoue encore fermé via
    # l'autre, donc ce mutant « survit » sans être un trou de confidentialité.
    # Annoté plutôt qu'épinglé par un test vacant.
    if type(document.state) is not str or document.state not in _VALID_STATES:
        raise ValueError("canonical document state must be 'active' or 'inactive'")
    return document


def _record_from_document(document: Document) -> dict[str, Any]:
    # Toute NOUVELLE écriture émet `state`, y compris `active` : une ligne
    # active neuve n'est jamais identique octet-pour-octet à une ligne legacy,
    # et une clé perdue par un bug est détectée (pas relue comme `active`).
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
        "state": document.state,
    }


def _record_is_modern(record: Mapping[str, Any]) -> bool:
    """Vrai si l'enregistrement porte la clé `state` (schéma moderne)."""
    return "state" in record


def _unique_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous JSON objects, including inside nested event payloads."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate canonical JSON key")
        result[key] = value
    return result


def _document_from_record(record: Any) -> Document:
    """Relecture STRICTE : aucune coercition (`int()`/`tuple()`) n'est tolérée.

    `dataset._build_document` coerce (`int(True) == 1`) : acceptable pour un
    corpus de bench, inacceptable pour une autorité de sécurité relue à chaud.

    Deux schémas acceptés sans réinterprétation : LEGACY (11 clés, sans
    `state`) relu comme `active`, ou MODERNE (11 clés + `state`).
    """
    if type(record) is not dict:
        raise ValueError("canonical record must be a JSON object")
    keys = set(record)
    if keys == _RECORD_KEYS:
        state = _STATE_ACTIVE
    elif keys == _MODERN_RECORD_KEYS:
        state = record["state"]
        # Défense en profondeur redondante avec `_validated_document` (appelé
        # juste après) : dominée, donc annotée au lieu d'un test vacant.
        if type(state) is not str or state not in _VALID_STATES:
            raise ValueError("canonical record state must be 'active' or 'inactive'")
    else:
        missing = sorted(_MODERN_RECORD_KEYS - keys)
        extra = sorted(keys - _MODERN_RECORD_KEYS)
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
            state=state,
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
    le démarrage au lieu de servir une politique affaiblie. Les lectures
    rejouent le fichier sous verrou partagé ; les écritures le rejouent sous
    verrou exclusif avant de vérifier les versions et d'ajouter la ligne.
    """

    def __init__(self, store_dir: str | Path) -> None:
        path = Path(store_dir)
        if not path.is_absolute():
            raise ValueError("canonical store directory must be an absolute path")
        if not path.is_dir():
            # Créer le répertoire masquerait une faute de frappe de déploiement :
            # l'opérateur doit l'avoir créé délibérément.
            raise ValueError("canonical store directory must exist and be a directory")
        dir_fd = _open_private_dir(path)
        os.close(dir_fd)
        self._store_dir = path
        self._path = path / _STORE_FILENAME
        self._lock = threading.Lock()
        self._documents: dict[str, Document] = {}
        # Dernier enregistrement ACTIF par document (identique à `_documents`
        # pour un document actif ; l'état d'avant masquage pour un inactif).
        # C'est lui qui a produit les points Qdrant, car `mark_inactive`
        # n'incrémente que `acl_version` sans réécrire le payload indexé.
        self._last_active: dict[str, Document] = {}
        self._records = 0
        self._running = hashlib.sha256()
        self._broken: str | None = None
        self._signature: tuple[int, int, int, int, int] | None = None
        self._anchor_signature: tuple[int, int, int, int, int] | None = None
        self._anchor_path = path / _ANCHOR_FILENAME
        self._authority = _LiveCanonicalAclAuthority(self)
        with _ACTIVE_TRANSACTION_FDS_LOCK:
            # Registered under the fork `before` lock: a child must never see
            # a half-built registry whose mutex it cannot reset.
            _LIVE_REGISTRIES.add(self)
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def anchor_path(self) -> Path:
        return self._anchor_path

    @staticmethod
    def _anchor_identity(dir_fd: int) -> tuple[int, int, int, int, int] | None:
        """Cheap change detection even when the JSONL inode did not change.

        A failed directory fsync after `rename(anchor)` can publish an anchor
        ahead of the unchanged history. Every live registry (not just the
        writer) must then replay or refuse rather than reuse its old ACL cache.
        Open without following symlinks and validate ownership/mode just like
        the full anchor reader before trusting the cached signature.
        """
        try:
            file_fd = _open_private_file(
                dir_fd, write=False, create=False, name=_ANCHOR_FILENAME
            )
        except FileNotFoundError:
            return None
        try:
            return _file_identity(file_fd)
        finally:
            os.close(file_fd)

    def _read_anchor(
        self, dir_fd: int
    ) -> tuple[int, str, dict[str, tuple[int, int, str]], int] | None:
        return self._read_anchor_file(dir_fd)

    @staticmethod
    def _read_anchor_file(
        dir_fd: int
    ) -> tuple[int, str, dict[str, tuple[int, int, str]], int] | None:
        """Lire le repère persisté hors du JSONL, ou `None` s'il n'existe pas.

        Le descripteur de répertoire DÉJÀ validé par l'appelant est réutilisé :
        résoudre le chemin une seconde fois validerait l'ancre à travers une
        autre résolution que le JSONL auquel on la compare.

        Un fichier illisible, exposé, symbolique ou malformé échoue FERMÉ :
        l'absence d'ancre est une installation d'avant ce lot, pas une ancre
        vide (qui, elle, autoriserait la remise à zéro de l'historique).
        """
        try:
            try:
                file_fd = _open_private_file(
                    dir_fd, write=False, name=_ANCHOR_FILENAME
                )
            except FileNotFoundError:
                return None
            try:
                with os.fdopen(file_fd, "rb", closefd=False) as handle:
                    payload = handle.read().decode("utf-8")
            finally:
                os.close(file_fd)
            return _validated_anchor(json.loads(payload, object_pairs_hook=_unique_json_keys))
        except (OSError, ValueError, UnicodeError) as exc:
            raise CanonicalStoreError("canonical anchor is unusable") from exc

    def _write_anchor(self, dir_fd: int, anchor: Mapping[str, Any]) -> None:
        """Publier le repère par remplacement atomique, sous le verrou exclusif.

        Écrit AVANT l'append : l'ancre ne doit jamais être en retard sur le
        fichier, sinon un retour en arrière vers l'état qu'elle décrit
        redeviendrait acceptable. La conséquence assumée est qu'un crash entre
        les deux laisse l'ancre en avance, donc un refus de démarrage qui
        exige une reprise hors ligne.
        """
        _publish_anchor(dir_fd, anchor)

    @property
    def authority(self) -> CanonicalAclAuthority:
        return self._authority

    @contextmanager
    def _transaction_guard(self, *, write: bool):
        """Single-host lease: readers include generation, writers include Qdrant.

        Cooperating processes must share this store directory and lock inode.
        Reentrant calls in the same thread reuse the lease across instances
        sharing the lock inode; a writer cannot upgrade a read lease.
        """
        try:
            dir_fd = _open_private_dir(self._store_dir)
            try:
                file_fd, lease_token = _open_tracked_private_file(
                    dir_fd, write=True, name=_TRANSACTION_LOCK_FILENAME
                )
            finally:
                os.close(dir_fd)
        except (OSError, ValueError):
            raise CanonicalStoreError("canonical transaction lock unavailable") from None
        try:
            lock_stat = os.fstat(file_fd)
            identity = (lock_stat.st_dev, lock_stat.st_ino)
            leases = getattr(_TRANSACTION_LEASES, "held", None)
            if leases is None:
                leases = {}
                _TRANSACTION_LEASES.held = leases
            held = leases.get(identity)
            if held is not None:
                # Defense in depth, expected unreachable: the at-fork handler
                # already clears inherited thread-local lease state, so a
                # child never reads a lease recorded by its parent. Keep the
                # check in case a future path reaches here without that reset;
                # it is not pinned by a test (removing it changes no output).
                if held[1] != os.getpid():
                    raise CanonicalStoreError("canonical lease inherited across fork")
                if write and held[0] != "write":
                    raise CanonicalStoreError("cannot write during a canonical read")
                yield
                return
            try:
                fcntl.flock(file_fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            except OSError:
                raise CanonicalStoreError("canonical transaction lock unavailable") from None
            leases[identity] = ("write" if write else "read", os.getpid())
            try:
                yield
            finally:
                del leases[identity]
        finally:
            _close_tracked_private_file(lease_token)

    def read_guard(self):
        return self._transaction_guard(write=False)

    def write_guard(self):
        return self._transaction_guard(write=True)

    def _load(self) -> None:
        if self._broken is not None:
            # Défense en profondeur (non épinglée par un test) : l'invalidation
            # de la signature force déjà un rejeu, que l'état disque incohérent
            # fait refuser. Ce drapeau rend l'échec immédiat et explicite.
            raise CanonicalStoreError(self._broken)
        try:
            dir_fd = _open_private_dir(self._store_dir)
            try:
                # Deux tentatives : « fichier absent » peut simplement signifier
                # que le tout premier écrivain ne l'a pas encore créé. On ne
                # conclut à une disparition qu'après une seconde observation,
                # l'historique ne pouvant que croître. Prendre un verrou ici
                # serait pire : la lecture tient déjà `self._lock`, alors que
                # l'écriture prend le bail AVANT lui — donc un ABBA.
                for attempt in (0, 1):
                    try:
                        file_fd, lease_token = _open_tracked_private_file(
                            dir_fd, write=False
                        )
                    except FileNotFoundError:
                        if self._documents:
                            raise CanonicalStoreError(
                                "canonical store file disappeared"
                            )
                        self._records = 0
                        self._running = hashlib.sha256()
                        anchor = self._read_anchor(dir_fd)
                        if anchor is None or anchor[0] == 0:
                            return
                        if attempt == 0:
                            continue
                        raise CanonicalStoreError("canonical store lost records")
                    try:
                        fcntl.flock(file_fd, fcntl.LOCK_SH)
                        signature = _file_identity(file_fd)
                        anchor_signature = self._anchor_identity(dir_fd)
                        if self._anchor_signature is not None and anchor_signature is None:
                            raise CanonicalStoreError("canonical anchor disappeared")
                        if (
                            signature != self._signature
                            or anchor_signature != self._anchor_signature
                        ):
                            fresh = self._fresh_verified(file_fd, dir_fd)
                            self._documents = fresh
                            self._signature = signature
                            self._anchor_signature = anchor_signature
                        return
                    finally:
                        _close_tracked_private_file(lease_token)
            finally:
                os.close(dir_fd)
        except (OSError, ValueError, UnicodeError):
            raise CanonicalStoreError("canonical store unavailable") from None

    def _fresh_verified(self, file_fd: int, dir_fd: int) -> dict[str, Document]:
        try:
            anchor = self._read_anchor(dir_fd)
            boundary = 0 if anchor is None else anchor[0]
            fresh, records, prefix_digest, running, history_is_modern, last_active = (
                self._read_documents(file_fd, digest_at=boundary)
            )
            # The file may be truncated or restored from a valid old backup.
            # Replaying it internally is not enough: compare against every
            # revision already observed by THIS running process, including
            # documents removed entirely from the restored history.
            for document_id, previous in self._documents.items():
                current = fresh.get(document_id)
                if current is None:
                    raise CanonicalStoreError("canonical store lost a document")
                self._check_against_previous(current, {document_id: previous})
            self._check_against_anchor(
                anchor, fresh, records, prefix_digest, history_is_modern
            )
            self._records = records
            self._running = running
            self._last_active = last_active
            return fresh
        except (OSError, ValueError, UnicodeError, PermissionError):
            raise CanonicalStoreError("canonical store history is invalid") from None

    @staticmethod
    def _check_against_anchor(
        anchor: tuple[int, str, dict[str, tuple[int, int, str]], int] | None,
        fresh: Mapping[str, Document],
        records: int,
        prefix_digest: str | None,
        history_is_modern: int,
    ) -> None:
        """Repère PERSISTÉ : couvre le redémarrage, que le cache ne voit pas.

        Un processus neuf n'a rien observé ; sans ce contrôle, une sauvegarde
        antérieure (ou un fichier tronqué) lui paraît légitime et réautorise
        un utilisateur révoqué. Le repère vit hors du JSONL, donc une
        restauration du seul JSONL est détectée.

        Quatre liens, du plus fort au plus faible : l'empreinte SHA-256 du
        PRÉFIXE ancré (toute réécriture d'une ligne déjà ancrée est détectée,
        même à compte et versions constants), le nombre de lignes, les versions
        atteintes par document, puis l'ÉTAT (un `inactive` ancré ne peut jamais
        redevenir `active`).
        """
        if anchor is None:
            # Une installation legacy non vide est indiscernable d'un magasin
            # moderne dont l'ancre a été supprimée après une révocation. En
            # acceptant automatiquement le JSONL, un redémarrage réadmettrait
            # son ancienne ACL. Ne bénis PAS les octets présents par une ancre
            # reconstruite à partir du même fichier : une migration hors ligne
            # exige une preuve indépendante de l'état attendu. Un magasin
            # réellement neuf et vide peut toujours faire son premier import.
            if records:
                raise CanonicalStoreError("canonical anchor required for nonempty history")
            return
        anchored_records, anchored_digest, marks, anchor_schema = anchor
        if anchor_schema < history_is_modern:
            # Legacy cannot attest state; v2 cannot attest event lines, even
            # if its digest and count were recomputed to cover those bytes.
            raise CanonicalStoreError(
                "canonical anchor schema cannot attest this history"
            )
        # L'ancre est publiée AVANT l'append, donc le fichier n'est jamais
        # légitimement en avance : l'égalité STRICTE est la bonne borne. Un
        # `>=` permissif laisserait ajouter une révision forgée à version
        # supérieure sans toucher à l'ancre, et une ancre remise à zéro
        # vaudrait « pas d'ancre ».
        if records != anchored_records:
            raise CanonicalStoreError("canonical store record count differs from its anchor")
        if prefix_digest != anchored_digest:
            raise CanonicalStoreError("canonical store prefix does not match its anchor")
        for document_id, (doc_version, acl_version, state) in marks.items():
            current = fresh.get(document_id)
            if current is None:
                raise CanonicalStoreError("canonical store lost an anchored document")
            if current.doc_version < doc_version or current.acl_version < acl_version:
                raise CanonicalStoreError("canonical store regressed below its anchor")
            if state == _STATE_INACTIVE and current.state != _STATE_INACTIVE:
                # Suppression logique ancrée : un retour en arrière du seul JSONL
                # qui la « déschuchoterait » est détecté et refusé fermé.
                # DÉFENSE EN PROFONDEUR ANNOTÉE (survivant de mutation dominé) :
                # le contrôle de digest byte-exact ci-dessus attrape déjà toute
                # réécriture d'une ligne ancrée, donc ce refus d'état n'est pas
                # atteignable isolément par un test — gardé par sûreté, non
                # épinglé par un test vacant.
                raise CanonicalStoreError(
                    "canonical store reactivated a document below its anchor"
                )

    @staticmethod
    def _read_documents(
        file_fd: int, *, digest_at: int = 0
    ) -> tuple[dict[str, Document], int, str | None, Any, int, dict[str, Document]]:
        # Relire depuis le descripteur vérifié, sans publier de demi-rejeu si
        # une ligne est corrompue ou si un invariant de version est violé.
        with os.fdopen(file_fd, "rb", closefd=False) as handle:
            handle.seek(0)
            payload = handle.read().decode("utf-8")
        documents: dict[str, Document] = {}
        last_active: dict[str, Document] = {}
        records = 0
        running = hashlib.sha256()
        prefix_digest: str | None = running.hexdigest() if digest_at == 0 else None
        history_is_modern = 0
        modern_documents: set[str] = set()
        # Intent must immediately follow its ORIGINAL document line. A later
        # identical reimport cannot make an old confirmation contemporary.
        last_document: tuple[str, int, str] | None = None
        document_lines: dict[str, tuple[int, str]] = {}
        intents: dict[int, tuple[int, str, str]] = {}
        confirmed: set[int] = set()
        for number, line in enumerate(payload.splitlines(), 1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line, object_pairs_hook=_unique_json_keys)
                if type(parsed) is dict and "event_version" in parsed:
                    document_id = parsed.get("document_id")
                    if type(document_id) is not str or document_id not in documents:
                        raise ValueError("orphan canonical ingestion event")
                    doc_index, doc_digest = document_lines[document_id]
                    event_kind = validate_event(
                        parsed, document=documents[document_id],
                        document_index=doc_index, document_digest=doc_digest,
                    )
                    if event_kind == "ingestion_intent":
                        if last_document != (document_id, doc_index, doc_digest):
                            raise ValueError("ingestion intent must immediately follow its document")
                        intents[records + 1] = (
                            doc_index, hashlib.sha256((line + "\n").encode("utf-8")).hexdigest(), document_id
                        )
                    else:
                        intent_index = parsed["intent_record_index"]
                        if (intent_index != records or intent_index not in intents
                                or intent_index in confirmed
                                or intents[intent_index] != (
                                    doc_index, parsed["intent_line_sha256"], document_id
                                )):
                            raise ValueError("orphan, duplicate or obsolete ingestion confirmation")
                        confirmed.add(intent_index)
                    last_document = None
                    history_is_modern = 3
                    running.update(line.encode("utf-8") + b"\n")
                    records += 1
                    if records == digest_at:
                        prefix_digest = running.hexdigest()
                    continue
                is_modern = type(parsed) is dict and _record_is_modern(parsed)
                document = _document_from_record(parsed)
                # Monotonie de schéma : une ligne 11-clés (legacy) APRÈS une
                # ligne 12-clés pour le MÊME document est un retour en arrière
                # (clé `state` perdue), refusé — jamais relu comme `active`.
                if document.document_id in modern_documents and not is_modern:
                    raise ValueError(
                        "canonical record schema regressed from modern to legacy"
                    )
                CanonicalDocumentRegistry._check_against_previous(document, documents)
            except (ValueError, PermissionError) as exc:
                # Au démarrage, toute violation d'invariant est un refus de
                # démarrage : on uniformise en ValueError.
                raise ValueError(
                    f"invalid canonical document record at line {number}: {exc}"
                ) from exc
            documents[document.document_id] = document
            document_lines[document.document_id] = (
                records + 1, hashlib.sha256((line + "\n").encode("utf-8")).hexdigest()
            )
            last_document = (document.document_id, *document_lines[document.document_id])
            if document.state == _STATE_ACTIVE:
                last_active[document.document_id] = document
            if is_modern:
                modern_documents.add(document.document_id)
                history_is_modern = max(history_is_modern, 2)
            # Les lignes blanches ne comptent pas et n'entrent pas dans
            # l'empreinte : un bourrage ne doit pas casser la vérification,
            # seule la suite des ENREGISTREMENTS est liée.
            running.update(line.encode("utf-8") + b"\n")
            records += 1
            if records == digest_at:
                prefix_digest = running.hexdigest()
        return documents, records, prefix_digest, running, history_is_modern, last_active

    @staticmethod
    def _check_against_previous(
        document: Document, documents: Mapping[str, Document]
    ) -> None:
        previous = documents.get(document.document_id)
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
        if document.doc_version == previous.doc_version and (
            document.content != previous.content or document.source_uri != previous.source_uri
        ):
            raise ValueError("canonical content or provenance change requires an incremented doc_version")
        if document.acl_version < previous.acl_version:
            raise ValueError("canonical acl_version must not regress")
        if document.acl_version == previous.acl_version and any(
            getattr(document, field) != getattr(previous, field)
            for field in ("visibility", "allowed_groups", "allowed_users", "classification")
        ):
            raise ValueError("canonical ACL change requires an incremented acl_version")
        # Machine à états de la suppression logique réversible (issue #71).
        # Valable aux DEUX usages de cette garde : rejeu de records consécutifs
        # ET comparaison de l'état rejoué à l'état déjà observé. On interdit la
        # seule transition dangereuse (réactivation = recul de révocation) et on
        # exige un bump d'`acl_version` pour masquer. `inactive → inactive`
        # (états égaux) est TOLÉRÉ ici : le document reste caché, c'est sûr ; le
        # refus d'un second masquage est une règle d'API portée par
        # `_mark_inactive_in_transaction`, pas un invariant d'intégrité.
        if previous.state == _STATE_INACTIVE and document.state == _STATE_ACTIVE:
            raise ValueError("cannot reactivate an inactive canonical document")
        if (
            previous.state == _STATE_ACTIVE
            and document.state == _STATE_INACTIVE
            and document.acl_version <= previous.acl_version
        ):
            raise ValueError(
                "masking a canonical document requires an incremented acl_version"
            )

    def source(self, document_id: str) -> Document | None:
        if type(document_id) is not str:
            return None
        with self._lock:
            self._load()
            document = self._documents.get(document_id)
            # Un document `inactive` (suppression logique) est INVISIBLE à toute
            # lecture V1 : `policy_for` (qui délègue ici), la génération et les
            # citations le voient comme inconnu → abstention, jamais son texte.
            if document is None or document.state != _STATE_ACTIVE:
                return None
            return document

    def documents(self) -> Mapping[str, Document]:
        with self._lock:
            self._load()
            return dict(self._documents)

    def last_active_manifest(self) -> tuple[Mapping[str, Document], frozenset[str]]:
        """Manifeste pour l'audit d'index incluant les documents masqués.

        Retourne `(manifest, tombstoned_ids)` :
        - `manifest[document_id]` = dernier enregistrement ACTIF du document.
          Pour un document actif, c'est son état courant ; pour un inactif,
          c'est l'état d'avant masquage, car `mark_inactive` n'incrémente que
          `acl_version` et ne réécrit pas le payload des points Qdrant déjà
          indexés — ce sont donc ces chunks-là qu'il faut régénérer.
        - `tombstoned_ids` = `document_id` actuellement `inactive`.

        Ce n'est pas un instantané Qdrant ni une autorisation de mutation :
        les points réellement présents ne sont pas lus ici.
        """
        with self._lock:
            self._load()
            manifest = dict(self._last_active)
            tombstoned = frozenset(
                document_id
                for document_id, document in self._documents.items()
                if document.state == _STATE_INACTIVE
            )
            return manifest, tombstoned

    def register(self, document: Any) -> Document:
        with self.write_guard():
            validated = _validated_document(document)
            if validated.state != _STATE_ACTIVE:
                # Un import ordinaire ne CRÉE jamais un enregistrement inactif :
                # le masquage ne passe QUE par la transition dédiée
                # `mark_inactive`. Sans ce refus, un importateur authentifié
                # pourrait « empoisonner » durablement un document_id en le
                # rendant non lisible et non réactivable (déni logiciel), et la
                # garantie « seule mark_inactive produit inactive » tomberait.
                raise ValueError(
                    "register cannot create a non-active canonical document; "
                    "use mark_inactive"
                )
            return self._write_in_transaction(
                lambda fresh: validated, create=not bool(self._documents)
            )

    def mark_inactive(self, document_id: str, *, owner_id: str) -> Document:
        """Transition dédiée `active → inactive` (suppression logique, #71).

        Seule voie qui produit un enregistrement `inactive` : un import ordinaire
        ne peut JAMAIS basculer l'état. Append-only, sous le bail exclusif, avec
        `acl_version` strictement incrémenté. AUCUNE mutation Qdrant, AUCUN
        endpoint ici : l'exposition (tranches B/C) reste fermée tant que la
        séquence complète n'est pas démontrée et contre-relue.

        `owner_id` est une ENTRÉE d'autorisation vérifiée contre l'historique
        canonique, PAS une preuve d'identité : l'authentification réelle du
        demandeur est la responsabilité de la couche appelante (tranche C).
        """
        if type(document_id) is not str or type(owner_id) is not str:
            raise ValueError("mark_inactive requires str document_id and owner_id")

        def _build_masked(fresh: Mapping[str, Document]) -> Document:
            current = fresh.get(document_id)
            if current is None:
                raise ValueError("unknown canonical document")
            if current.owner_id != owner_id:
                # PermissionError → 403 côté HTTP, comme le refus de changement
                # de propriétaire ; ce n'est pas une erreur de saisie (400).
                raise PermissionError("canonical owner_id mismatch")
            if current.state != _STATE_ACTIVE:
                # Second masquage refusé explicitement (règle d'API, pas un
                # no-op silencieux) ; l'intégrité tolère deux lignes inactives.
                raise ValueError("canonical document is already inactive")
            return _validated_document(
                replace(
                    current,
                    state=_STATE_INACTIVE,
                    acl_version=current.acl_version + 1,
                )
            )

        with self.write_guard():
            return self._write_in_transaction(_build_masked, create=False)

    def _write_in_transaction(
        self,
        build: "Callable[[Mapping[str, Document]], Document]",
        *,
        create: bool,
    ) -> Document:
        """Append canonique partagé : rejeu vérifié → ancre AVANT append → append.

        Factorise la séquence durcie commune à `register` (le document est fourni)
        et à `mark_inactive` (le document masqué est dérivé de l'état FRAIS sous le
        bail). `build(fresh)` est appelé APRÈS la relecture vérifiée, donc il
        décide sur l'état réel et non sur un cache possiblement périmé.

        Échoue fermé : rien n'est publié en mémoire avant que la ligne ne soit
        écrite, relue à l'identique et `fsync`-ée.
        """
        if self._broken is not None:
            # Écrire par-dessus un magasin déjà constaté incohérent avancerait
            # l'ancre sur un historique faux — et, via l'écriture traversante,
            # pousserait vers Qdrant un document que le registre refuse.
            raise CanonicalStoreError(self._broken)
        with self._lock:
            try:
                dir_fd = _open_private_dir(self._store_dir)
            except (OSError, ValueError):
                raise CanonicalStoreError("canonical store unavailable") from None
            try:
                try:
                    file_fd, lease_token = _open_tracked_private_file(
                        dir_fd, write=True, create=create
                    )
                except (OSError, ValueError):
                    raise CanonicalStoreError("canonical store unavailable") from None
                try:
                    # Le verrou sur l'inode partagé couvre relecture, contrôle
                    # monotone et append, y compris entre processus distincts.
                    fcntl.flock(file_fd, fcntl.LOCK_EX)
                    fresh = self._fresh_verified(file_fd, dir_fd)
                    self._documents = fresh
                    # Décider sur l'état FRAIS : pour un masquage, l'owner et la
                    # version viennent de la relecture vérifiée, pas d'un cache.
                    validated = build(fresh)
                    line = json.dumps(
                        _record_from_document(validated),
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                        ensure_ascii=True,
                    )
                    # Valider la PROJECTION réellement persistée, pas seulement
                    # l'objet : c'est elle que relira le prochain démarrage.
                    if _document_from_record(json.loads(line)) != validated:
                        raise ValueError("canonical record does not round-trip")
                    self._check_against_previous(validated, fresh)
                    published = {**fresh, validated.document_id: validated}
                    # L'ancre est publiée AVANT l'append : elle ne doit jamais
                    # décrire un état plus ancien que le fichier. Son empreinte
                    # couvre le préfixe relu PLUS la ligne qui va être écrite.
                    record_bytes = line.encode("ascii") + b"\n"
                    running = self._running.copy()
                    running.update(record_bytes)
                    # A `rename(anchor)` followed by a failing directory fsync
                    # can change the anchor while leaving the JSONL signature
                    # unchanged. `_load()` compares BOTH file identities, even
                    # in another live registry, before reusing an ACL cache.
                    self._write_anchor(
                        dir_fd,
                        _anchor_from_documents(
                            published,
                            records=self._records + 1,
                            digest=running.hexdigest(),
                        ),
                    )
                    try:
                        with os.fdopen(file_fd, "ab", closefd=False) as handle:
                            handle.write(record_bytes)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.fsync(dir_fd)
                    except OSError as exc:
                        # Deux cas très différents sous le même `OSError` : soit
                        # rien n'a été écrit (l'ancre est en avance, le magasin
                        # est incohérent), soit la ligne EST là et seule la
                        # barrière de durabilité a échoué. Le verrou exclusif
                        # est toujours tenu : on relit pour trancher, au lieu de
                        # condamner un magasin sain. Dans les DEUX cas on LÈVE :
                        # aucun succès (de masquage ou d'import) n'est annoncé,
                        # et la lecture reste refusée fermée.
                        self._signature = None
                        try:
                            fresh = self._fresh_verified(file_fd, dir_fd)
                        except CanonicalStoreError:
                            self._broken = (
                                "canonical store anchor is ahead of its history"
                            )
                            raise CanonicalStoreError(self._broken) from exc
                        self._documents = fresh
                        self._signature = _file_identity(file_fd)
                        self._anchor_signature = self._anchor_identity(dir_fd)
                        raise CanonicalStoreError(
                            "canonical record durability is not confirmed"
                        ) from exc
                    self._documents = published
                    # Maintenir le dernier-actif publié en mémoire, puisque le
                    # cache est réutilisé sans relecture tant que la signature
                    # ne change pas : un append actif devient le dernier-actif
                    # de son document ; un masquage conserve l'actif précédent
                    # (déjà capturé par `_fresh_verified`).
                    if validated.state == _STATE_ACTIVE:
                        self._last_active = {
                            **self._last_active, validated.document_id: validated
                        }
                    self._records += 1
                    self._running = running
                    self._signature = _file_identity(file_fd)
                    self._anchor_signature = self._anchor_identity(dir_fd)
                finally:
                    _close_tracked_private_file(lease_token)
            finally:
                os.close(dir_fd)
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
        with self._registry.write_guard():
            self._registry.register(document)
            return self._repository.replace_document(document, materialized)

    def search(self, query: str, *, context: Any, limit: int = 10) -> Any:
        return self._repository.search(query, context=context, limit=limit)


@contextmanager
def _verified_anchor_snapshot(store_dir: str | Path, candidate: bytes):
    """Snapshot vérifié, sous baux partagés jusqu'à la sortie du contexte.

    Le contenu manquant ne se déduit PAS de l'ancre : l'opérateur doit fournir
    les octets exacts. Ne répare ni le registre, ni la cohérence Qdrant.
    """
    path = Path(store_dir)
    if not path.is_absolute() or type(candidate) is not bytes:
        raise CanonicalStoreError("absolute store path and candidate bytes required")
    if candidate.count(b"\n") != 1 or not candidate.endswith(b"\n"):
        raise CanonicalStoreError("candidate must be exactly one canonical JSONL line")
    try:
        parsed_candidate = json.loads(candidate[:-1].decode("ascii"))
        document = _document_from_record(parsed_candidate)
        candidate_is_modern = (
            type(parsed_candidate) is dict and _record_is_modern(parsed_candidate)
        )
        # Re-sérialiser dans le MÊME schéma que le candidat : un historique
        # legacy (11 clés) doit pouvoir être récupéré avec ses octets exacts
        # d'origine, sans les réécrire au format moderne. La correspondance du
        # digest d'ancre confirmera ensuite que le schéma attendu est le bon.
        expected_record = _record_from_document(document)
        if not candidate_is_modern:
            expected_record = {
                key: value for key, value in expected_record.items() if key != "state"
            }
        expected = (json.dumps(
            expected_record, sort_keys=True, separators=(",", ":"),
            allow_nan=False, ensure_ascii=True,
        ) + "\n").encode("ascii")
        if candidate != expected:
            raise ValueError("candidate is not in the canonical record format")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise CanonicalStoreError("candidate is not a canonical record") from exc

    try:
        dir_fd = _open_private_dir(path)
        try:
            # Baux partagés, sans création implicite : verifier = lecture seule.
            lock_fd, lock_token = _open_tracked_private_file(
                dir_fd, write=True, create=False, name=_TRANSACTION_LOCK_FILENAME
            )
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH)
                file_fd, file_token = _open_tracked_private_file(
                    dir_fd, write=False, create=False
                )
                try:
                    fcntl.flock(file_fd, fcntl.LOCK_SH)
                    # Même descripteur pour la validation ET la copie : un
                    # second open pourrait lire un autre inode après échange
                    # du chemin, même pendant notre bail partagé.
                    anchor_fd = _open_private_file(
                        dir_fd, write=False, create=False, name=_ANCHOR_FILENAME
                    )
                    try:
                        with os.fdopen(anchor_fd, "rb", closefd=False) as handle:
                            anchor_bytes = handle.read()
                    finally:
                        os.close(anchor_fd)
                    anchor = _validated_anchor(json.loads(
                        anchor_bytes.decode("utf-8"), object_pairs_hook=_unique_json_keys
                    ))
                    if anchor[0] == 0:
                        raise CanonicalStoreError("nonempty canonical anchor required")
                    with os.fdopen(file_fd, "rb", closefd=False) as handle:
                        existing = handle.read()
                    if existing and not existing.endswith(b"\n"):
                        raise CanonicalStoreError("canonical history has a partial trailing line")
                    documents, count, _, running, history_schema, _ = CanonicalDocumentRegistry._read_documents(
                        file_fd
                    )
                    if max(history_schema, 2 if candidate_is_modern else 0) > anchor[3]:
                        raise CanonicalStoreError(
                            "recovery anchor schema cannot attest this history"
                        )
                    if count + 1 != anchor[0]:
                        raise CanonicalStoreError("anchor is not exactly one record ahead")
                    CanonicalDocumentRegistry._check_against_previous(document, documents)
                    documents[document.document_id] = document
                    running.update(candidate)
                    marks = {
                        key: (doc.doc_version, doc.acl_version, doc.state)
                        for key, doc in documents.items()
                    }
                    if running.hexdigest() != anchor[1] or marks != anchor[2]:
                        raise CanonicalStoreError("candidate does not match anchored history")
                    source_info = os.fstat(dir_fd)
                    yield existing, anchor_bytes, (source_info.st_dev, source_info.st_ino)
                finally:
                    _close_tracked_private_file(file_token)
            finally:
                _close_tracked_private_file(lock_token)
        finally:
            os.close(dir_fd)
    except (OSError, ValueError, UnicodeError) as exc:
        raise CanonicalStoreError("canonical recovery verification unavailable") from exc


def verify_anchor_recovery_candidate(store_dir: str | Path, candidate: bytes) -> None:
    """Prouver sans écriture qu'une ligne précise comble une ancre en avance."""
    with _verified_anchor_snapshot(store_dir, candidate):
        pass


def _publish_anchor(dir_fd: int, anchor: Mapping[str, Any]) -> None:
    """Publier le repère par remplacement atomique, sous le verrou exclusif.

    Extrait de `_write_anchor` pour que l'écriture traversante ET l'outil de
    migration hors ligne partagent exactement la même publication durable.
    """
    payload = json.dumps(
        anchor, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ensure_ascii=True,
    ).encode("ascii")
    if _validated_anchor(json.loads(payload)) != _validated_anchor(dict(anchor)):
        raise ValueError("canonical anchor does not round-trip")
    temporary = f"{_ANCHOR_FILENAME}.new"
    # O_EXCL sur un temporaire neuf : jamais de réutilisation d'un inode
    # laissé en place, et O_NONBLOCK pour qu'un FIFO échoue au lieu de
    # bloquer en tenant le verrou exclusif. Le descripteur est validé
    # (fichier régulier, propriétaire, droits) avant toute écriture.
    flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    )
    try:
        try:
            os.unlink(temporary, dir_fd=dir_fd)
        except FileNotFoundError:
            pass
        file_fd = os.open(temporary, flags, 0o600, dir_fd=dir_fd)
        try:
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode):
                raise CanonicalStoreError("canonical anchor must be a regular file")
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o7077:
                raise CanonicalStoreError("canonical anchor has unsafe permissions")
            with os.fdopen(file_fd, "wb", closefd=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(file_fd)
        os.rename(temporary, _ANCHOR_FILENAME, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
    except BaseException as exc:
        # Le nettoyage doit couvrir le cas ATTENDU (écriture ou rename en
        # échec) : un `except OSError` suivi d'un `except BaseException`
        # frère ne l'attrape pas, le second ne voyant pas ce que lève le
        # premier. Un seul gestionnaire, puis reclassement.
        with contextlib.suppress(OSError):
            os.unlink(temporary, dir_fd=dir_fd)
        if isinstance(exc, OSError):
            # Sans ancre publiée, l'append ne doit PAS avoir lieu : un
            # fichier en avance sur son repère rouvrirait la fenêtre de recul.
            raise CanonicalStoreError(
                "canonical anchor cannot be published"
            ) from exc
        raise


def _validated_anchor_attestation(
    attestation: object,
) -> tuple[int, dict[str, tuple[int, int, str]], str | None, bool]:
    """Attestation INDÉPENDANTE de l'opérateur : compte + versions par document.

    Même rigueur que l'ancre : jeu de clés exact, aucune coercition,
    `type(x) is int` (donc `bool` refusé), entiers non négatifs. La valeur
    provient d'une source externe à l'hôte ; elle n'est JAMAIS dérivée du
    JSONL présent, sinon la migration bénirait un recul.
    """
    if type(attestation) is not dict or set(attestation) not in (
        {"records", "documents"},
        {"records", "documents", "digest"},
    ):
        raise CanonicalStoreError(
            "anchor attestation must carry records, documents and an optional digest"
        )
    records = attestation["records"]
    if type(records) is not int or records < 1:
        raise CanonicalStoreError(
            "anchor attestation records must be a positive exact int"
        )
    digest: str | None = None
    if "digest" in attestation:
        digest = attestation["digest"]
        if type(digest) is not str or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise CanonicalStoreError(
                "anchor attestation digest must be a lowercase sha256 hex digest"
            )
    entries = attestation["documents"]
    if type(entries) is not dict or not entries:
        raise CanonicalStoreError(
            "anchor attestation documents must be a non-empty object"
        )
    marks: dict[str, tuple[int, int, str]] = {}
    has_state: bool | None = None
    for document_id, mark in entries.items():
        if type(document_id) is not str or not document_id:
            raise CanonicalStoreError(
                "anchor attestation document_id must be a non-empty str"
            )
        if type(mark) is not dict or set(mark) not in (
            {"doc_version", "acl_version"},
            {"doc_version", "acl_version", "state"},
        ):
            raise CanonicalStoreError(
                "anchor attestation mark must carry both versions and an optional state"
            )
        mark_has_state = "state" in mark
        # Schéma d'attestation HOMOGÈNE : toutes les marques avec état, ou
        # toutes sans. Un mélange est refusé, jamais deviné.
        if has_state is None:
            has_state = mark_has_state
        elif has_state != mark_has_state:
            raise CanonicalStoreError(
                "anchor attestation marks must all carry state or none"
            )
        if any(
            type(mark[field]) is not int or mark[field] < 0
            for field in ("doc_version", "acl_version")
        ):
            raise CanonicalStoreError(
                "anchor attestation versions must be non-negative exact ints"
            )
        if mark_has_state:
            state = mark["state"]
            if type(state) is not str or state not in _VALID_STATES:
                raise CanonicalStoreError("anchor attestation state is unknown")
        else:
            state = _STATE_ACTIVE
        marks[document_id] = (mark["doc_version"], mark["acl_version"], state)
    return records, marks, digest, bool(has_state)


def bootstrap_canonical_anchor(store_dir: str | Path, attestation: object) -> None:
    """Recréer HORS LIGNE une ancre manquante, gardée par une attestation.

    Un registre non vide sans ancre échoue fermé (`_check_against_anchor`) :
    une installation historique est indiscernable d'une ancre publiée puis
    supprimée après une révocation. Cet outil laisse l'opérateur republier
    une ancre, mais JAMAIS en bénissant aveuglément le JSONL : il exige une
    attestation indépendante (nombre d'enregistrements ET versions par
    document, depuis une source externe) et n'écrit l'ancre QUE si le fichier
    courant la respecte EXACTEMENT. Un backup restauré à des versions plus
    anciennes diverge donc et est refusé.

    À exécuter service arrêté. Ne réconcilie PAS Qdrant : l'opérateur doit le
    faire séparément avant de remettre le service en route.
    """
    expected_records, expected_marks, expected_digest, attestation_has_state = (
        _validated_anchor_attestation(attestation)
    )
    path = Path(store_dir)
    if not path.is_absolute():
        raise CanonicalStoreError("absolute store path required")
    try:
        dir_fd = _open_private_dir(path)
    except (OSError, ValueError):
        raise CanonicalStoreError("canonical store unavailable") from None
    try:
        # Double contrôle d'ancre existante : (1) rejet rapide avant de prendre
        # le verrou, (2) revérification SOUS le verrou contre un TOCTOU (un
        # service relancé par erreur publierait une ancre entre les deux). Les
        # deux ne sont tués ENSEMBLE que par mutation (M8) ; retirer l'un seul
        # survit en mono-fil car l'autre rattrape — défense en profondeur, pas
        # un trou de couverture. Ne jamais écraser une ancre vivante.
        if CanonicalDocumentRegistry._anchor_identity(dir_fd) is not None:
            raise CanonicalStoreError("canonical anchor already present")
        try:
            file_fd, lease_token = _open_tracked_private_file(
                dir_fd, write=True, create=False
            )
        except FileNotFoundError:
            raise CanonicalStoreError("canonical store history is missing") from None
        except (OSError, ValueError):
            raise CanonicalStoreError("canonical store unavailable") from None
        try:
            fcntl.flock(file_fd, fcntl.LOCK_EX)
            # Revérifier SOUS le verrou : une ancre a pu apparaître entre le
            # premier contrôle et l'acquisition (un service relancé par erreur).
            if CanonicalDocumentRegistry._anchor_identity(dir_fd) is not None:
                raise CanonicalStoreError("canonical anchor already present")
            try:
                documents, records, _, running, history_is_modern, _ = (
                    CanonicalDocumentRegistry._read_documents(file_fd)
                )
            except (OSError, ValueError, UnicodeError) as exc:
                raise CanonicalStoreError("canonical store history is invalid") from exc
            if records == 0:
                raise CanonicalStoreError(
                    "empty canonical store needs no anchor migration"
                )
            if history_is_modern == 3:
                # The old operator attestation describes only document marks.
                # It has no independently attested ingestion-event history.
                raise CanonicalStoreError(
                    "legacy anchor bootstrap cannot attest ingestion events"
                )
            # Historique MODERNE (au moins un état documentaire) : l'attestation
            # doit attester l'ÉTAT de chaque document ET un digest liant les
            # octets. Sans cela, la migration bénirait l'état porté par un JSONL
            # possiblement altéré (le seul rempart de bootstrap étant la preuve
            # externe). Un historique legacy (tout actif) reste migrable avec
            # l'attestation versions-seules et produit une ancre moderne active.
            if history_is_modern:
                if not attestation_has_state:
                    raise CanonicalStoreError(
                        "modern canonical history requires document state in the attestation"
                    )
                if expected_digest is None:
                    raise CanonicalStoreError(
                        "modern canonical history requires an attested digest"
                    )
            actual_marks = {
                document_id: (document.doc_version, document.acl_version, document.state)
                for document_id, document in documents.items()
            }
            if records != expected_records or actual_marks != expected_marks:
                # Divergence = backup restauré, troncature ou attestation
                # erronée : refuser plutôt que bénir un état non attesté.
                raise CanonicalStoreError(
                    "canonical history does not match the operator attestation"
                )
            if expected_digest is not None and running.hexdigest() != expected_digest:
                # Le digest attesté lie les OCTETS exacts : une réécriture en
                # place à compte et marques constants est ainsi refusée.
                raise CanonicalStoreError(
                    "canonical history digest does not match the attestation"
                )
            _publish_anchor(
                dir_fd,
                _anchor_from_documents(
                    documents, records=records, digest=running.hexdigest()
                ),
            )
        finally:
            _close_tracked_private_file(lease_token)
    finally:
        os.close(dir_fd)


def _write_recovery_file(dir_fd: int, name: str, payload: bytes) -> None:
    """Créer un fichier privé neuf et durable dans le répertoire de staging."""
    fd = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
        dir_fd=dir_fd,
    )
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or (
            stat.S_IMODE(info.st_mode) & 0o7077
        ):
            raise CanonicalStoreError("recovery output is not a private regular file")
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def _read_recovery_file(dir_fd: int, name: str) -> bytes:
    fd = _open_private_file(dir_fd, write=False, create=False, name=name)
    try:
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(fd)


def _rename_recovery_noreplace(parent_fd: int, source: str, target: str) -> None:
    """Publication atomique sans remplacer un répertoire concurrent (Linux)."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise CanonicalStoreError("atomic no-replace rename is unavailable")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                          ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(parent_fd, os.fsencode(source), parent_fd,
                 os.fsencode(target), 1) != 0:  # RENAME_NOREPLACE
        raise OSError(ctypes.get_errno(), "recovery target cannot be published")


def _directory_descends_from(fd: int, ancestor: tuple[int, int]) -> bool:
    """Tester l'ascendance des INODES ouverts, pas des noms pré-résolus."""
    current = os.dup(fd)  # Descripteur de répertoire, jamais un bail flock.
    try:
        for _ in range(256):
            info = os.fstat(current)
            identity = (info.st_dev, info.st_ino)
            if identity == ancestor:
                return True
            above = os.open(
                "..", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=current,
            )
            try:
                parent_info = os.fstat(above)
            except BaseException:
                os.close(above)
                raise
            if (parent_info.st_dev, parent_info.st_ino) == identity:
                os.close(above)  # Racine atteinte.
                return False
            os.close(current)
            current = above
        raise CanonicalStoreError("recovery output ancestry is too deep")
    finally:
        os.close(current)


def prepare_anchor_recovery_copy(
    store_dir: str | Path, candidate: bytes, output_dir: str | Path
) -> None:
    """Créer une COPIE réparée, jamais modifier le magasin source.

    La copie ne doit pas être mise en service sans réconciliation Qdrant et
    décision explicite de l'opérateur. Le succès seul ne prouve rien sur l'index.
    """
    source = Path(store_dir)
    target = Path(output_dir)
    if not source.is_absolute() or not target.is_absolute():
        raise CanonicalStoreError("absolute source and output paths required")
    # Un répertoire de sortie imbriqué dans la source modifierait celle-ci.
    source_real = source.resolve(strict=True)
    parent_real = target.parent.resolve(strict=True)
    if source_real == parent_real or source_real in parent_real.parents:
        raise CanonicalStoreError("recovery copy cannot be created inside the source")
    with _verified_anchor_snapshot(source, candidate) as (history, anchor, source_inode):
        try:
            parent_fd = _open_private_dir(target.parent)
        except (OSError, ValueError) as exc:
            raise CanonicalStoreError("recovery output parent is not private") from exc
        try:
            if _directory_descends_from(parent_fd, source_inode):
                raise CanonicalStoreError("recovery output is inside the opened source")
            # Réobserver la relation après l'ouverture : le chemin du parent
            # pouvait avoir été remplacé entre le premier prévol et l'open.
            current_parent = target.parent.resolve(strict=True)
            if source_real == current_parent or source_real in current_parent.parents:
                raise CanonicalStoreError("recovery output moved inside the source")
            stage = f".{target.name}.recovery-{os.urandom(12).hex()}"
            os.mkdir(stage, 0o700, dir_fd=parent_fd)
            try:
                stage_fd = os.open(
                    stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except BaseException:
                # Le staging vient d'être créé ; si son ouverture échoue,
                # l'ancien `finally` (qui supposait stage_fd) ne le nettoyait pas.
                with contextlib.suppress(OSError):
                    os.rmdir(stage, dir_fd=parent_fd)
                raise
            published = False
            try:
                _write_recovery_file(stage_fd, _STORE_FILENAME, history + candidate)
                _write_recovery_file(stage_fd, _ANCHOR_FILENAME, anchor)
                _write_recovery_file(stage_fd, _TRANSACTION_LOCK_FILENAME, b"")
                os.fsync(stage_fd)
                # Ne JAMAIS rouvrir le staging par `target.parent / stage` :
                # le chemin parent peut avoir été échangé depuis l'ouverture
                # du descripteur. Valider les mêmes inodes sous `stage_fd`.
                if _read_recovery_file(stage_fd, _STORE_FILENAME) != history + candidate:
                    raise CanonicalStoreError("recovery copy differs from verified history")
                if _read_recovery_file(stage_fd, _ANCHOR_FILENAME) != anchor:
                    raise CanonicalStoreError("recovery anchor differs from source")
                if _read_recovery_file(stage_fd, _TRANSACTION_LOCK_FILENAME):
                    raise CanonicalStoreError("recovery lock file is not empty")
                anchor_view = CanonicalDocumentRegistry._read_anchor_file(stage_fd)
                if anchor_view is None:
                    raise CanonicalStoreError("recovery copy has no anchor")
                copy_fd = _open_private_file(stage_fd, write=False, create=False)
                try:
                    docs, count, prefix, _, staged_modern, _ = (
                        CanonicalDocumentRegistry._read_documents(
                            copy_fd, digest_at=anchor_view[0]
                        )
                    )
                finally:
                    os.close(copy_fd)
                CanonicalDocumentRegistry._check_against_anchor(
                    anchor_view, docs, count, prefix, staged_modern
                )
                expected = _document_from_record(json.loads(candidate[:-1]))
                if docs.get(expected.document_id) != expected:
                    raise CanonicalStoreError("recovery copy failed its restart check")
                parent_stat = os.stat(target.parent, follow_symlinks=False)
                opened_stat = os.fstat(parent_fd)
                if (parent_stat.st_dev, parent_stat.st_ino) != (
                    opened_stat.st_dev, opened_stat.st_ino
                ):
                    raise CanonicalStoreError("recovery output parent path changed")
                if _directory_descends_from(parent_fd, source_inode):
                    raise CanonicalStoreError("recovery output moved inside the source")
                _rename_recovery_noreplace(parent_fd, stage, target.name)
                published = True
                os.fsync(parent_fd)
                published_stat = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
                visible_stat = os.stat(target, follow_symlinks=False)
                if (published_stat.st_dev, published_stat.st_ino) != (
                    visible_stat.st_dev, visible_stat.st_ino
                ):
                    raise CanonicalStoreError("recovery output path changed after publication")
            finally:
                try:
                    if not published:
                        # Même un échec du nettoyage ne doit pas garder le FD
                        # ouvert. Le résidu éventuel reste privé (0700) et le
                        # chemin final n'est jamais publié.
                        for name in (_STORE_FILENAME, _ANCHOR_FILENAME, _TRANSACTION_LOCK_FILENAME):
                            with contextlib.suppress(OSError):
                                os.unlink(name, dir_fd=stage_fd)
                finally:
                    os.close(stage_fd)
                if not published:
                    with contextlib.suppress(OSError):
                        os.rmdir(stage, dir_fd=parent_fd)
        except (OSError, ValueError) as exc:
            raise CanonicalStoreError("recovery copy could not be published") from exc
        finally:
            os.close(parent_fd)


def wrap_repository_with_canonical_barrier(
    repository: Any,
    registry: CanonicalDocumentRegistry,
    *,
    minimum_score: float,
    chunker: Callable[[Document], list[Chunk]] | None = None,
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
        chunker=chunker,
        read_guard=registry.read_guard,
    )
