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
filtrage ACL, citation et abstention. Par défaut, elle utilise un stockage en
mémoire (perdu au redémarrage) et une réponse extractive lexicale. Qdrant et un
générateur OpenAI-compatible sont activables explicitement. Le contexte
utilisateur reste saisi manuellement : cette V1 ne doit pas être exposée sur
Internet et ne constitue pas encore une authentification de production.

```bash
.venv-audit/bin/python scripts/serve_v1.py
```

Ouvrir ensuite `http://127.0.0.1:8080`. Le serveur écoute uniquement sur l'interface
locale par défaut. Les options sont visibles avec :

```bash
.venv-audit/bin/python scripts/serve_v1.py --help
```

`--port 0` demande au système un port éphémère libre ; le serveur affiche l'URL
réellement allouée. `SIGTERM` et `Ctrl-C` déclenchent un arrêt propre (message
`Arrêt du serveur.`, code de sortie 0). Un test d'intégration lance le vrai
processus HTTP sur un port éphémère, exécute import → question → citation, vérifie
les en-têtes de sécurité puis confirme l'arrêt propre.

**Durcissement HTTP.** L'API n'accepte que les hôtes loopback (`localhost`,
`127.0.0.1`, `[::1]`), exige `Content-Type: application/json` sur les routes
mutantes, plafonne le corps à 1 Mo et mappe chaque erreur (400/403/404/405/413/
415/502) sans fuite de pile. Toute réponse (HTML, JS, JSON) porte les en-têtes de
sécurité : `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`,
`Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store` et une
**Content-Security-Policy stricte** (`default-src 'none'; script-src 'self'; …;
frame-ancestors 'none'`). Le JavaScript de l'interface est servi depuis `/app.js`
(plus aucun `<script>` inline), de sorte que la CSP interdit toute exécution de
script inline ou `eval`. Seul `style-src 'unsafe-inline'` reste toléré pour la
feuille de style intégrée (vecteur sans exécution de code).

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

### Génération optionnelle OpenAI-compatible

Sans configuration supplémentaire, la V1 conserve son mode extractif local :
elle retourne le meilleur segment autorisé. Un générateur OpenAI-compatible peut
être activé explicitement, indépendamment du backend mémoire ou Qdrant :

```bash
export RAG_GENERATOR_BASE_URL=http://127.0.0.1:8000/v1
export RAG_GENERATOR_MODEL=qwen-local
.venv-audit/bin/python scripts/serve_v1.py
```

Pour un service distant, l'URL doit utiliser HTTPS et la clé peut être fournie
avec `RAG_GENERATOR_API_KEY`. HTTP n'est accepté que pour `localhost`,
`127.0.0.1` ou `::1`. Une configuration partielle (URL sans modèle ou modèle
sans URL) bloque le démarrage.

Le générateur reçoit uniquement la question et les segments déjà autorisés par
la barrière ACL. Le prompt traite les documents comme des données non fiables,
interdit de suivre leurs instructions et exige des marqueurs `[S1]`, `[S2]`,
etc. Une réponse non vide sans citation valide, une réponse fournisseur
malformée ou une panne réseau échoue explicitement en HTTP 502 ; elle n'est pas
comptée comme une abstention. Une abstention explicite masque les citations
inutiles. Le fournisseur reçoit une demande plafonnée à 512 tokens ; le client
refuse en plus toute réponse HTTP dépassant 1 000 000 octets et tout contenu de
réponse dépassant 16 384 caractères.

### Récupération multi-source (top-k)

Par défaut, la V1 ne récupère qu'un seul segment (`RAG_TOP_K=1`). Pour fonder
une réponse sur plusieurs segments autorisés, augmenter la valeur :

```bash
export RAG_TOP_K=5
```

