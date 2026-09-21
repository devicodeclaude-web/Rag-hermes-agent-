"""Durcissement local : executer le workload RAG sous un utilisateur non-root.

Hermes tourne en root a l'interieur du PRoot Termux. Tout process compromis a
donc acces a /root (cles, cache de delegation, logs). Ce module fournit de quoi
creer un utilisateur local non privilegie et executer le harnais sous cet
utilisateur, pour que le workload ne s'execute jamais en root.

Reutilise la logique validee de pod_security (meme politique anti-root).
"""
from __future__ import annotations

from .pod_security import build_non_root_bootstrap, run_as_user_command


def build_local_user_bootstrap(username: str, workspace: str) -> str:
    """Cree l'utilisateur local non-root et un workspace lui appartenant."""
    return build_non_root_bootstrap(username, workspace)


def build_local_workload_command(username: str, command: str) -> str:
    """Enveloppe une commande pour qu'elle s'execute sous l'utilisateur non-root."""
    return run_as_user_command(username, command)
