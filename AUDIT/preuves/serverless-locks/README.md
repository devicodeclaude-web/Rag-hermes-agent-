# Preuves locales des locks RunPod Serverless

Date : 2026-10-27

## Portée

Ce dossier atteste uniquement :

- la compilation des deux locks avec `uv 0.13.4` ;
- la cible de résolution CPython 3.12 / `x86_64-manylinux_2_28` ;
- deux régénérations consécutives produisant les mêmes SHA-256 ;
- une consommation sèche avec `--require-hashes` dans un venv CPython 3.12.14.

Il ne prouve pas la construction d’une image Serverless, l’exécution de `import torch`, la disponibilité d’un GPU ni l’exécution de la campagne.

## Résultats

| Artefact | Résultat |
|---|---|
| `requirements-serverless.lock.txt` | 101 paquets ; SHA-256 `cb09ee07dabfe3ba3902ca1966b77d28d2f3db9e2693a8aeceb41c95dabde58e` |
| `requirements-serverless-gpu.lock.txt` | 151 paquets, dont la roue Torch directe ; SHA-256 `149fe07cd6ce77ca5470acc2337bac50b5e14392867f626a9f26a87f011186c4` |
| Régénération consécutive | PASS, voir `locks-pass1.sha256`, `locks-pass2.sha256` et `reproducibility.txt` |
| Dry-run SDK | PASS, voir `dry-run-sdk.txt` |
| Dry-run GPU | PASS, voir `dry-run-gpu.txt` |
| Revue indépendante finale | PASS, voir `final-independent-review.txt` |

## Commandes essentielles

```text
UV_BIN=/chemin/uv-0.13.4 .venv-audit/bin/python -m scripts.compile_serverless_lock
UV_BIN=/chemin/uv-0.13.4 .venv-audit/bin/python -m scripts.compile_serverless_gpu_lock
uv venv <temp>/venv --python 3.12 --no-python-downloads
uv pip install --python <temp>/venv/bin/python --dry-run --require-hashes \
  --python-platform x86_64-manylinux_2_28 --python-version 3.12 \
  -r requirements-serverless.lock.txt
uv pip install --python <temp>/venv/bin/python --dry-run --require-hashes \
  --python-platform x86_64-manylinux_2_28 --python-version 3.12 \
  -r requirements-serverless-gpu.lock.txt
```

`SHA256SUMS` couvre tous les fichiers de preuve de ce dossier, hors ce README et `SHA256SUMS` lui-même.