La valeur doit être un entier positif ; toute autre valeur bloque le démarrage.
Le service récupère jusqu'à `RAG_TOP_K` segments dépassant le seuil de score,
puis les transmet au générateur numérotés `[S1]`, `[S2]`, etc. dans l'ordre de
pertinence. Seuls les segments réellement cités par un marqueur valide dans la
réponse deviennent des citations retournées ; les marqueurs sont dédupliqués et
les citations suivent l'ordre de première citation. En mode extractif (sans
générateur), seul le meilleur segment est renvoyé, quel que soit `RAG_TOP_K`.

### Reranking (cross-encodeur optionnel)

La récupération vectorielle est rapide mais approximative. Un reranker
cross-encodeur (BGE-reranker-v2-m3) relit chaque paire `question + passage`
ensemble et produit un score de pertinence plus fiable. Deux paramètres
séparent la récupération de la sortie :

- `RAG_RETRIEVAL_K` : nombre de candidats récupérés avant reranking (ex. 20) ;
- `RAG_TOP_K` : nombre de segments conservés après reranking et envoyés au
  générateur (ex. 5).

`RAG_RETRIEVAL_K` doit être un entier positif et supérieur ou égal à
`RAG_TOP_K` ; sinon le démarrage est bloqué. Sans reranker injecté, seul
`RAG_TOP_K` est récupéré (pas d'élargissement) et l'ordre de récupération est
conservé.

Le reranker est injecté explicitement en code via
`RagService(reranker=...)` ; ce module ne choisit ni ne télécharge aucun
modèle implicitement. Le pont fourni est
`rag_hermes.reranker.BudgetedCrossEncoderReranker`, qui reçoit un modèle et le
tokenizer exact. Chaque paire est vérifiée contre le budget de 512 tokens avec
le tokenizer réel AVANT tout scoring : une paire hors budget est rejetée (jamais
tronquée) et le modèle n'est alors jamais appelé. Le reranker ne fait que
réordonner des segments déjà autorisés par la barrière ACL ; il n'élargit
jamais l'autorisation. L'exécution du vrai modèle BGE nécessite
`pip install -e '.[gpu]'` et une classe de GPU adaptée (voir le smoke GPU) ;
les tests locaux utilisent un cross-encodeur déterministe factice.

Attention : avec un fournisseur distant, la question et les extraits autorisés
quittent la machine. Le coût et la politique de conservation dépendent de ce
fournisseur. Aucune requête externe n'est effectuée tant que ces variables ne
sont pas définies.

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

### Jeux d’évaluation : deux pistes strictement séparées

L’évaluation distingue deux pistes qui ne se mélangent jamais. La séparation est
imposée par le schéma (`question_provenance`) et par `is_quality_eligible`, de
sorte qu’une question générée depuis le corpus ne peut jamais gonfler un score
de qualité humaine (non-circularité).

1. **Piste humaine — `data/benchmark/dataset-v2.jsonl`.** Questions écrites par un
   humain sans voir le corpus (`human_task_without_corpus_view`) ou questions
   réelles anonymisées (`anonymized_real_user_question`), annotées au **passage**
   (span exact + `passage_sha256`), avec paires EN/FR. C’est la seule piste
   éligible comme preuve de qualité. Le gate `scripts/validate_dataset_v2.py`
   n’est `READY` qu’avec 100 cas EN, 40 paires FR complètes et **toutes** les
   références revues (`validated`/`arbitrated`). Objectif README : au moins 30 des
   questions écrites à la main. Cette piste est aujourd’hui **vide** et attend les
   annotations humaines (voir `scripts/annotate_eval_case.py`). Le rapport du gate
   expose un bloc `remaining` actionnable (`en2en_cases`, `fr_pairs`, `to_review`)
   indiquant exactement ce qu’il reste à produire pour atteindre `READY`, ainsi
   qu’un booléen `targets_met`.

2. **Piste synthétique — `data/benchmark/dataset-synthetic.jsonl`.** Migration du
   jeu généré `dataset-v1.jsonl` (100 questions) vers le schéma canonique via
   `scripts/migrate_v1_to_synthetic.py`. Provenance honnête
   `synthetic_generated_from_corpus` (**jamais** quality-eligible), relevance au
   **document entier** (span `start=0..len(content)`, pas un passage précis),
   `reference_status = pending`. État vérifié : 100 cas valides (0 rejet par le
   validateur strict), 80 répondables + 20 abstentions, 0 quality-eligible, hashes
   de span conformes au corpus canonique, migration déterministe. Cette piste sert
   uniquement de témoin technique de bout en bout (recall@k au niveau document) ;
   elle ne mesure aucune qualité sémantique probante.

```bash
# Migrer/rafraîchir la piste synthétique (déterministe)
.venv-audit/bin/python scripts/migrate_v1_to_synthetic.py
```

#### Rapport-témoin de la piste synthétique

`scripts/synthetic_eval_report.py` fait passer les 100 cas synthétiques par le
vrai chemin `RagService` sur le corpus public complet (461 documents) et écrit
`data/results/synthetic-eval-report.json`. C’est un **témoin technique** de la
récupération lexicale au niveau document, jamais une preuve de qualité (questions
générées, pertinence document entier, récupérateur lexical sans embeddings).

```bash
.venv-audit/bin/python scripts/synthetic_eval_report.py --k 5
```

Résultat vérifié (baseline lexicale en mémoire, `minimum_score=0.05`, `k=5`, 461
documents, 100 cas) : `recall@5 = 0,30`, `MRR = 0,20`, `citation_precision = 0,12`,
`leak_count = 0`, `security_gate_passed = true`. L’**abstention est nulle**
(`abstention_precision = abstention_recall = 0,0`) : à seuil bas le récupérateur
lexical trouve toujours un chunk au-dessus du seuil, donc il ne s’abstient jamais
sur les 20 cas sans réponse. Ce n’est pas un défaut de code mais une propriété
mesurée de la baseline lexicale ; l’abstention n’apparaît qu’à seuil élevé
(par ex. `minimum_score=0.6`) et reste faible. Ces chiffres sont un plancher
attendu ; la piste humaine annotée au passage et un récupérateur dense/reranké
sont nécessaires pour toute affirmation de qualité.

### Baseline générative sans retrieval (closed-book)

La campagne générative exige une baseline **sans retrieval** (règle non
négociable 7) : ce que le modèle répond DE MÉMOIRE, sans corpus, pour prouver
ensuite que le RAG apporte un gain. `rag_hermes/closed_book.py` fournit un
`ClosedBookGenerator` distinct du générateur RAG :

- il n'envoie QUE la question (jamais de champ `sources`) ;
- il n'exige AUCUNE citation `[Sn]` (il n'y a rien à citer) ;
- il est instruit d'abstenir honnêtement (`Je ne connais pas la réponse.`)
  plutôt que d'inventer ;
