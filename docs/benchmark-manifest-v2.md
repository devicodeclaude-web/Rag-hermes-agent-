# Manifeste du benchmark v2 (gel)

Date de gel : 2026-11-02 UTC.
Révision git : `c48e3a0ff147afe876d0c465a894b0402576faed` (`audit-20260923-246-gc48e3a0`).
Lock machine-vérifiable : `manifests/locks/benchmark-v2.lock.json`.
Empreinte agrégée du benchmark (`benchmark_sha`) :
`654dd33f50049bf7b12002f307b21383b773aad97e9f2a1ebc2212e1b0b5b3fd`.

Toutes les empreintes ci-dessous sont des **sha256 bruts** du fichier (octet pour
octet). La porte CI `dataset-qa` exécute `scripts/verify_benchmark_lock.py`, qui
recalcule chaque sha + compte, l'empreinte agrégée et l'invariante public-only, et
échoue à la moindre dérive. Le test `tests/test_benchmark_lock.py` grave les mêmes
invariants dans la suite.

## Jeu d'évaluation actif (public-only)

- Fichier : `data/benchmark/dataset-v2.jsonl`
- SHA-256 : `e976b648c783018db88440e6e89de01eb50c56e8cfc32edb973ca8a1284209e6`
- Nombre de cas : 300
- Invariante : `acl_probe` = `False` partout (jeu public-only, gravé par
  `tests/test_dataset_qa.py`).
- Distribution par catégorie :

  | catégorie         | cas |
  |-------------------|-----|
  | simple            | 76  |
  | paraphrase        | 60  |
  | close_distractor  | 60  |
  | chunk_boundary    | 44  |
  | no_answer         | 60  |
  | **total**         | 300 |

## Strates (fichiers dédiés, hors jeu actif)

Les strates de sécurité restent dans des fichiers séparés pour préserver
l'invariante public-only du jeu actif.

- `data/benchmark/dataset-v2-acl-probe.jsonl` — 11 cas —
  SHA-256 `9fb1f1933060e9e2505e4093348299b2f7bdb187d3ca56d6d99f6f3f0c6446b0`
- `data/benchmark/dataset-v2-contradiction.jsonl` — 8 cas —
  SHA-256 `dc32025b527f065b96cb2859c9cde7f9c63b8a9935b3c653dc618ea8d93daaa2`
- `data/benchmark/dataset-v2-injection.jsonl` — 8 cas —
  SHA-256 `90e813cc2e060fdc30ff718239c6a214759faa2aa2fe685ee589bec12605c2f9`

## Fixtures dépendantes

- `data/fixtures/contradiction_documents.jsonl` — 8 docs —
  SHA-256 `fd7c2ae9bf08387ed19956e7297ad221200f7be51971383743848c6d871163ff`
- `data/fixtures/injection_documents.jsonl` — 8 docs —
  SHA-256 `50c19d0c8847287ae8a22251595e0e68a99e1455dbb4763523c6863997a2e4b0`
- `data/fixtures/private_and_synthetic_documents.jsonl` — 4 docs —
  SHA-256 `8276caa3bcd86d1759b69e34120b804cae3460e8476986e80d079ce9bc65a19b`

## Corpus

L'identité du corpus public d'évaluation est épinglée séparément dans
`manifests/locks/corpus.lock.json` (461 docs, révision source
`b682a98ab8cb30c4f0561021e0ff9f41e5156526`, manifest sha
`793e3b9c24bf706e8590386e6306e1819243e6d09b0040b4423c18c095cfe586`) et vérifiée
par `scripts/verify_corpus_lock.py`.

## Statut de revue (honnêteté)

- **Revue agent** : un relecteur agent indépendant (contexte neuf, aucune part de
  rédaction) + une revue croisée inter-vendeur (xAI/Grok) ont tous deux conclu
  `validate` sur les derniers cas litigieux (`v3na-169`, `v3na-170`).
- **Revue humaine INDÉPENDANTE : NON ATTEINTE.** Les validations d'auteur
  (`devicodeclaude-web`) sont des auto-revues (auteur = réviseur). Un second
  humain indépendant reste requis pour cocher ce critère. Cette limite est gravée
  dans les `review_note` des cas concernés et ne doit pas être surclamée.

## Reconstruction / vérification

```
PYTHONPATH=. python3 scripts/verify_benchmark_lock.py
PYTHONPATH=. python3 -m unittest tests.test_benchmark_lock
```

Suite complète au gel : `571 tests OK (skipped=19)`.
