#!/usr/bin/env bash
# Baseline G0 closed-book (modele SEUL, sans retrieval) sur les 154 cas humains.
# A lancer sur un pod GPU x86_64 (A40 recommande), template PyTorch Python 3.12.
#
# Ce que ca fait :
#   1. verifie que le clone git est PROPRE au commit a mesurer ;
#   2. installe vLLM dans un venv .venv-vllm (gitignore) ;
#   3. sert Qwen2.5-7B-Instruct a la revision EPINGLEE via l'API OpenAI de vLLM ;
#   4. lance la campagne G0 (axe abstention) qui ecrit un recu autonome verifie ;
#   5. affiche le resume et rappelle d'eteindre le pod.
#
# G0 ne mesure QUE l'abstention honnete (modele seul, aucune source). La justesse
# des reponses concretes n'est PAS scoree hors-ligne : elle attend la revue
# humaine aveugle >=20%. Run classe 'infrastructure_smoke_only' (protocole v2 =
# BROUILLON), PAS un resultat de qualite pre-inscrit.
#
# Prerequis (clone propre) :
#   git clone https://***@github.com/devicodeclaude-web/Rag-hermes-agent-.git
#   cd Rag-hermes-agent-
#   bash scripts/runpod_g0.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
REV="$(git rev-parse HEAD)"
echo ">> depot : $(pwd)"
echo ">> commit mesure : $REV"

if [ -n "$(git status --porcelain=v1 --untracked-files=all)" ]; then
  echo "!! ARBRE GIT MODIFIE — le runner refusera. Ne cree/modifie RIEN dans le clone." >&2
  echo "   (les logs vLLM vont dans /tmp, le venv .venv-vllm est gitignore)" >&2
  git status --porcelain=v1 --untracked-files=all >&2
  exit 1
fi

# --- Manifeste : lire le modele + la revision epinglee (source unique de verite)
MANIFEST="manifests/gpu/g0-closed-book-human-154.json"
REPO_ID="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['generator']['repo_id'])")"
MODEL_REV="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['generator']['revision'])")"
SERVED="$(python3 -c "import json;print(json.load(open('$MANIFEST'))['generator']['served_model_name'])")"
echo ">> modele servi : $REPO_ID @ $MODEL_REV (nom servi: $SERVED)"

# --- Python 3.12 (comme la CI / les wheels)
PY="$(command -v python3.12 || command -v python3)"
echo ">> interpreteur : $PY ($("$PY" -V 2>&1))"
case "$("$PY" -V 2>&1)" in
  *" 3.12."*) : ;;
  *) echo "!! ATTENTION : Python != 3.12. Prends un template pod PyTorch Ubuntu 24.04 (=3.12) si l'install vLLM echoue." >&2 ;;
esac

# --- Installer vLLM (il apporte sa propre pile torch/cuda ; NE PAS melanger avec
#     requirements-gpu.lock.txt, qui est la pile du retrieval, pas de la generation).
echo ">> creation du venv vLLM + installation…"
"$PY" -m venv .venv-vllm
# shellcheck disable=SC1091
. .venv-vllm/bin/activate
python -m pip install --upgrade pip wheel >/dev/null
# Pas de version epinglee ici (run infra). La version reelle est enregistree ci-dessous
# et devra etre EPINGLEE pour un run pre-inscrit.
pip install vllm hf_transfer
# hf_transfer est present mais on le desactive (meme piege que le smoke retrieval).
export HF_HUB_ENABLE_HF_TRANSFER=0
echo ">> version vLLM installee (A NOTER pour la reproductibilite) :"
python -c "import vllm; print('vllm', vllm.__version__)" || pip show vllm | grep -i version || true

# --- Servir le modele epingle via l'API OpenAI de vLLM (en arriere-plan).
VLLM_LOG="/tmp/vllm-g0.log"   # HORS du repo : ne pas salir l'arbre git
echo ">> demarrage de vLLM (telechargement du modele au 1er appel ; log: $VLLM_LOG)…"
python -m vllm.entrypoints.openai.api_server \
  --model "$REPO_ID" \
  --revision "$MODEL_REV" \
  --served-model-name "$SERVED" \
  --host 127.0.0.1 --port 8000 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  >"$VLLM_LOG" 2>&1 &
VLLM_PID=$!
# Toujours arreter vLLM en sortie (succes comme echec).
cleanup() { echo ">> arret de vLLM (pid $VLLM_PID)…"; kill "$VLLM_PID" 2>/dev/null || true; }
trap cleanup EXIT

echo ">> attente de la disponibilite de l'endpoint (jusqu'a 20 min)…"
READY=""
for _ in $(seq 1 240); do   # 240 x 5s = 20 min
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "!! vLLM s'est arrete avant d'etre pret. Fin du log :" >&2
    tail -n 40 "$VLLM_LOG" >&2
    exit 1
  fi
  if curl -fsS "http://127.0.0.1:8000/v1/models" >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 5
done
if [ -z "$READY" ]; then
  echo "!! endpoint toujours pas pret apres 20 min. Fin du log :" >&2
  tail -n 40 "$VLLM_LOG" >&2
  exit 1
fi
echo ">> endpoint pret."

# --- Lancer la campagne G0 (le worker n'a aucune dep lourde : le venv vLLM suffit).
export RAG_GENERATOR_BASE_URL="http://127.0.0.1:8000/v1"
export RAG_GENERATOR_MODEL="$SERVED"
echo ">> lancement de la campagne G0…"
PYTHONPATH=. python scripts/run_closed_book_campaign.py \
  --manifest "$MANIFEST" \
  --code-revision "$REV"

echo
echo "================ RESULTATS G0 (resume) ================"
PYTHONPATH=. python - <<'PY'
import json
from pathlib import Path
from rag_hermes.execution_receipt import load_consumable_receipt_v2

receipt = load_consumable_receipt_v2(
    Path("data/results/g0_closed_book_human_154_execution_receipt.json")
)
report = receipt["report"]
for key in ("job_id", "configuration", "status", "result_classification", "quality_gate_passed"):
    print(f"{key} = {report.get(key)}")
print("--- generator"); print(json.dumps(report.get("generator"), indent=2, ensure_ascii=False))
print("--- metrics_abstention"); print(json.dumps(report.get("metrics_abstention"), indent=2, ensure_ascii=False))
hr = report.get("human_review_sample", {})
print(f"--- reponses concretes a faire relire (>=20%) : {hr.get('answered_count')}")
PY
echo "======================================================"
echo ">> Recu complet (a me renvoyer) :"
echo "   data/results/g0_closed_book_human_154_execution_receipt.json"
echo ">> N'OUBLIE PAS la version de vLLM affichee plus haut (reproductibilite)."
echo ">> SUPPRIME le pod des que tu as le recu (sinon il continue a facturer)."
