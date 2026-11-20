#!/usr/bin/env python3
"""Mint the two collection-scoped Qdrant JWTs the V1 service requires.

The signing secret is the operator's `service.api_key`. It must stay with the
operator: the service only ever receives the two tokens printed here.

    QDRANT_ADMIN_API_KEY=... python scripts/mint_qdrant_jwt.py \
        --collection hermes_chunks_v1 --ttl-days 30

Prints shell assignments for RAG_QDRANT_QUERY_API_KEY (read-only) and
RAG_QDRANT_WRITE_API_KEY (points read/write). Redirect to a file your secret
manager reads; never commit the output, and never pass the admin key to the
service itself.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_hermes.qdrant_identity import (  # noqa: E402
    QUERY_ACCESS,
    WRITE_ACCESS,
    mint_collection_token,
)

SECRET_ENV = "QDRANT_ADMIN_API_KEY"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default="hermes_chunks_v1")
    parser.add_argument("--ttl-days", type=int, default=30)
    parser.add_argument(
        "--only", choices=(QUERY_ACCESS, WRITE_ACCESS),
        help="mint a single token (default: both)",
    )
    arguments = parser.parse_args(argv)

    secret = os.environ.get(SECRET_ENV, "").strip()
    if not secret:
        sys.stderr.write(
            f"{SECRET_ENV} is required: it is the Qdrant service.api_key that "
            "signs the tokens, and it is never written to stdout.\n"
        )
        return 2
    if arguments.ttl_days < 1:
        sys.stderr.write("--ttl-days must be a positive integer\n")
        return 2

    ttl_seconds = arguments.ttl_days * 86400
    wanted = (
        [(arguments.only, _variable(arguments.only))]
        if arguments.only
        else [
            (QUERY_ACCESS, "RAG_QDRANT_QUERY_API_KEY"),
            (WRITE_ACCESS, "RAG_QDRANT_WRITE_API_KEY"),
        ]
    )
    for access, variable in wanted:
        token = mint_collection_token(
            secret, collection=arguments.collection, access=access,
            ttl_seconds=ttl_seconds,
        )
        print(f"{variable}={token}")
    sys.stderr.write(
        f"Minted for collection {arguments.collection!r}, valid "
        f"{arguments.ttl_days} day(s). Qdrant needs service.jwt_rbac: true.\n"
    )
    return 0


def _variable(access: str) -> str:
    return (
        "RAG_QDRANT_QUERY_API_KEY" if access == QUERY_ACCESS
        else "RAG_QDRANT_WRITE_API_KEY"
    )


if __name__ == "__main__":
    raise SystemExit(main())