- il partage le durcissement réseau du générateur RAG via `validate_endpoint`
  (HTTPS partout ou HTTP loopback uniquement, pas d'identifiants dans l'URL,
  redirections coupées, réponse plafonnée), et son transport est injectable
  (tests hors-ligne, aucun appel réseau).

`rag_hermes/closed_book_eval.py` mesure hors-ligne le **seul** axe scorable sans
sources : l'abstention (précision/rappel entre `should_abstain` attendu et
l'abstention réelle). Les réponses concrètes sont exposées par `case_id`
(`answered_case_ids`) pour tirer l'échantillon de **revue humaine ≥20 %** — seule
une revue humaine juge la justesse d'une réponse closed-book, qu'aucune métrique
hors-ligne ne peut établir. Cette revue humaine reste à réaliser.

Le générateur baseline s'active par variables d'environnement, sur le même modèle
que le générateur RAG : `RAG_BASELINE_BASE_URL` et `RAG_BASELINE_MODEL` sont
exigés ensemble, `RAG_BASELINE_API_KEY` est optionnel. Le même durcissement réseau
s'applique (HTTPS partout ou HTTP loopback uniquement, sans identifiants). La
fabrique `rag_hermes.app_factory.build_baseline_generator(env=…)` renvoie un
`ClosedBookGenerator` ou `None` si rien n'est configuré. La baseline est une
campagne SÉPARÉE (sans retrieval) : elle n'est jamais injectée dans le
`RagService`, les appelants la pilotent directement (voir le comparateur).

