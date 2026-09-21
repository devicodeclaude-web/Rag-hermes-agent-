"""Scanner de secrets local, sans dependance externe (remplace gitleaks).

Detecte : cles privees, secrets assignes a une chaine litterale suffisamment
longue. Ignore explicitement les references d'environnement (os.environ[...],
$VAR) et les valeurs courtes/placeholders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PRIVATE_KEY = re.compile(r"BEGIN (?:OPENSSH|RSA|EC|DSA|PGP) PRIVATE KEY")
_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[=:]\s*"
    r"['\"]([^'\"]{12,})['\"]"
)
_ENV_REFERENCE = re.compile(r"os\.environ|getenv|\$\{?[A-Z_]+\}?")
_PLACEHOLDER = re.compile(
    r"(?i)(your[_-]?key|xxx+|placeholder|example|changeme|<[^>]+>)"
)


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    rule: str
    preview: str


def scan_text(path: str, text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if _PRIVATE_KEY.search(line):
            findings.append(
                SecretFinding(path, line_number, "private_key", line[:40])
            )
            continue
        match = _ASSIGNED_SECRET.search(line)
        if match:
            value = match.group(2)
            if _ENV_REFERENCE.search(line) or _PLACEHOLDER.search(value):
                continue
            findings.append(
                SecretFinding(path, line_number, "assigned_secret", value[:8] + "...")
            )
    return findings
