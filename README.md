# RAG Hermes Agent — MVP vérifiable

Assistant RAG francophone consacré à **Hermes Agent de Nous Research** : installation, configuration, modèles, bots, automatisations, sécurité et dépannage sous Debian, Ubuntu, WSL et Termux.

Ce dépôt est un harnais de preuve, pas encore une plateforme de production. Il construit ensemble le pipeline minimal et son évaluation. Keycloak, OpenBao, Valkey, Langfuse, stockage objet et OpenSearch restent hors du MVP.

## État réellement vérifié

- Corpus officiel Hermes Agent cloné au commit `b682a98ab8cb30c4f0561021e0ff9f41e5156526`.
- 461 fichiers Markdown/MDX convertis en documents publics versionnés.
- Fixtures privées/synthétiques pour quatre contextes et trois faux tenants.
- ACL appliquées avant scoring, avec corpus global public explicite.
- Chunks porteurs de `tenant_id`, ACL, `doc_version`, `source_sha` et `source_uri`.
- Filtre Qdrant construit systématiquement à partir d’un contexte d’autorisation.
- Qdrant 1.19.0 aarch64 réellement démarré sur `127.0.0.1` ; 2 945 chunks persistés.
- Dix index payload créés ; `tenant_id` est confirmé avec `is_tenant: true` par lecture de la collection.
- Probes réels : accès privé autorisé pour Alpha/Beta/Gamma, refus par clearance, fuite inter-tenant `0`.
- Métriques : recall@k, MRR, précision des citations, précision/rappel d’abstention et fuite absolue.
- Deux profils d’inférence exacts : GGUF + llama.cpp et BF16 + vLLM.
- Baseline lexicale exécutée : recall@10 `0,667`, rappel d’abstention `0,25`, fuite `0`.
- Smoke d’infrastructure BGE-M3 exécuté sur RTX 4090 : 2 945 chunks en `24,88 s`, soit `118,38 chunks/s`, pic CUDA alloué `1,11 Gio`.
- Signal de smoke dense+sparse avant reranking : recall@10 `1,0` et MRR `1,0` sur seulement 10 questions, dont certaines dérivées du corpus ; ce n’est pas une preuve de qualité générale.
- Le filtrage ACL de ce runner a été appliqué en mémoire Python avant scoring. Il n’a pas exercé Qdrant et ne valide donc pas la barrière ACL du moteur réel.
- Le contrôle exact du reranker a refusé `190/200` paires dépassant 512 tokens. Le recall post-reranking `0,667` correspond à `4/6` questions répondables ; le reranker n’a pas été valablement évalué.
- La cause est une déviation de spécification : `max_tokens=420` comptait des mots via `str.split()`, alors que le contrat exigeait des tokens du tokenizer exact.

La baseline et le smoke restent des témoins techniques. Aucun score de qualité n’est considéré probant avant les jeux indépendants de 100 puis 300 questions. Voir `docs/audit-reconciliation.md`.

## Exécution locale

### V1 web locale

Cette première interface permet d'importer un texte puis de poser une question avec
filtrage ACL, citation et abstention. Elle reste volontairement limitée : stockage
en mémoire (perdu au redémarrage), recherche lexicale et contexte utilisateur saisi
manuellement. Elle ne doit pas être exposée sur Internet et ne constitue pas encore
une authentification de production.

```bash
.venv-audit/bin/python scripts/serve_v1.py
```

Ouvrir ensuite `http://127.0.0.1:8080`. Le serveur écoute uniquement sur l'interface
locale par défaut. Les options sont visibles avec :

```bash
.venv-audit/bin/python scripts/serve_v1.py --help
```

### Backend de stockage (mémoire ou Qdrant)

Par défaut, la V1 stocke les segments en mémoire (perdus au redémarrage). Pour
activer la persistance Qdrant, définir `RAG_QDRANT_URL` (et éventuellement
`RAG_QDRANT_COLLECTION`, défaut `hermes_chunks_v1`) avant de lancer le serveur.
La collection et ses index de payload doivent exister au préalable
(voir `qdrant/payload-indexes.json`).

Pour provisionner explicitement la collection par défaut BGE-M3 (vecteur dense
de dimension 1 024) sur un Qdrant local :

```bash
.venv-audit/bin/python scripts/provision_qdrant.py
```

Les paramètres peuvent être modifiés avec `--url`, `--collection`,
`--vector-size` et `--index-spec`. La commande est idempotente : une seconde
exécution sur une collection conforme ne crée rien. Une collection existante
avec une dimension, une distance ou un index incompatible est refusée avant
toute création d'index ; aucune infrastructure existante n'est corrigée ou
écrasée silencieusement.

