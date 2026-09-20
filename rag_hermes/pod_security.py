from __future__ import annotations

import re
import shlex

_USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")


def _validate_user(username: str) -> None:
    if username == "root":
        raise ValueError("root is forbidden as the workload user")
    if not _USERNAME.fullmatch(username):
        raise ValueError("invalid workload username")


def build_non_root_bootstrap(username: str, workspace: str) -> str:
    _validate_user(username)
    if not workspace.startswith("/"):
        raise ValueError("workspace must be an absolute path")
    user = shlex.quote(username)
    target = shlex.quote(workspace)
    return (
        "set -euo pipefail; "
        f"id -u {user} >/dev/null 2>&1 || useradd --create-home --shell /bin/bash {user}; "
        f"install -d -m 0750 -o {user} -g {user} {target}; "
        f"chown -R {user}:{user} {target}"
    )


def run_as_user_command(username: str, command: str) -> str:
    _validate_user(username)
    if not command.strip():
        raise ValueError("workload command is required")
    return f"runuser -u {shlex.quote(username)} -- bash -lc {shlex.quote(command)}"
