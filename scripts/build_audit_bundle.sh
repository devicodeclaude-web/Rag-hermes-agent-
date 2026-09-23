#!/bin/sh
set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT" || exit 1
STAGING="$ROOT/AUDIT/.staging"
PROOFS="$ROOT/AUDIT/preuves"
HISTORY="$ROOT/AUDIT/historique"
AUDIT_PYTHON=${AUDIT_PYTHON:-python}
rm -rf "$STAGING"
mkdir -p "$STAGING" "$HISTORY"

run_capture() {
  output=$1
  shift
  python scripts/capture_evidence.py --output "$STAGING/$output" -- "$@"
  return $?
}

failed=0
run_capture tests-ci-strict.txt "$AUDIT_PYTHON" scripts/run_ci_strict.py || failed=1
run_capture lock-install.txt python scripts/verify_lock_install.py || failed=1
run_capture runtime-identity.txt sh -c 'id; ps -ef | grep -E "[h]ermes|[r]un_agent"' || failed=1
run_capture git-status.txt git status --short --branch || failed=1
run_capture git-log.txt git log -9 --oneline || failed=1
AUDIT_RANDOM_SEED=20260923 python scripts/capture_evidence.py --output "$STAGING/dataset-v1-validation.txt" -- python scripts/validate_dataset_v1.py || failed=1
AUDIT_RANDOM_SEED=20260923 python scripts/capture_evidence.py --output "$STAGING/acl-matrix-qdrant.txt" -- python scripts/run_acl_matrix.py || failed=1

printf '%s\n' "$(git rev-parse HEAD)" > "$STAGING/audited_commit"
for source in \
  data/results/bge_m3_gpu_smoke_report.json \
  data/results/chunking_ablation_cpu.json \
  data/results/acl_matrix_qdrant.json; do
  [ -f "$source" ] && cp "$source" "$STAGING/$(basename "$source")"
done

# Structural validation checks evidence existence and headers, not success.
# Non-zero command results remain valid evidence and are reflected in status.
python - "$STAGING" <<'PY' || exit 2
from pathlib import Path
import re, sys
root = Path(sys.argv[1])
required = [
    "tests-ci-strict.txt",
    "lock-install.txt",
    "runtime-identity.txt",
    "dataset-v1-validation.txt",
    "acl-matrix-qdrant.txt",
]
fields = (
    "audited_commit", "date_utc", "command", "exit_code", "python_version",
    "qdrant_version", "qdrant_revision", "embedding_model",
    "reranker_model", "random_seed",
)
for name in required:
    path = root / name
    if not path.is_file():
        raise SystemExit(f"missing evidence file: {name}")
    text = path.read_text(encoding="utf-8")
    for field in fields:
        if not re.search(rf"^{field}: .+", text, re.MULTILINE):
            raise SystemExit(f"missing {field} in {name}")
PY

python scripts/render_audit_status.py \
  "$STAGING" "$HISTORY" "$STAGING/LOT-STATUS.json" || exit 2

python - "$STAGING" "$HISTORY" <<'PY' || exit 2
from pathlib import Path
import hashlib
import sys
staging, history = map(Path, sys.argv[1:])
lines = []
for root, prefix in ((staging, "AUDIT/preuves"), (history, "AUDIT/historique")):
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "SHA256SUMS"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {prefix}/{path.relative_to(root).as_posix()}")
(staging / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

python scripts/atomic_replace_dir.py "$STAGING" "$PROOFS" || exit 2
printf '%s\n' "Bundle régénéré avec résultats réussis et échoués : $PROOFS"
if [ "$failed" -ne 0 ]; then
  printf '%s\n' "BLOQUÉ: au moins une preuve a un code de sortie non nul; voir LOT-STATUS.json." >&2
  exit 1
fi
exit 0
