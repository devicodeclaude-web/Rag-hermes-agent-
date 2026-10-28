# Faisabilité d’une campagne BGE-M3 sur RunPod Serverless

Faits RunPod vérifiés le 2026-10-19 ; lock local revérifié le 2026-10-27.

## Verdict

**PARTIAL — ne pas déployer en l’état.**

RunPod Serverless fournit des limites côté fournisseur (`executionTimeout`, TTL du
job et `workersMin=0`) qui répondent mieux au risque d’un Pod restant facturé.
Un scaffold local de handler queue-based existe désormais dans
`scripts/runpod_serverless_handler.py` et sa logique locale est testée. Le lock combiné
CUDA/PyTorch/SDK a été résolu et accepté en installation sèche pour le runtime attendu.
Un Dockerfile candidat épinglé et un générateur de contexte limité au commit existent dans
`containers/serverless/Dockerfile` et `scripts/prepare_serverless_build_context.py`.
Ils ne constituent toutefois pas un worker déployable : aucune image Serverless n’a été construite
et le runtime n’a été validé ni par l’exécution de `import torch` dans la base candidate,
ni par une campagne. La durée réelle reste donc inconnue. Le plafond financier de
0,50 USD n’est pas compatible avec une fenêtre A40 de 30 minutes au tarif vérifié.

Aucun endpoint, worker, Pod ou autre ressource payante n’a été créé pendant cette
étude.

## Faits vérifiés

- `runpodctl 3.0.1` ne propose pas `pod create --terminate-after`.
- L’API/MCP de création de Pod inspectée ne fournit pas non plus d’expiration
  automatique du Pod.
- La porte 3 du runbook Pod reste donc fermée.
- RunPod Serverless expose :
  - `workersMin=0` ;
  - un timeout d’exécution ;
  - une politique TTL couvrant file d’attente et exécution ;
  - le retour automatique à zéro worker après inactivité.
- Tarif Serverless vérifié pour le groupe A40/A6000 48 Gio : 0,00034 USD/s.
- Version stable du SDK vérifiée sur PyPI : `runpod==1.12.0` ; le lock
  `requirements-serverless.lock.txt` est généré avec `uv==0.13.4` pour CPython
  3.12 et `x86_64-manylinux_2_28`, puis accepté en installation sèche avec hashes
  obligatoires (101 paquets).
- `uv==0.13.1` a été abandonné : son magasin de CA embarqué est concerné par
  `GHSA-hq85-5cpj-mr62`; `uv==0.13.4` retire la racine compromise.
- Le lock combiné `requirements-serverless-gpu.lock.txt` résout 151 paquets pour
  le runtime attendu CPython 3.12 et `x86_64-manylinux_2_28`. Il référence directement
  la roue officielle `torch==2.8.0+cu128` avec son SHA-256, et épingle notamment
  `triton==3.4.0`, `runpod==1.12.0` et `FlagEmbedding==1.3.5`, puis passe une
  installation sèche avec hashes obligatoires pour cette cible.
- Deux régénérations consécutives avec `uv==0.13.4` ont produit des fichiers
  strictement identiques selon `sha256sum`. Les commandes, sorties de compilation,
  dry-runs et checksums sont conservés dans
  `AUDIT/preuves/serverless-locks/`.
- Base officielle candidate vérifiée :
  `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`. Le digest de l’index
  OCI multi-plateforme est
  `sha256:0a360022e8de4375af99430f84e8b38951acc397252163a37ceac7204d01be35` ;
  son manifeste enfant `linux/amd64` distinct est
  `sha256:4d1721e62b56d345c83b4fd6090664be6daf9312caab5b2e76f23d8231941851`.
  Le tag et ces digests identifient la base candidate, mais n’attestent pas que `import torch` fonctionne
  dans l’image finale.

## Budget

| Fenêtre facturable | Coût au tarif vérifié |
|---:|---:|
| 20 minutes | 0,4080 USD |
| 24 minutes | 0,4896 USD |
| 30 minutes | 0,6120 USD |

Le plafond théorique correspondant à 0,50 USD est d’environ 1 470,6 secondes,
soit 24 min 30 s. Ce calcul ne constitue pas un plafond monétaire fournisseur :
il faut encore tenir compte du chargement en VRAM, de l’arrêt du worker, d’un
éventuel changement de tarif et de toute nouvelle tentative. RunPod n’expose pas
de plafond monétaire par job.

## Éléments conservables

Une architecture Serverless queue-based pourrait conserver :

- le snapshot humain immuable de 154 cas
  `data/benchmark/dataset-v2-human-154.jsonl` (SHA-256
  `4613e8b3b84fb7b24ad66cf01329f40d95934bec189fe7f6cddf1eb751c767d4`),
  distinct du dataset actif désormais étendu à 300 cas ;
- le corpus immuable correspondant
  `data/generated/hermes_public_documents-human-154.jsonl` (SHA-256
  `af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866`),
  distinct du corpus actif dont le schéma ACL a évolué ;
- les verrous de modèles et leurs révisions Hugging Face ;
- le split déterministe calibration 81 / holdout 73 ;
- le checkout Git propre et la révision auditée ;
- le reçu autonome `gpu_execution_receipt.v2` ;
- les contrôles JSON, chemins, publication atomique et provenance existants.

