# Preuves — baseline lexicale humaine

Niveau de preuve : **intégration de composant avec mesure descriptive sur dataset humain**.
Ce dossier ne démontre ni qualité statistique complète ni aptitude à la production.

## Exécution

- Dataset : `data/benchmark/dataset-v2.jsonl` — 154 cas validés.
- Corpus : `data/generated/hermes_public_documents.jsonl` — 461 documents.
- Baseline : recherche lexicale en mémoire, sans embeddings, reranker ni générateur.
- Paramètres : `k=10`, `minimum_score=0.05`.
- Rapport brut : `data/results/human-lexical-eval-report.json`.
- Empreinte : `data/results/human-lexical-eval-report.sha256`.
- Qdrant réel : 1.19.0 sur loopback, activé par `QDRANT_INTEGRATION_URL` pour la suite complète.
- Commande exacte : `QDRANT_INTEGRATION_URL=http://127.0.0.1:6451 .venv-audit/bin/python -m unittest discover -s tests -v`.
- Avant la suite : `/healthz` → `healthz check passed`; binaire → `qdrant 1.19.0`.
- Après la suite : arrêt SIGTERM confirmé et port 6451 inaccessible.
- Protocole de publication : checksum d’abord, rapport en dernier comme marqueur de commit ; le consommateur exige les deux et vérifie l’empreinte.

## Résultats directement mesurés

- Global : Recall@10 0,3361 ; MRR 0,1737.
- EN→EN : Recall@10 0,4471 ; MRR 0,2339.
- FR→EN : Recall@10 0,0811 ; MRR 0,0354 — diagnostic seulement.
- Rappel d’abstention : 0,0 au seuil 0,05.
- Fuite : 0.
- Tests ciblés : 62 réussis.
- Suite complète : 365 réussis, 0 skip, avec Qdrant réel.

## Limites

- Le rapport brut initial porte `working_tree_dirty: true` : il a été produit avant le commit du code qui crée ce runner.
- Après autorisation du commit de code, le rapport doit être rejoué depuis un arbre propre puis republié avec son empreinte finale.
- Aucun intervalle bootstrap n’est calculé.
- Le score FR→EN lexical n’est pas une baseline translingue équitable.
- Les jugements humains de validité et de support des citations ne sont pas instrumentés (`null`).