### Comparaison RAG vs closed-book (harnais hors-ligne)

`rag_hermes/campaign_compare.py` contraste les deux campagnes sur le même jeu de
questions. Chaque campagne abstient avec SA propre sentinelle (RAG et closed-book
en ont deux distinctes), et le harnais mesure l'axe **abstention** des deux côtés,
puis tire un échantillon de revue humaine déterministe (fraction paramétrable,
≥20 %) appariant, par question, la réponse RAG et la réponse closed-book.

`scripts/compare_campaigns.py` exécute cette comparaison sur la piste synthétique
et écrit `data/results/campaign-comparison.json` (métriques d'abstention) et
`data/results/campaign-review-sample.jsonl` (les paires à juger, avec des champs
`human_verdict` vides à remplir).

```bash
.venv-audit/bin/python scripts/compare_campaigns.py --review-fraction 0.2 --seed 1
```

**Limite hors-ligne assumée** : sans endpoint LLM câblé, le côté RAG utilise la
réponse extractive (meilleur chunk autorisé) et le côté closed-book s'abstient par
défaut. Résultat vérifié (100 cas, seed 1) : `rag_abstention_recall = 0,0`
(l'extractif à seuil bas ne s'abstient jamais), `closed_book_abstention_recall =
1,0` mais `precision = 0,2` (le stub s'abstient partout, y compris à tort sur les
répondables). Ces chiffres ne mesurent PAS la justesse des réponses : seule la
**revue humaine ≥20 %** (le fichier de paires produit) le fait. Quand un endpoint
réel sera fourni, on remplace les deux callables injectés par les générateurs
réseau (RAG et baseline).

#### Agrégation des verdicts humains

Une fois le fichier `campaign-review-sample.jsonl` rempli (chaque
`human_verdict.rag_correct` / `closed_book_correct` mis à `true`/`false`),
`scripts/aggregate_review.py` calcule la **justesse** de chaque campagne — la
seule mesure de correction d'une réponse, qu'aucune métrique hors-ligne ne peut
produire — et écrit `data/results/campaign-review-aggregate.json`.

```bash
.venv-audit/bin/python scripts/aggregate_review.py            # fail-closed : refuse si une paire reste non revue
.venv-audit/bin/python scripts/aggregate_review.py --allow-partial  # instantané sur le sous-ensemble revu
```

Le rapport donne `rag_accuracy`, `closed_book_accuracy` (dénominateur = nombre de
paires revues), ainsi que `rag_better_count` / `closed_book_better_count` (sur
combien de cas une campagne est correcte quand l'autre ne l'est pas). Par défaut,
l'agrégation est **fail-closed** : tant qu'une paire porte un verdict `null`, elle
refuse de publier une justesse partielle.

#### Rapport consolidé de campagne

`scripts/consolidate_campaign.py` réunit les rapports de retrieval synthétique,
de comparaison d'abstention et de justesse humaine dans
`data/results/campaign-summary.json`, sans mélanger leurs niveaux de preuve :

```bash
.venv-audit/bin/python scripts/consolidate_campaign.py
```

Les sections restent distinctes (`retrieval_technical`,
`abstention_comparison`, `human_correctness`). Le consolidateur vérifie la
cohérence des nombres de cas et de la taille de l'échantillon humain. Codes de
sortie : `0` si la campagne synthétique et sa revue sont complètes, `2` si la
revue humaine est absente/incomplète, `1` sur incohérence ou échec du gate de
sécurité. Même complet, ce rapport conserve `quality_evidence=false` : une piste
synthétique ne devient jamais une preuve de qualité humaine.

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
