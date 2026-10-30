# Preuve BM25 local — rapport régénéré après commit du code

## Verdict

**PASS technique**, niveau de preuve **intégration de composant** pour la comparaison de retrieval lexical.

Ce dossier ne constitue ni une preuve de qualité statistique indépendante ni un verdict de production. Le même dataset humain de 154 cas a servi au diagnostic et à la mesure : c'est descriptif, pas held-out.

## Changement mesuré

Le retriever lexical en mémoire utilise désormais un classement BM25 calculé uniquement sur les chunks déjà autorisés (ACL avant calcul IDF). Le seuil d'acceptation historique reste fondé sur le ratio de recouvrement lexical, exposé séparément via `effective_threshold_score` (fallback sur le score dense quand `threshold_score` vaut `None`).

| Piste | Mesure | Avant | Après |
|---|---:|---:|---:|
| Global | Recall@10 | 0,3361 | 0,5082 |
| Global | MRR | 0,1737 | 0,2951 |
| EN→EN primaire | Recall@10 | 0,4471 | 0,6471 |
| EN→EN primaire | MRR | 0,2339 | 0,3919 |
| FR→EN diagnostic | Recall@10 | 0,0811 | 0,1892 |
| FR→EN diagnostic | MRR | 0,0354 | 0,0726 |

Le compteur de fuite est resté à zéro dans l'évaluation en mémoire. Cela prouve seulement le chemin évalué ; les tests Qdrant réels vérifient séparément plusieurs scénarios d'isolation et de provisioning.

Défaut de qualité ouvert, non traité ici : `abstention_recall = 0` sur les 32 cas sans réponse.

## Environnement et commandes

- `before` : rapport lexical naïf à la revision git `3294a6b35ed944a5c7d7d7046693ab02dd9b4cd2`
- `after` / candidat : `code_revision` = `7638fc065c95329a448fa69953d15601cbd48083`, régénéré sur arbre propre
- Dataset : 154 cas humains validés (`dataset_sha256` 4613e8b3…)
- Corpus : 461 documents
- Matériel : CPU local
- Retriever : `in_memory_bm25`
- Générateur, embeddings et reranker : non exercés
- Qdrant de la suite complète : `qdrant 1.19.0`, `/healthz` réussi

Rapport humain (écrit l'artefact versionné) :

```text
PYTHONPATH=. .venv-audit/bin/python scripts/human_eval_report.py \
  --results data/results/human-lexical-eval-report.json \
  --checksum data/results/human-lexical-eval-report.sha256
```

Suite complète avec Qdrant réel :

```text
QDRANT_INTEGRATION_URL=http://127.0.0.1:6333 \
  .venv-audit/bin/python -m unittest discover -s tests -v
```

Résultat conservé : **378 tests réussis en 178,592 s**, sans skip déclaré. Les tests nommés d'intégration Qdrant sont visibles dans `tests-full-qdrant-reel.txt`.

Note sur `working_tree_dirty` : le rapport candidat enregistre désormais `working_tree_dirty: false`. Le script a été corrigé (commit `7638fc0`) pour capturer l'état git AVANT l'invalidation du rapport et exclure du calcul les seuls fichiers de sortie qu'il régénère (voir `rag_hermes/git_status.py`). Un vrai changement non commité hors de ces fichiers resterait détecté comme `dirty` (jamais de faux négatif).

## Artefacts

- `human-lexical-bm25-report.json` : copie figée du rapport officiel `data/results/human-lexical-eval-report.json` (SHA256 identique) ;
- `comparaison.json` : interprétation séparée avant/après, avec provenance git du baseline ;
- `tests-full-qdrant-reel.txt` : sortie complète de la suite avec Qdrant réel ;
- `SHA256SUMS` : empreintes des trois artefacts ci-dessus.

Vérification :

```text
sha256sum -c AUDIT/preuves/bm25-exploratoire/SHA256SUMS
```

## Limites et prochaine expérience

1. La comparaison est descriptive : le dataset n'est pas un jeu de test indépendant et aveugle.
2. FR→EN reste un diagnostic lexical non équitable ; BM25 n'est pas un retriever multilingue.
3. Aucun modèle dense BGE-M3, reranker ou générateur n'a été exercé.
4. Prochain défaut prioritaire : l'abstention (`abstention_recall = 0`), à traiter avec un signal de confiance calibré sur un jeu distinct, sans dégrader le Recall@10 des 122 cas répondables.
5. Pour une affirmation de qualité, définir un jeu held-out indépendant, des seuils avant exécution et des intervalles d'incertitude.
