# Relancer le smoke GPU sur Colab — mode d'emploi simple

Cette machine n'a pas de GPU. On lance donc le smoke BGE-M3 sur Google Colab
(gratuit). But : confirmer `rejected_pairs = 0` avec le découpage tokenizer exact.

Notebook prêt à l'emploi : `notebooks/colab_bge_gpu_smoke.ipynb`.

## Étapes (à faire une fois)

1. Créer un jeton GitHub en lecture seule pour ce dépôt
   - Va sur https://github.com/settings/personal-access-tokens/new
   - « Token name » : `colab-rag`
   - « Repository access » : `Only select repositories` → coche `Rag-hermes-agent-`
   - « Permissions » → `Repository permissions` → `Contents` : `Read-only`
   - Clique `Generate token` et **copie** le jeton (il commence par `github_pat_`).

2. Ouvrir le notebook dans Colab
   - Va sur https://colab.research.google.com
   - Onglet `GitHub` → connecte ton compte si demandé → cherche
     `devicodeclaude-web/Rag-hermes-agent-` → ouvre
     `notebooks/colab_bge_gpu_smoke.ipynb`.

3. Activer le GPU
   - Menu `Exécution` → `Modifier le type d'exécution` → `GPU` (T4 suffit) → `Enregistrer`.

4. Donner le jeton au notebook
   - Clique l'icône clé 🔑 à gauche (`Secrets`) → `Ajouter un secret`.
   - Nom : `GITHUB_TOKEN`. Valeur : colle le jeton de l'étape 1.
   - Active l'interrupteur « Accès au notebook ».

5. Lancer
   - Menu `Exécution` → `Tout exécuter`.
   - Le téléchargement des modèles prend ~2–4 min. À la fin, la cellule 6 affiche
     `PORTE JALON (0 rejet, 0 fuite) : OK` si tout va bien.
   - La cellule 7 télécharge `bge_m3_gpu_smoke_report.json` sur ton appareil.

## Ensuite

Envoie-moi le fichier `bge_m3_gpu_smoke_report.json` (ou son contenu) :
je vérifierai `rejected_pairs`, le recall et la fuite, puis je committerai le
nouveau rapport comme preuve du jalon.

## Note de rigueur

L'installation Colab utilise les versions du `pyproject` (`FlagEmbedding==1.3.5`,
`transformers==4.57.6`, `huggingface_hub==0.34.4`). Pour une reproductibilité
stricte avec empreintes, l'environnement de référence reste
`requirements-gpu.lock.txt` (x86_64 / Python 3.12). Le smoke valide l'exécution
matérielle et le câblage, pas la qualité statistique (10 questions seulement).