Au démarrage, le service lit les métadonnées de la collection et refuse de
démarrer si la collection est absente, si le vecteur nommé `dense` manque, si
un index déclaré dans `qdrant/payload-indexes.json` manque ou possède un type
différent, ou si `tenant_id` n'est pas un index `keyword` déclaré avec
`is_tenant: true`. Ce contrôle est fail-closed et ne crée ni ne modifie
l'infrastructure Qdrant.

Le module n'impose aucun modèle d'embedding : `scripts/serve_v1.py` ne fournit
pas d'`embed`. Deux options explicites pour la persistance Qdrant :

- passer une fonction `embed` en code via `app_factory.build_service(env, embed=...)` ;
- ou définir `RAG_EMBED_LOCK` vers un lock de checkpoint épinglé
  (`manifests/locks/bge-m3.lock.json`). Le factory construit alors un
  `LockedBgeM3Embedder` verrouillé sur `BAAI/bge-m3` à la révision auditée. Le
  modèle est chargé paresseusement au premier appel (import de `FlagEmbedding`
  différé) ; l'installation GPU se fait via `pip install -e '.[gpu]'`. Démarrer
  avec `RAG_QDRANT_URL` sans l'une de ces deux options est refusé explicitement.

La barrière ACL pré-filtrage/post-filtrage est déjà prouvée contre un vrai
Qdrant 1.19.0.

Le parcours système HTTP → service → Qdrant est également testé contre ce
serveur réel : un document importé reste interrogeable avec sa citation après
reconstruction complète du service. Le propriétaire persisté est contrôlé
avant tout remplacement ; après redémarrage, un autre utilisateur du même
tenant ne peut pas reprendre le même `document_id`. Ce test utilise un vecteur
déterministe de quatre dimensions et prouve le câblage, la persistance et la
barrière de propriété, pas la qualité sémantique du modèle d'embedding.

Cette garantie suppose l'unique writer fourni par `scripts/serve_v1.py`
(serveur WSGI mono-processus et séquentiel). Le contrôle du propriétaire et
l'écriture Qdrant ne constituent pas une transaction atomique : plusieurs
processus ou writers concurrents sur la même collection ne sont pas supportés
par cette V1. Un déploiement multi-writer devra ajouter un registre de
propriété avec création conditionnelle ou un verrou distribué avant d'être
considéré sûr.


### Tests

La suite complète utilise `hypothesis`, verrouillé dans
`requirements-audit.lock.txt`. Sur un nouveau clone, préparer l’environnement
d’audit avec :

```bash
python -m venv .venv-audit
.venv-audit/bin/python -m pip install --require-hashes -r requirements-audit.lock.txt
```

Exécuter ensuite tous les tests :

```bash
.venv-audit/bin/python -m unittest discover -s tests -v
```

Reconstruction du corpus public :

```bash
PYTHONPATH=. python scripts/build_public_corpus.py \
  --docs-root data/sources/hermes-agent/website/docs \
  --commit b682a98ab8cb30c4f0561021e0ff9f41e5156526 \
  --output data/generated/hermes_public_documents.jsonl
```

Baseline retrieval :

```bash
PYTHONPATH=. python scripts/run_baseline.py \
  --documents data/generated/hermes_public_documents.jsonl \
  --documents data/fixtures/private_and_synthetic_documents.jsonl \
  --questions data/fixtures/smoke_questions.jsonl \
  --k 10 --minimum-score 0.5
```

Après démarrage de Qdrant 1.19.0 sur `127.0.0.1:6333`, chargement et probes ACL :

```bash
PYTHONPATH=. python scripts/qdrant_smoke.py \
  --url http://127.0.0.1:6333 \
  --collection hermes_chunks_smoke_v1 \
  --documents data/generated/hermes_public_documents.jsonl \
  --documents data/fixtures/private_and_synthetic_documents.jsonl
```

Les vecteurs de ce script sont déterministes et destinés exclusivement aux tests de stockage et d’ACL. Ils ne constituent pas des embeddings et ne mesurent aucune qualité sémantique.

## Architecture du MVP

```text
Markdown/MDX officiel + fixtures privées/synthétiques
  -> documents versionnés
  -> chunks <= 420 mots (approximation provisoire)
  -> payload ACL complet
  -> BGE-M3 dense+sparse (prochaine étape GPU)
  -> Qdrant avec filtre ACL pré-scoring
  -> BGE-reranker-v2-m3 (entrée tokenisée <= 512)
  -> modèle générateur via API OpenAI-compatible
  -> citations ou abstention
  -> harnais d’évaluation
```

La limite actuelle de 420 est une approximation par mots, pas une garantie tokenizer. Avant le reranking, le code devra mesurer `requête + passage + tokens spéciaux` avec le tokenizer exact et refuser toute troncature silencieuse.

