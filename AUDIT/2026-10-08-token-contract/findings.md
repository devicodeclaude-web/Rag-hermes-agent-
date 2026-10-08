# Lot 2 — contrat de tokens : synthèse de preuve

- Date d'exécution : 2026-10-08 (UTC), CPU uniquement, aucun GPU.
- Décision produit : Option A (rejet par paire + poursuite ; `ERROR_TOKEN_BUDGET`
  seulement si tous les candidats sont rejetés).
- Tokenizer de preuve : `BAAI/bge-reranker-v2-m3` @ `953dc6f6…` (révision verrouillée),
  chargé en local, exécuté en CPU (tokenisation seule, pas de forward GPU).

## Ce qui est prouvé (exécuté cette session)

Tests unitaires (logique, tokenizer injecté) — `tests/test_token_contract.py`, 8 cas :
  commande : `python3 -m unittest tests.test_token_contract` → OK.
Non-régression du périmètre — `tests.test_production_retrieval`,
  `tests.test_reranker_budget`, `tests.test_evaluation`, `tests.test_ingestion`
  → 30/30 OK (tests existants inchangés).

Mesure exacte sur le corpus réel (465 docs, 10 questions) —
  `AUDIT/2026-10-08-token-contract/token_budget_measurement.json` :

| | Avant (mots 420/40) | Après (tokens 384/64) |
|---|---:|---:|
| chunks | 2 945 | 7 371 |
| passage tokens (min/p50/p95/max) | 28 / 873 / 1252 / 2054 | 28 / 384 / 385 / 386 |
| paires q×chunk (min/p50/p95/max) | 35 / 882 / 1261 / 2065 | 35 / 393 / 395 / 397 |
| paires > 512 | 26 761 / 29 450 (90,87 %) | 0 / 73 710 (0 %) |

Invariant de tokens spéciaux vérifié : `len(pair) == len(q) + len(p) + 4` (XLM-R),
contrôlé sur un échantillon avant d'étendre le calcul.

Budget de passage dérivé d'une marge de question NOMMÉE :
`passage_token_budget(reranker_max_length=512, question_token_margin=96,
special_token_reserve=32) = 384`.

## Interprétation

- Le chunking par mots produisait ~91 % de paires hors budget : confirmé avec le
  tokenizer EXACT (et non l'approximation 1.4 de l'ablation committée). Le ratio
  réel mots→tokens sur cette doc est ~2,0 (p50 : 873 tokens pour 420 mots), car le
  markdown/code est dense — ce qui explique pourquoi l'approximation sous-estimait.
- Le chunking par tokens borne les paires bien sous 512 (max observé 397).
- `pairs_over_budget` passe de 26 761 à 0.

## Résidu honnête (non corrigé, hors menace budget)

- `chunk_document_tokens` vise `max_passage_tokens=384` mais le passage ré-encodé
  atteint 386 tokens (p95 385, max 386). Cause : découpe par offsets de caractères
  puis re-tokenisation, non identique au comptage par tokens. Le budget 512 reste
  respecté avec marge (paire max 397). La garantie « passage ≤ 384 exact » n'est
  donc PAS littérale ; aucune troncature silencieuse n'est introduite.

## Non prouvé dans cette session

- Le chemin GPU réel (`scripts/run_bge_gpu_smoke.py`) a été câblé au nouveau contrat
  (alignement sur `counters.scored`, capture `ERROR_TOKEN_BUDGET`, `rejected_candidates`
  par requête, garde de provenance tokenizer + garde structurelle de budget) mais
  N'A PAS été exécuté : il requiert un GPU payant + les modèles. Le forward du
  reranker n'est pas ce que mesure le contrat de tokens.
- Identité de tokenisation à la frontière interne de `FlagReranker.compute_score`
  non instrumentée (hypothèse : même tokenizer que `count_pair_tokens`).
- La règle « nouveau manifeste si le corpus change » n'est pas automatisée (process).

## Revue critique (sous-agent, 2026-10-08)

Verdict : APPROUVÉ, aucun bloquant. Les 5 risques ciblés (troncature cachée,
off-by-one spéciaux, tokenizer divergent ingestion/reranker, garde par `assert`,
erreur comptée comme abstention) sont correctement traités.

Constats mineurs — suite donnée :
- Appliqué : `maximum_pair_tokens` calculé sur toutes les paires vérifiées
  (conservées + rejetées), `rag_hermes/retrieval.py`.
- Appliqué : garde de provenance tokenizer (déclaré == verrouillé) et garde
  structurelle `passage_max_tokens <= passage_token_budget(...)` dans le runner.
- Différé (documenté) : `chunk.token_count` = span pré-slicing (≤ texte ré-encodé,
  drift ±2) ; instrumentation de la frontière interne du reranker ; retrait de
  `assert_pair_fits` (conservée pour le cas paire-unique).

## Environnement de la preuve

- Tokenizer tooling installé hors dépôt : `/root/work/venv` (transformers 5.19, tokenizers),
  sans torch. Modèle tokenizer : `/root/work/models/bge-reranker-v2-m3`.
- Corpus public reconstruit : clone `NousResearch/hermes-agent@b682a98` (461 md/mdx)
  → `scripts/build_public_corpus.py` → `data/generated/hermes_public_documents.jsonl`
  (461 docs) + 4 fixtures = 465.
- Rejouer : `PYTHONPATH=. python AUDIT/2026-10-08-token-contract/measure_token_budget.py`.
