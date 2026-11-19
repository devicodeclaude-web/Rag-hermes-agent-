# Triage des 3 audits externes (révision auditée `1bf4865`)

Date du triage : 2026-11-19. Révision vérifiée localement : `1bf48653bbeef686b1dfe5372fe2381acc2b2a1d`
(identique à celle citée par les trois auditeurs). Aucune correction appliquée à ce stade : ce document
ne fait que confronter chaque affirmation au code réel.

Méthode : lecture du code à HEAD + exécution réelle de la suite CPU
(`PYTHONPATH=. python -m unittest discover -s tests` → **937 tests, OK, skipped=34** sans Qdrant local)
+ lecture des reçus/manifests versionnés. Pas de pentest, pas de run GPU.

Sources auditées :
- **Audit A** — revue globale notée (8,2/10 harnais, 4,5/10 production).
- **Audit B** — auditeur ayant réellement cloné et exécuté (937 tests, gitleaks 249 commits, 4 constats + PoC).
- **Audit C** — audit statique structuré P0/P1/P2 (SEC-01/02/03, CI-01, QUAL-01, ARCH-01, CONS-01, CODE-01, OPS-01, SUP-01).

## 1. Constats CONFIRMÉS par le code

| ID | Constat | Preuve locale | Gravité retenue |
|----|---------|---------------|-----------------|
| CI-01 | La suite stricte n'est pas un contrôle de PR | `.github/workflows/lock-install-x86_64-py312.yml` : triggers = `workflow_dispatch` + `push` avec `paths` = `requirements-*.lock.txt`, `scripts/verify_lock_install.py`, `scripts/run_ci_strict.py`, `scripts/capture_evidence.py`, `tests/**`, le workflow lui-même. **Pas de `pull_request`, pas de `rag_hermes/**`**. `dataset-qa.yml` = chemins dataset uniquement. `serverless-image.yml` = manuel. | P0 gouvernance |
| SEC-01 | Autorité ACL canonique non branchée sur la V1 | `app_factory.py:125` construit `QdrantChunkRepository` et le passe à `RagService` (l.132). `CanonicalAclSearch` n'apparaît que dans `g1_wiring.py:69` et `g1_hybrid_candidates.py:28`. Nuance : `service.py:73` sait déjà accepter un `CanonicalAclSearch` injecté → branchement possible sans refonte. | P0 avant tout multi-tenant déployé (risque de conception, aucune fuite observée) |
| SEC-02 | Remplacement non atomique | `qdrant_repository.py:_replace_document_locked` : upsert conditionnel + readback (l.566-590) **puis** `delete_points` des anciens IDs (l.604). Verrou = `fcntl.flock` local, et `search()` ne le prend pas → fenêtre où l'ancienne génération (donc l'ancienne ACL) reste lisible. | P1-P0 selon déploiement |
| ARCH-01 | Chunking du service ≠ chunking évalué | `service.py:9,98` → `chunk_document` (mots, défaut 420/40 dans `ingestion.py:26-27`). `chunk_document_tokens` (384/64, `ingestion.py:75-80`) n'est utilisé que par les parcours GPU/éval. **Le README (l.453 « désormais piloté par le tokenizer exact », l.528 « **Fait** ») est donc trompeur pour le chemin V1.** | P1 + correction de doc |
| B-3b | Erreur serveur rendue en 400 | `reranker_budget.py:4` : `class RerankerBudgetExceeded(ValueError)`. `http_api.py:252` attrape `(KeyError, TypeError, ValueError, JSONDecodeError)` → `400 invalid_request` pour un dépassement de budget côté serveur. | P1 |
| CODE-01 | Scores de rerank non finis acceptés en V1 | `service.py:176` trie sur `float(scores[index])` sans `math.isfinite`. `g1_reranking.py:134` le vérifie. Asymétrie réelle. | P1 |
| B-2 | Tenant `"public"` non réservé | Aucune occurrence de `"public"` dans `auth.py` (`_context_from_entry`, l.85-106, accepte n'importe quel `tenant_id`). `acl.py:55` : `is_global_public = chunk.tenant_id == "public" and chunk.visibility == "public"` ; `qdrant_filter.py:44-45` ouvre la même branche. Un principal `tenant_id="public"` écrit donc dans le corpus lu par tous les tenants. **Nuance : exige un fichier de principaux fabriqué par l'admin (mauvaise configuration), pas une escalade à distance.** | P1 (fail-closed cheap) |
| SEC-03 | Transport/privilèges Qdrant | `qdrant_rest.py:15-27` : `QdrantRestClient(base_url, timeout)`, aucun en-tête `api-key`, aucune validation de schéma HTTPS/loopback, lecture + upsert + delete dans la même classe. | P1 |
| B-faible | Erreurs imprévues → 500 nu | `http_api.py` n'a aucun `except Exception` (excepts = `AuthenticationError`, `DocumentWriteLockTimeout`, `GenerationError`, `PermissionError`, `(KeyError, TypeError, ValueError, JSONDecodeError)`). Un `RuntimeError("Qdrant unavailable")` remonte à wsgiref → 500 générique **sans** `_SECURITY_HEADERS`. Le README annonce un mappage complet. | P2 + correction de doc |
| OPS-01 | Serveur de dev | `scripts/serve_v1.py:9,82` : `wsgiref.simple_server.make_server`, mono-requête, sans timeout → un `Content-Length` annoncé sans corps bloque le serveur. | P2 (assumé hors scope prod) |
| SUP-01 | Actions CI non épinglées | `dataset-qa.yml` et `lock-install-*.yml` : `actions/checkout@v4`, `actions/setup-python@v5` ; seul `serverless-image.yml` épingle par SHA. | P2 |
| B-faible | Fallback gitleaks | `scripts/run_ci_strict.py:28` : `shutil.which("gitleaks") or "/tmp/gitleaks"`. | P2 |
| B-faible | `numpy` absent du lock d'audit | `requirements-audit.lock.txt` = `attrs`, `hypothesis`, `sortedcontainers` seulement. `tests/test_g1_canonical_reranking.py:124,134` importe `numpy` dans des méthodes de test → 2-3 tests en erreur sur clone neuf suivant le README (l.215). | P2 |
| B-faible | Ports par défaut qui se marchent dessus | `inference/llama_cpp/launch.sh:15` `--port ${PORT:-8080}` = défaut de `scripts/serve_v1.py:63`. Aucun `--api-key` dans les deux `launch.sh` (vLLM écoute 8000). | P2 |
| B-info / QUAL-01 | Contrôle de citation purement structurel | `generator.py:143-146` : regex `\[S(\d+)\]` + bornes des indices. Aucun contrôle de support sémantique. | P1 pour la porte qualité |
| QUAL-01 | Métriques non mesurées exposées en `0.0` | `data/results/bge_m3_human_154_execution_receipt.json` : `metrics_after_rerank.citation_precision = 0.0`, `citation_support_precision = 0.0` alors que `execution.qdrant_status = "not_exercised_in_component_runner"`. Un non-mesuré rendu `0.0` est indiscernable d'un échec mesuré → défaut de schéma de reçu. | P1 honnêteté |

### Chiffres cités par les auditeurs — tous exacts
- Reçu 154 cas : `recall_at_k` après rerank **0.8524590**, `mrr` **0.6815574**, abstention holdout **0.80** (16/20), `leak_count` **0**, `quality_gate_passed` **false**. ✔
- `benchmark-v2.lock.json` : 300 cas actifs, `human_independent_review: "NON ATTEINT"`, strates séparées — comptes réels **ACL 11 / contradictions 8 / injections 8**. ✔
- 94 fichiers de tests, 937 tests, 34 tests d'intégration Qdrant (ici *skipped* faute de Qdrant local), 326 commits. ✔
- 24 scripts jetables (`apply_batch*`, `cb_probe*`, `cb_verify*`) sur 83 ; `data/` = 18 Mo (l'audit dit 23 Mo : ordre de grandeur). ✔≈

## 2. Affirmations INEXACTES ou PÉRIMÉES

1. **Audit A, section 2** : « chunking désormais tokenizer-exact » listé comme *force*. **Faux pour le chemin service V1** — l'auditeur a cru le README. Les audits B et C ont raison contre A.
2. **Audit A, section 4** : « les smokes et baselines restent sur de très petits jeux (10 questions) ». **Périmé** : reçu réel sur 154 cas, jeu actif gelé à 300.
3. **Audit A, reco 1** : « finaliser et geler un jeu de 100 puis 300 questions ». **Déjà fait** (gel du 2026-11-18). Ce qui manque est la **revue humaine indépendante**, déjà tracée `NON ATTEINT` dans le lock, et figée comme structurellement inclosable (aucun second relecteur humain disponible — décision « option 1 », cf. skill `references/deficit2-and-corpus-count.md`).
4. **Audit A, reco 3** : « instrumenter `truncated_pairs` réel ». Mal nommé : le code **rejette** les paires hors budget (`RerankerBudgetExceeded`), il ne tronque pas. La métrique pertinente est `rejected_pairs`, déjà présente dans le smoke GPU.
5. **Audit A, verdict « 0 fuite » comme force de sécurité** : le reçu dit lui-même `qdrant_status = not_exercised_in_component_runner` → le `leak_count = 0` de ce run ne couvre pas Qdrant persistant. L'audit C le dit correctement, A le survend légèrement.
6. **Audit B, « gitleaks sur 249 commits »** : le dépôt a 326 commits ; chiffre partiel (périmètre de scan), pas une contradiction.
7. **Audit B, « 3 tests en erreur » sans numpy** : les imports `numpy` sont locaux à 2 méthodes de test → 2-3 tests, à ±1. Détail.
8. **Audit C, CI-01** : honnête sur sa limite (protection de branche = 403, non certifiée). À vérifier côté GitHub avant de conclure « merge non protégé ».

## 3. Ce sur quoi les trois audits convergent (donc le vrai backlog)

1. CI non contraignante sur `rag_hermes/**` et absente des PR. *(A implicite, B-1, C CI-01)*
2. Autorité ACL canonique non branchée sur le chemin V1 standard. *(A implicite, C SEC-01)*
3. Divergence chunking service ↔ pipeline évalué, et README trompeur. *(B-3, C ARCH-01)*
4. Durcissement Qdrant (auth/TLS/séparation des privilèges). *(A, B-4, C SEC-03)*
5. Porte qualité non franchie : `quality_gate_passed=false`, revue humaine indépendante non atteinte, citations non évaluées sémantiquement. *(A, C QUAL-01)*

## 4. Plan de correction proposé (non exécuté)

- **Lot 0 — CI non contournable** : trigger `pull_request` + `push:main` sans filtre de chemins sur la suite stricte, épinglage des actions par SHA, suppression du fallback `/tmp/gitleaks`, `numpy` ajouté au lock d'audit. Aucun changement fonctionnel.
- **Lot 1 — Corrections fail-closed bon marché** : `tenant_id == "public"` refusé dans `_context_from_entry` (+ test rouge) ; `math.isfinite` partagé V1/G1 ; `RerankerBudgetExceeded` mappé en `502 backend_error` au lieu de `400` ; `except Exception` → 500 JSON avec en-têtes de sécurité.
- **Lot 2 — Identité d'exécution** : `service.import_document` sur `chunk_document_tokens` (384/64) + profil de pipeline épinglé ; README corrigé (la déviation n'était corrigée que côté GPU).
- **Lot 3 — Transport/privilèges Qdrant** : validation d'URL (`validate_endpoint` déjà existant côté générateur), support `api-key`, clients lecture/écriture/audit distincts.
- **Lot 4 — Honnêteté des reçus** : non-mesuré = `null` et non `0.0` dans le schéma de reçu ; mention explicite « harnais de preuve, pas produit » en tête de README.
- **Lot 5 — Atomicité/concurrence (SEC-02, CONS-01)** : génération active + CAS, monotonie `doc_version`/`acl_version`. Chantier lourd, à ne lancer que si un déploiement partagé est visé.

### État d'application (mis à jour à chaque lot livré)

- **Lot 0 : APPLIQUÉ** (PR #84, mergée). Premier run du workflow sur une PR observé vert (`lock-install` + `qa`) : le test d'acceptation de CI-01 est passé.
- **Lot 1 : APPLIQUÉ** (cette PR). Détail des écarts par rapport au plan : le garde de finitude est partagé par **trois** chemins et non deux (`rag_hermes/reranker_scores.py` est aussi utilisé par `retrieval.score_authorized_pairs`, le runner de campagne, qui convertissait les scores sans refuser `bool` ni les chaînes), et le tenant réservé est désormais une constante unique `acl.GLOBAL_PUBLIC_TENANT` au lieu d'un littéral répété dans `acl.py` et `qdrant_filter.py`.
- **SEC-01 : APPLIQUÉ** (hors des lots 0-5, qui ne le traitaient pas). `rag_hermes/canonical_registry.py` ajoute l'autorité ACL canonique locale qui manquait au chemin V1 : registre documentaire persisté hors de Qdrant, écriture canonique **avant** l'index, et `build_service` enveloppe désormais le dépôt dans `CanonicalAclSearch` (refus de démarrage si `RAG_QDRANT_URL` est défini sans `RAG_CANONICAL_STORE`, refus d'un `RAG_RETRIEVAL_K` > 128). Conception, comportements observables et limites assumées : `docs/v1-canonical-acl.md`. Deux refus supplémentaires découverts en écrivant la tranche : un `document_id` déjà pris par un autre locataire (l'autorité canonique indexe par `document_id` seul, le service par `(tenant_id, document_id)`) et toute régression de `doc_version`/`acl_version`.
- **Lots 2 à 5 : NON appliqués.** ARCH-01 (chunking du service), SEC-03 (transport/privilèges Qdrant), QUAL-01 (non-mesuré rendu `0.0`) et SEC-02 (remplacement non atomique) restent ouverts tels que décrits en section 1.