## Inférence : deux livraisons distinctes

### Poste isolé

- RTX 4090 24 Gio comme classe de référence initiale ;
- Qwen2.5-14B-Instruct GGUF Q4_K_M ;
- llama.cpp v0.4.0 ;
- un utilisateur dans le manifeste initial.

Fichiers :

- `manifests/models/qwen2.5-14b-q4km-llamacpp-rtx4090.json`
- `inference/llama_cpp/launch.sh`

### Serveur partagé

- RTX 6000 Ada 48 Gio comme classe de référence initiale ;
- Qwen2.5-14B-Instruct BF16 officiel ;
- vLLM 0.29.0 ;
- quatre séquences dans le manifeste initial.

Fichiers :

- `manifests/models/qwen2.5-14b-bf16-vllm-rtx6000ada.json`
- `manifests/locks/qwen2.5-14b-bf16.lock.json`
- `inference/vllm/launch.sh`

Ces deux profils sont `candidate_unbenchmarked`. Aucune capacité, concurrence ou latence n’est garantie avant mesure sur la classe de matériel indiquée.

## Job GPU BGE exécuté

Le manifeste `manifests/gpu/bge-m3-smoke-rtx4090.json` verrouille :

- `BAAI/bge-m3` au commit `5617a9f61b028005a4858fdac845db406aefb181`, licence MIT ;
- `BAAI/bge-reranker-v2-m3` au commit `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`, licence Apache-2.0 ;
- 4,262 Gio d’artefacts listés par empreinte ;
- dense 1 024 dimensions, dense+sparse activés, ColBERT désactivé pour le premier smoke test ;
- embeddings limités à 1 024 tokens ;
- reranker limité à 512 tokens avec politique `reject`, jamais `truncate` ;
- cible matérielle RTX 4090 24 Gio.

Validation locale sans téléchargement ni dépense :

```bash
PYTHONPATH=. python scripts/plan_bge_gpu_job.py
```

Exécution GPU reproductible :

```bash
python -m pip install -e '.[gpu]'
PYTHONPATH=. python scripts/run_bge_gpu_smoke.py
```

Rapport historique corrigé après audit : `data/results/bge_m3_gpu_smoke_report.json` (SHA-256 actuel `c82589b1cb2b6da5f7a374f76846d87b068406c82088cb3bea5270e00193dbf2`, SHA-256 original conservé dans le rapport). Les artefacts principaux des deux checkpoints ont été vérifiés par taille et SHA-256 lorsqu’une empreinte LFS était présente dans les locks.

Ce smoke valide l’exécution matérielle et le câblage, pas la qualité statistique : il ne contient que 10 questions. Il révèle surtout que la limite actuelle de 420 mots produit des passages trop longs pour le budget exact de 512 tokens du reranker.

## Règles non négociables

1. Poids et code sous licence OSI, vérifiés pour chaque checkpoint.
2. Pas de transposition d’un résultat BF16/A100 vers une livraison Q4/RTX grand public.
3. Un résultat est identifié par checkpoint, révision, artefact, quantification, moteur, version, GPU, contexte et concurrence.
4. Toute requête retrieval possède un contexte d’autorisation ; absence de contexte = erreur.
5. `tenant_id` doit être indexé dans Qdrant et déclaré tenant lorsque la version le permet.
6. Une fuite inter-tenant invalide la configuration, indépendamment des scores moyens.
7. La baseline sans retrieval est obligatoire dans la campagne générative.
8. Le jeu final comporte au moins 300 questions et une revue humaine d’au moins 20 %.

Voir `docs/acceptance-criteria.md`.

## Prochain jalon

1. Remplacer le chunking provisoire à 420 mots par un chunking piloté par le tokenizer exact, afin que `question + passage + tokens spéciaux <= 512`. **Fait** : `chunk_document_tokens` (question 96 / passage 384 / overlap 64 / réserve 32), avec test rouge d’abord.
2. Réexécuter le smoke GPU et exiger zéro paire rejetée avant de retenir le reranker.
3. Persister les sorties dense+sparse réelles dans Qdrant tout en conservant les mêmes filtres ACL pré-scoring. **Barrière ACL Qdrant réelle déjà validée** (`docs/smoke-gpu-runbook.md`, porte 2).
4. Étendre et geler le corpus à 300 questions avant comparaison des modèles, en passant d’abord par un jeu intermédiaire de 100 questions dont au moins 30 écrites à la main.
5. Ajouter la baseline générative sans retrieval et la revue humaine de 20 %.

La procédure complète et les portes de sécurité sont dans `docs/smoke-gpu-runbook.md` ; la réconciliation des audits dans `docs/audit-reconciliation.md`.
