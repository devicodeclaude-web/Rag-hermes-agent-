# Runbook — Baseline G0 closed-book (sans retrieval) sur le pod GPU

Statut : **run d'infrastructure** (`infrastructure_smoke_only`). G0 est la baseline
sans récupération exigée par `docs/acceptance-criteria.md` : le modèle répond de
mémoire, sans corpus, sans sources, sans citations. Ce n'est **pas** un résultat
de qualité pré-inscrit — `docs/evaluation-protocol-v2.md` est encore un BROUILLON.

## Ce que G0 mesure (et ne mesure pas)

- **Mesuré hors-ligne** : l'axe **abstention honnête** sur les 154 cas humains
  (32 `no_answer` où l'abstention est requise, 122 `simple` répondables) —
  précision/rappel d'abstention + échecs fournisseur comptés à part.
- **PAS mesuré hors-ligne** : la justesse des réponses concrètes sur les 122 cas
  répondables. Le runner les remonte par `case_id` pour la **revue humaine
  aveugle ≥20 %** (aucune métrique automatique ne les score).

## Modèle (épinglé dans le manifeste)

`manifests/gpu/g0-closed-book-human-154.json` fige :
`Qwen/Qwen2.5-7B-Instruct` révision `a09a35458c702b33eeacc393d103063234e8bc28`,
servi par **vLLM**, décodage `temperature 0 / max_tokens 512` (= exactement ce
que code le générateur closed-book, le worker refuse tout écart).

## Pré-vol pod

- GPU **x86_64** (A40 48 Go idéal, ~0,40 $/h ; le 7B tient large). **Jamais**
  GH200/GB200 (ARM).
- Template **PyTorch Ubuntu 24.04** (= Python 3.12).
- Clone git **propre** au commit à mesurer (le runner refuse un arbre modifié).
  Les logs vLLM vont dans `/tmp`, le venv `.venv-vllm` est gitignoré → l'arbre
  reste propre.

## Procédure (sur ordinateur, terminal web du pod)

```bash
git clone https://<TOKEN_LECTURE_SEULE>@github.com/devicodeclaude-web/Rag-hermes-agent-.git
cd Rag-hermes-agent-
git pull   # s'assurer d'être au dernier main
bash scripts/runpod_g0.sh
```

Le script : installe vLLM → sert le modèle épinglé → attend l'endpoint
(`http://127.0.0.1:8000/v1`, jusqu'à 20 min le temps du téléchargement) → lance
`scripts/run_closed_book_campaign.py` → affiche le résumé → arrête vLLM.

**Note la version de vLLM affichée** (ligne « version vLLM installée ») : elle
n'est pas encore épinglée (run infra) et devra l'être pour un run pré-inscrit.

## Récupérer le reçu

Artefact unique consommable : `data/results/g0_closed_book_human_154_execution_receipt.json`.
Même route que la campagne retrieval (le terminal web colle mal sur mobile) :

```bash
curl -F "file=@data/results/g0_closed_book_human_154_execution_receipt.json" https://tmpfiles.org/api/v1/upload
```

Renvoie l'URL affichée ; le reçu est ensuite vérifié (sha256 auto-cohérent) et
committé dans le repo comme artefact officiel.

## Après le run

- **Supprime le pod** dès le reçu récupéré (facturation).
- Étape suivante : geler `docs/evaluation-protocol-v2.md` (seuils + schéma), puis
  construire G1 (RAG de production : R3 + ACL + génération + citations) pour la
  comparaison G0 vs G1.

## Limites honnêtes consignées dans le reçu

- G0 ne score que l'abstention ; la justesse des réponses attend la revue humaine.
- L'identité du modèle servi est assertée par l'opérateur (`RAG_GENERATOR_MODEL`
  vs manifeste), pas prouvée cryptographiquement.
- Protocole v2 en brouillon → run non pré-inscrit.
- Les échecs fournisseur ne sont ni réponses ni abstentions et gardent leur place
  dans le total.
