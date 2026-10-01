#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_hermes.app_factory import build_service
from rag_hermes.http_api import make_app


def validate_bind_host(value: str) -> str:
    host = value.strip().lower()
    if host not in {"127.0.0.1", "localhost"}:
        raise argparse.ArgumentTypeError("--host must be a loopback address")
    return host


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Démarre la V1 locale du RAG Hermes en mémoire.",
    )
    parser.add_argument(
        "--host",
        type=validate_bind_host,
        default="127.0.0.1",
        help="adresse d'écoute locale (défaut : 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="port HTTP (défaut : 8080 ; 0 = port libre automatique)",
    )
    return parser.parse_args()


def _stop_on_signal(_signum, _frame) -> None:
    """Leave serve_forever cleanly when the process receives SIGTERM."""
    raise KeyboardInterrupt


def main() -> int:
    args = parse_args()
    if not 0 <= args.port <= 65535:
        raise SystemExit("--port doit être compris entre 0 et 65535")
    app = make_app(build_service(env=os.environ))
    with make_server(args.host, args.port, app) as server:
        backend = "Qdrant" if os.environ.get("RAG_QDRANT_URL", "").strip() else "mémoire"
        print(
            f"RAG Hermes V1 ({backend}) : http://{args.host}:{server.server_port}",
            flush=True,
        )
        previous_sigterm = signal.signal(signal.SIGTERM, _stop_on_signal)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nArrêt du serveur.", flush=True)
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
