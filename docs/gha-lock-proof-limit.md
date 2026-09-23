# Limite de la preuve du lock sur GitHub Actions

Le workflow `lock-install-x86_64-py312.yml` utilise un runner Ubuntu x86_64,
Python 3.12 et un venv vierge sans `--system-site-packages`. Il installe les
fichiers `requirements-*.lock.txt` avec `pip --require-hashes`, démarre Qdrant
1.19.0 x86_64 dont l'archive est vérifiée par SHA-256, puis exécute la CI
stricte. La preuve est téléversée même si la commande échoue.

Cette exécution peut prouver uniquement :

- la résolution effectivement matérialisée par les locks ;
- l'intégrité des distributions téléchargées par rapport aux hashes autorisés ;
- leur installabilité sur Ubuntu x86_64 avec Python 3.12 ;
- le résultat des tests CPU et Qdrant sur ce runner.

Elle ne prouve pas :

- l'identité avec une image GPU de production ;
- CUDA 12.8 ni `torch 2.8.0+cu128` ;
- le chargement des checkpoints BGE-M3 et du reranker sur GPU ;
- les kernels CUDA, la précision FP16, la VRAM, la latence ou le débit ;
- la compatibilité ou la reproductibilité du runtime A40.

Le lock GPU actuel décrit un environnement pip x86_64 et peut résoudre Torch
et les bibliothèques CUDA différemment d'une image GPU préconstruite. Un succès
GHA doit donc être formulé comme « résolution + hashes + installation/tests
x86_64/Python 3.12 prouvés ; runtime CUDA non prouvé ».
