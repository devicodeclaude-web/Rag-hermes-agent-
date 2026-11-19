from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import re
from pathlib import Path
from typing import Any

from .acl import Chunk
from .ingestion import Document, chunk_document_tokens

# Approved by the versioned reranker lock + GPU campaign manifest. A writable
# operator-supplied lock alone cannot assert a different checkpoint identity.
_APPROVED_REPO = "BAAI/bge-reranker-v2-m3"
_APPROVED_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
_APPROVED_TOKENIZER_SHA256 = "69564b696052886ed0ac63fa393e928384e0f8caada38c1f4864a9bfbf379c15"


class _TokenizerAdapter:
    """Adapt Hugging Face's fast tokenizer core to the chunker interface."""

    def __init__(self, core: Any) -> None:
        self._core = core

    def __call__(self, text: str, **_kwargs: Any) -> dict[str, Any]:
        encoded = self._core.encode(text, add_special_tokens=False)
        return {"input_ids": encoded.ids, "offset_mapping": encoded.offsets}


class LockedTokenChunker:
    """Token chunks from a locally verified tokenizer.json and pinned revision.

    The optional tokenizer argument is for controlled CPU/system tests only; an
    injected object cannot be attested by the file digest. Production uses the
    tokenizer parsed from the verified bytes themselves.
    """

    def __init__(
        self,
        *,
        lock_path: str | Path,
        tokenizer_path: str | Path,
        tokenizer: Any = None,
        max_passage_tokens: int = 384,
        overlap_tokens: int = 64,
    ) -> None:
        lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
        name, revision = lock.get("repo_id"), lock.get("revision")
        if type(name) is not str or not name or type(revision) is not str or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("tokenizer lock must pin a repo_id and 40-hex revision")
        files = lock.get("files")
        if type(files) is not list:
            raise ValueError("tokenizer lock must list files")
        pins = [entry.get("sha256") for entry in files
                if type(entry) is dict and entry.get("path") == "tokenizer.json"]
        if len(pins) != 1 or type(pins[0]) is not str or not re.fullmatch(r"[0-9a-f]{64}", pins[0]):
            raise ValueError("tokenizer.json requires exactly one sha256 pin")
        if tokenizer is None and (
            name != _APPROVED_REPO or revision != _APPROVED_REVISION
            or pins[0] != _APPROVED_TOKENIZER_SHA256
        ):
            raise ValueError("tokenizer lock does not match the approved BGE checkpoint")
        path = Path(tokenizer_path)
        if path.name != "tokenizer.json":
            raise ValueError("tokenizer path must name tokenizer.json")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pins[0]:
            raise ValueError("tokenizer.json sha256 mismatch")
        if max_passage_tokens < 1 or not 0 <= overlap_tokens < max_passage_tokens:
            raise ValueError("invalid token chunking budget")
        if tokenizer is None:
            # No remote fetch: the pinned bytes are parsed from memory, after
            # digest verification, avoiding a path swap between check and use.
            # The GPU evaluation used tokenizers 0.22.2. Pin the version of
            # the actual verified runtime; other wrappers can change offsets.
            try:
                runtime_version = metadata.version("tokenizers")
            except metadata.PackageNotFoundError as exc:
                raise ValueError("tokenizers 0.22.2 is required") from exc
            if runtime_version != "0.22.2":
                raise ValueError("tokenizers 0.22.2 is required for this profile")
            from tokenizers import Tokenizer

            tokenizer = _TokenizerAdapter(Tokenizer.from_str(raw.decode("utf-8")))
        if not callable(tokenizer):
            raise ValueError("tokenizer must be callable")
        self._tokenizer = tokenizer
        self.name = name
        self.revision = revision
        self.max_passage_tokens = max_passage_tokens
        self.overlap_tokens = overlap_tokens

    def __call__(self, document: Document) -> list[Chunk]:
        return chunk_document_tokens(
            document, self._tokenizer,
            max_passage_tokens=self.max_passage_tokens,
            overlap_tokens=self.overlap_tokens,
            tokenizer_name=self.name, tokenizer_revision=self.revision,
        )
