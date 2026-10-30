#!/usr/bin/env bash
# Campagne BGE-M3 reelle sur les 154 cas humains — a lancer sur un pod RunPod GPU.
#
# Donne le PREMIER chiffre de retrieval reel du projet (recall@10 / MRR avant et
# apres reranking, 0 fuite inter-tenant), sur le vrai corpus et les 154 questions
# humaines. Ne lance PAS de generation LLM (etape suivante).
#
# Prerequis : etre dans un clone git PROPRE du depot, au commit a mesurer.
#   git clone https://<TON_TOKEN>@github.com/devicodeclaude-web/Rag-hermes-agent-.git
#   cd Rag-hermes-agent-
#   bash scripts/runpod_human154.sh
#
# Le runner epingle les revisions de modeles ET le commit du code ; il refuse de
# tourner si l'arbre git est modifie. Le resultat est un recu autonome et verifie.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
REV="$(git rev-parse HEAD)"
echo ">> depot : $(pwd)"
echo ">> commit mesure : $REV"

if [ -n "$(git status --porcelain=v1 --untracked-files=all)" ]; then
  echo "!! ARBRE GIT MODIFIE — le runner refusera. Ne modifie rien dans le clone." >&2
  git status --porcelain=v1 --untracked-files=all >&2
  exit 1
fi

# Les wheels du lock sont construits pour Python 3.12 (comme la CI). Un autre
# Python fera echouer l'installation hash-verifiee.
PY="$(command -v python3.12 || command -v python3)"
echo ">> interpreteur : $PY ($("$PY" -V 2>&1))"
case "$("$PY" -V 2>&1)" in
  *" 3.12."*) : ;;
  *) echo "!! ATTENTION : Python != 3.12. Si l'install echoue, choisis un pod/template Python 3.12 (ou installe python3.12) puis relance." >&2 ;;
esac

echo ">> creation du venv + installation des dependances GPU (hash-verifiees)…"
"$PY" -m venv .venv-gpu
# shellcheck disable=SC1091
. .venv-gpu/bin/activate
python -m pip install --upgrade pip wheel >/dev/null
pip install --require-hashes -r requirements-gpu.lock.txt

echo ">> lancement de la campagne (telechargement des modeles epingles au 1er appel)…"
PYTHONPATH=. python scripts/run_bge_gpu_campaign.py \
  --manifest manifests/gpu/bge-m3-human-154.json \
  --code-revision "$REV"

echo
echo "================ RESULTATS (resume) ================"
PYTHONPATH=. python - <<'PY'
import json
from pathlib import Path
from rag_hermes.execution_receipt import load_consumable_receipt_v2

receipt = load_consumable_receipt_v2(
    Path("data/results/bge_m3_human_154_execution_receipt.json")
)
report = receipt["report"]
for key in ("job_id", "status", "quality_gate_passed"):
    print(f"{key} = {report.get(key)}")
for block in ("metrics_hybrid_pre_rerank", "metrics_after_rerank", "acl_evidence"):
    print(f"--- {block}")
    print(json.dumps(report.get(block), indent=2, ensure_ascii=False))
PY
echo "===================================================="
echo ">> Recu complet (a me renvoyer) :"
echo "   data/results/bge_m3_human_154_execution_receipt.json"
echo ">> SUPPRIME le pod dans la console RunPod des que tu as le recu (sinon il continue a facturer)."
