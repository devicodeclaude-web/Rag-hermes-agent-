# Runbook — smoke GPU sécurisé (chunking tokenizer + garde budget)

Ce runbook est la seule procédure autorisée pour relancer le smoke GPU après l’audit.
Aucun Pod ne doit être créé tant que les portes 1 à 4 ne sont pas vertes.

## Porte 0 — Prérequis secrets (préparés par l’utilisateur, jamais transmis)

1. Clé API RunPod **Restricted**, limitée à la gestion des Pods
   (console → Settings → API Keys → Restricted → Pods: Read/Write).
2. Clé SSH dédiée **avec passphrase**, chargée dans `ssh-agent` :
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/runpod_rag_bge -C rag-bge-runpod   # saisir une passphrase
   chmod 600 ~/.ssh/runpod_rag_bge
   eval "$(ssh-agent -s)" && ssh-add ~/.ssh/runpod_rag_bge
   ```
3. Enregistrer uniquement la moitié publique sur RunPod, sans écraser d’autres clés.

## Porte 1 — Validation locale hors dépense

```bash
cd /root/rag-hermes-agent
QDRANT_INTEGRATION_URL=http://127.0.0.1:6333 python -m unittest discover -s tests -q
PYTHONPATH=. python scripts/plan_bge_gpu_job.py
```

Exigences : suite verte, intégration Qdrant réelle incluse, contrat de chunking
(question 96 / passage 384 / overlap 64 / réserve 32 ≤ 512) validé.

## Porte 2 — Preuve ACL sur Qdrant réel

Serveur épinglé 1.19.0, vecteurs identiques, fuite absolue = 0
(`data/results/qdrant_acl_audit_report.json`). Aucune revendication de qualité
sémantique : les vecteurs sont `deterministic-test-only-not-an-embedding`.

## Porte 3 — Garde budget/durée armée AVANT le workload

Le watchdog est un superviseur indépendant. Il ne lit aucune sortie du benchmark.

```bash
export RUNPOD_API_KEY=...          # clé Restricted
NAME="rag-bge-m3-guarded-$(date -u +%Y%m%dT%H%M%SZ)"
CREATED_AFTER="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PYTHONPATH=. python scripts/pod_watchdog.py \
  --name "$NAME" --created-after "$CREATED_AFTER" \
  --hourly-rate-usd 0.74 --max-duration-minutes 30 --max-total-cost-usd 0.50 &
```

Le watchdog :
- calcule l’échéance de terminaison et le coût estimé ;
- refuse un plan dont le coût dépasse le plafond ;
- sélectionne uniquement le Pod au nom exact créé après `CREATED_AFTER` ;
- échoue fermé si plusieurs Pods correspondent ;
- supprime le Pod à l’échéance même si le benchmark a planté ;
- confirme l’absence du Pod après suppression.

## Porte 4 — Provisionnement non-root

Créer le Pod avec ce nom exact, puis, sur le Pod :

```bash
# bootstrap non-root (généré par rag_hermes.pod_security.build_non_root_bootstrap)
useradd --create-home --shell /bin/bash ragbench
install -d -m 0750 -o ragbench -g ragbench /opt/ragbench
chown -R ragbench:ragbench /opt/ragbench
# workload sous privilèges réduits
runuser -u ragbench -- bash -lc 'cd /opt/ragbench && PYTHONPATH=. python scripts/run_bge_gpu_smoke.py'
```

## Porte 5 — Smoke reconstruit et critères d’acceptation

Le runner régénère le corpus avec le chunking tokenizer, encode dense+sparse,
récupère au moins 20 candidats, rerank sans troncature, puis persiste dans Qdrant
seulement après validation.

Critères durs du prochain run :
- `rejected_pairs = 0` ;
- `truncated_pairs = 0` ;
- fuite ACL = 0 ;
- détail par question avant et après reranking ;
- Recall@10 post-reranking ≥ Recall@10 sans reranker ;
- temps de reranking mesuré séparément.

Rappel : avec MRR = 1 avant reranking sur le smoke, le reranker ne peut pas
démontrer d’amélioration. Son utilité sera jugée sur le futur jeu de 100 puis 300
questions, dont au moins 30 écrites à la main sans regarder les chunks.

## Porte 6 — Récupération et arrêt

1. Copier le rapport hors du Pod.
2. Vérifier et hacher le rapport localement.
3. Laisser le watchdog confirmer la suppression, ou supprimer manuellement.
4. Vérifier que `runpodctl pod list --all` ne renvoie plus le Pod.
5. Estimer le coût à partir de la durée observée, en le qualifiant d’estimation.
