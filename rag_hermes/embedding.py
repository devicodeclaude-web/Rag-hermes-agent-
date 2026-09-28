from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

ModelLoader = Callable[..., Any]


def _default_model_loader(*, repo_id: str, revision: str, use_fp16: bool) -> Any:
    """Load the pinned BGE-M3 model via FlagEmbedding.

    Imported lazily so this module stays importable (and unit-testable) on hosts
    without FlagEmbedding, torch, or a GPU. The checkpoint is pinned by revision.
    """
    from FlagEmbedding import BGEM3FlagModel  # type: ignore

    return BGEM3FlagModel(repo_id, revision=revision, use_fp16=use_fp16)


class LockedBgeM3Embedder:
    """Dense embedder pinned to the audited BAAI/bge-m3 checkpoint.

    The model is loaded lazily on first ``embed`` call. The produced vector is
    validated against the declared dense dimension; a mismatch fails closed
    instead of silently persisting a wrong-shaped vector.
    """

    def __init__(
        self,
        *,
        lock_path: str | Path,
        dense_dimension: int | None = None,
        use_fp16: bool = True,
        model_loader: ModelLoader = _default_model_loader,
    ) -> None:
        lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
        repo_id = str(lock.get("repo_id", "")).strip()
        revision = str(lock.get("revision", "")).strip()
        if not repo_id or not revision:
            raise ValueError("lock must pin repo_id and revision")
        # Prefer an explicit argument, then an optional lock field, then the
        # known bge-m3 dense size. Pinning from the lock keeps the dimension and
        # the checkpoint revision from drifting apart.
        resolved_dimension = (
            dense_dimension
            if dense_dimension is not None
            else int(lock.get("dense_dimension", 1024))
        )
        if resolved_dimension < 1:
            raise ValueError("dense_dimension must be positive")
        self._repo_id = repo_id
        self._revision = revision
        self._dense_dimension = resolved_dimension
        self._use_fp16 = use_fp16
        self._model_loader = model_loader
        self._model: Any | None = None

    @property
    def repo_id(self) -> str:
        return self._repo_id

    @property
    def revision(self) -> str:
        return self._revision

    @property
    def dense_dimension(self) -> int:
        return self._dense_dimension

    def _ensure_model(self) -> Any:
        if self._model is None:
            self._model = self._model_loader(
                repo_id=self._repo_id,
                revision=self._revision,
                use_fp16=self._use_fp16,
            )
        return self._model

    def embed(self, text: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        model = self._ensure_model()
        encoded = model.encode([text], return_dense=True, return_sparse=False)
        if not isinstance(encoded, dict) or "dense_vecs" not in encoded:
            raise ValueError("embedding model did not return a 'dense_vecs' field")
        dense = encoded["dense_vecs"]
        if not dense:
            raise ValueError("embedding model returned no dense vector")
        vector = [float(value) for value in dense[0]]
        if len(vector) != self._dense_dimension:
            raise ValueError(
                f"embedding dimension {len(vector)} does not match declared "
                f"{self._dense_dimension}"
            )
        return vector

    def __call__(self, text: str) -> list[float]:
        return self.embed(text)