## Architecture minimale à valider

1. Image `linux/amd64` fondée sur la base CUDA/PyTorch épinglée par digest ci-dessus.
2. Checkout Git propre complet, `.git` inclus, sous `/opt/ragbench`.
3. Worker queue-based qui :
   - valide le commit attendu ;
   - lance `python -m scripts.run_bge_gpu_campaign` ;
   - recharge le reçu avec `load_consumable_receipt_v2` ;
   - renvoie ce reçu comme résultat du job.
4. Endpoint avec un seul worker maximum, `workersMin=0`, idle minimal et limites
   fournisseur explicites.
5. Invocation asynchrone `/run`, polling borné jusqu’à un état terminal, puis
   persistance et validation immédiates du résultat avant suppression vérifiée de
   l’endpoint et du template.

Le contexte de construction doit être produit depuis un checkout propre et commité,
dans un répertoire extérieur au dépôt :

```bash
.venv-audit/bin/python scripts/prepare_serverless_build_context.py \
  --repository /root/rag-hermes-agent \
  --output-root /tmp/rag-serverless-contexts
```

La commande crée un répertoire nommé par le SHA Git contenant uniquement
`Dockerfile`, `repository.tar` et `context-manifest.json`. `repository.tar`
contient un checkout Git shallow limité au seul commit attesté : aucun objet
parent n’est embarqué. Le Dockerfile refuse un `RAG_CODE_REVISION` différent
du manifeste ou du checkout reconstruit. Une construction future devra utiliser
ce répertoire comme contexte et transmettre ce SHA via
`--build-arg RAG_CODE_REVISION=<sha>`. Aucun `COPY .` du répertoire de
travail n’est autorisé.

## Blocages avant toute dépense

- Le lock combiné CUDA/PyTorch/SDK est résolu et vérifié en installation sèche,
  mais n’a pas encore été installé ni exécuté dans la base candidate. Il ne prouve
  donc pas à lui seul une image reproductible ou fonctionnelle.
- Le Dockerfile et le générateur de contexte sont testés statiquement et l’archive
  Git shallow est générée puis extraite dans les tests, mais aucun moteur
  Docker/Podman/Buildah n’est
  disponible dans l’environnement actuel : l’image n’a pas été construite.
- Les deux modèles verrouillés représentent environ 4,576 Go ; leur stratégie de
  cache doit être testée sans téléchargement ou duplication imprévue.
- La campagne complète n’a jamais été chronométrée ; rien ne prouve qu’elle tient
  dans une fenêtre prudente inférieure à 24 minutes.
- Le manifeste exige exactement une `NVIDIA A40` et au moins 40 Gio. Les pools
  Serverless peuvent aussi attribuer une A6000 ; le contrôle matériel doit rester
  fail-closed.
- L’image ne peut pas encore être construite ou exécutée localement : Docker,
  Podman, Buildah et Skopeo ne sont pas présents. Le manifeste `linux/amd64`
  totalise environ 9,84 Gio de couches compressées alors que l’environnement ne
  dispose que d’environ 14 Gio libres ; le téléchargement puis le décompactage
  local ne constituent donc pas une validation sûre. `uv==0.13.4` a uniquement
  servi dans un venv temporaire à compiler, régénérer et vérifier en mode sec les
  locks ; aucun paquet du lock GPU n’a été installé.
- La base contient des paquets système préinstallés. Le Dockerfile définit un venv
  avec accès aux paquets système et un lock hashé, mais l’image doit encore être
  construite pour exclure tout remplacement silencieux ou conflit avec
  PyTorch/CUDA et les paquets Debian de la base.
- Le checkout Git shallow requis pour la provenance est limité au seul commit
  attesté ; les tests prouvent que les objets parents et un secret supprimé dans
  l’historique ne sont pas embarqués. L’image finale devra encore être inspectée
  après sa première construction réelle.
- Le résultat doit rester sous la limite de sortie de `/run` et être sauvegardé
  avant expiration de sa rétention.
- Aucun mécanisme ne garantit actuellement un plafond monétaire strict de
  0,50 USD pour cette campagne.

## Décision

Ne pas créer de template, endpoint, worker ou job Serverless tant que **tous** les
prérequis techniques cumulatifs suivants ne sont pas fermés et audités :

- image et handler reproductibles construits et testés sans GPU payant ;
- environnement CUDA/PyTorch verrouillé sur la cible ;
- cache des modèles, matériel exact, taille du résultat et récupération après
  polling validés ;
- durée de campagne suffisamment bornée par une preuve non payante ou par une
  expérience séparée disposant de sa propre autorisation de dépense ;
- nettoyage de l’endpoint et du template vérifiable et fail-closed.

Il faut ensuite choisir **et auditer** une solution budgétaire : réduire la fenêtre
d’exécution, relever le plafond, sélectionner un GPU moins coûteux avec un
manifeste honnêtement modifié, ou obtenir un plafond monétaire/une expiration
RunPod couvrant toute la durée facturable.

Même si tous ces prérequis sont satisfaits, ils ne constituent pas une autorisation
de dépense. Toute création de ressource ou expérience payante exige une
autorisation utilisateur séparée, explicite, indiquant son plafond total.
