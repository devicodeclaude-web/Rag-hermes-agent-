# Registre d'état réel — Phase 0 (lecture seule)

- Date d'exécution : 2026-10-08 (UTC)
- HEAD audité : `cc041e7a0eff651264f9ed52f8b2ec15daa4a517` (branche `main`)
- Clone local : `/root/work/Rag-hermes-agent-`
- Exécution de cette session : `python3 -m unittest discover -s tests -v`
  → 115 tests, 110 OK, 4 skipped, 1 error (import `hypothesis` manquant).
- Mode : aucune modification de code, aucun commit. Les chiffres non recalculés
  dans cette session sont attribués à un artefact committé daté, sinon « non mesuré ».

Légende statut : PROUVÉ / CONTREDIT / NON PROUVÉ.

---

## Provenance des preuves (à lire en premier)

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| P1 | Les preuves d'audit décrivent le HEAD courant | CONTREDIT | `AUDIT/preuves/audited_commit` = `ad1bc3c…` ; `AUDIT/00-DOSSIER-AUDIT.md` cite `5970956` ; HEAD = `cc041e7` | Trois commits différents. Les preuves committées ne sont PAS au HEAD. |

## A. Corpus

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| A1 | 461 documents au commit figé | PROUVÉ | `data/sources.lock.json` (`document_count: 461`, commit `b682a98…`, repo NousResearch/hermes-agent) | Fichier généré `data/generated/…jsonl` absent du dépôt (non recomputé cette session). |
| A2 | « 461 → 2 945 chunks » | CONTREDIT | `data/results/chunking_ablation_cpu.json` (`corpus_documents: 465`, `old_strategy.chunk_count: 2945`) ; `data/results/qdrant_acl_audit_report.json` (`documents: 465`, `chunks: 2945`) | 2 945 = chunking **mots** (420/40) sur **465** docs (461 publics + 4 fixtures), pas 461. |
| A3 | Nombre de chunks du smoke GPU = 2 945 | CONTREDIT | `data/results/bge_m3_gpu_smoke_report.json` (`corpus.chunks: 7371`, chunking token 384/64) | Le run GPU (tokens exacts) produit **7 371** chunks, pas 2 945. |

## B. Découpage (chunking)

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| B1 | Découpage par mots `str.split()` existe | PROUVÉ | `rag_hermes/ingestion.py:25-33` (`chunk_document`, `content.split()`, `max_tokens=420`/`overlap=40` — nommés « tokens » mais comptent des **mots**) | Trompeur : paramètre `max_tokens` = mots. |
| B2 | Découpage par tokens exacts 384/64 existe | PROUVÉ | `rag_hermes/ingestion.py:70-143` (`chunk_document_tokens`, `offset_mapping`, exige `tokenizer_name`+`revision`) | Tokenizer réel, pas d'approximation. |
| B3 | Chemin réellement exécuté — persistance Qdrant / baseline | PROUVÉ | `benchmark.py:31`, `scripts/qdrant_smoke.py:36`, `tests/test_qdrant_end_to_end_acl.py:44` appellent `chunk_document` (mots) | Les 2 945 chunks Qdrant viennent du chemin **mots**. |
| B4 | Chemin réellement exécuté — embedding/reranking GPU | PROUVÉ | `scripts/run_bge_gpu_smoke.py:112` appelle `chunk_document_tokens` ; tokenizer `BAAI/bge-reranker-v2-m3 @ 953dc6f6…` (`bge_m3_gpu_smoke_report.json` → `chunking.tokenizer/…revision`) | Le smoke GPU utilise le tokenizer **exact**. |

## C. Budget du reranker

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| C1 | Limite 512 — choix du projet | PROUVÉ | `rag_hermes/gpu_job.py:51-52` (« the MVP reranker budget cannot exceed 512 ») | Plafond projet ; borne structurelle `q+p+special ≤ max` à `gpu_job.py:63`. |
| C2 | Limite 512 — imposée par la config du modèle | NON PROUVÉ | — | `config.json` du reranker non ouvert cette session. bge-reranker-v2-m3 (XLM-R) ~512, à confirmer sur l'artefact. |
| C3 | Comptage exact question+passage+tokens spéciaux | PROUVÉ | `rag_hermes/reranker_budget.py:8-15` (`tokenizer(query, passage, add_special_tokens=True, truncation=False)`) ; câblé `rag_hermes/retrieval.py:130` | Comptage exact, pas d'approximation sur ce chemin. |
| C4 | Aucune troncature (politique « reject ») | PROUVÉ | `reranker_budget.py:13` (`truncation=False`) + `:22-25` (lève `RerankerBudgetExceeded`) ; `bge_m3_gpu_smoke_report.json` (`reranker.truncation_policy: reject`) | Lève une erreur typée, jamais tronque en silence. |
| C5 | Ablation CPU faite avec comptage approximatif | PROUVÉ | `data/results/chunking_ablation_cpu.json` (`classification: cpu_mechanism_only_not_exact_token_count`, `question_words_assumed: 8`, `special_tokens_assumed: 4`, ratios mots→tokens 1.2–1.5) | Mécanisme seulement, pas un comptage tokenizer. |

## D. « 190/200 paires rejetées »

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| D1 | 190/200 paires rejetées (quel run / quel code) | NON PROUVÉ | Cité en prose : `data/results/chunking_ablation_cpu.json` → `caveat_vs_gpu_run` (« run GPU historique montrait 190/200 ») + README | Aucun artefact de résultat committé ne contient 190/200. |
| D2 | Rejets dans le run GPU committé | CONTREDIT | `data/results/bge_m3_gpu_smoke_report.json` (`reranker.rejected_pairs: 0`, `maximum_observed_pair_tokens: 396`) | Le run committé (chunking token) rejette **0** paire. Le « 190/200 » concernait un run **mots** non committé ici. |

## E. Chemins ACL

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| E1 | Filtre ACL en mémoire Python | PROUVÉ | `rag_hermes/acl.py:54-72` (`_is_authorized`/`filter_authorized`) ; utilisé `retrieval.py:38` (LexicalRetriever) et smoke GPU (`bge_m3_gpu_smoke_report.json` → `acl_evidence.scope: python_in_memory_prefilter_before_scoring`, `qdrant_exercised: false`) | Le smoke GPU n'exerce PAS Qdrant pour l'ACL. |
| E2 | Filtre du **vrai** Qdrant exercé | PROUVÉ | `rag_hermes/retrieval.py:80-96` (`build_qdrant_filter`) ; `scripts/run_acl_matrix.py:185` (`QdrantRestClient` `127.0.0.1:6333`) ; `data/results/qdrant_acl_audit_report.json` (`server.url: 127.0.0.1:6333`, `points_count: 2945`) | Vecteurs « deterministic-test-only-not-an-embedding » → barrière ACL prouvée, pas la qualité sémantique. |
| E3 | Contrôle d'autorité APRÈS le retrieval | PROUVÉ | `rag_hermes/retrieval.py:64-77` (`postfilter_candidates` → `authority.authorize`) ; autorité `rag_hermes/acl_authority.py:46-56` (`unknown_document`/`stale_acl_version`/`denied`) ; exercé `run_acl_matrix.py:106` | Autorité canonique séparée des payloads Qdrant (« derived indexes »). |
| E4 | Fuite inter-tenant = 0 (chemin Qdrant) | PROUVÉ | `data/results/acl_matrix_qdrant.json` (catégories cross_tenant/clearance/acl_missing : `observed_leaks: 0`, `trials: 100`, `rule_of_three_upper_95pct: 0.03`) ; `qdrant_acl_audit_report.json` (`leak_count: 0`) | 0 observé sur 100 essais/catégorie ; borne haute 95 % = 3 %. Autorité in-memory, pas persistante (`acl_matrix_qdrant.json.authority`). |
| E5 | Deux logiques ACL indépendantes | NON PROUVÉ (risque) | `acl.py:_is_authorized` vs `acl_authority.py:AclPolicy.allows` | Logique dupliquée → risque de dérive ; équivalence formelle non démontrée. |

## F. Protocole d'évaluation

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| F1 | Seuils et exigences documentés | PROUVÉ | `docs/acceptance-criteria.md` (≥300 questions gelées, 20 % revue humaine, recall@10 ≥0,90, validité citations =1,0, support ≥0,95, abstention prec/recall ≥0,90, fuite 0, élargissement ACL 0) ; `docs/evaluation-protocol-v2.md` | Critères écrits, non atteints. |
| F2 | Séparation réglage / évaluation finale | PROUVÉ (documenté) / NON PROUVÉ (exécuté) | `docs/acceptance-criteria.md` ; jeux 100 & 300 inexistants (`bge_m3_gpu_smoke_report.json` → `independent_manual_questions: 0`, `limitations`) | Seul un smoke de 10 questions existe. |
| F3 | État des lots historiques | PROUVÉ | `AUDIT/preuves/LOT-STATUS.json` : lot_1 BLOQUÉ (lock-install exit 1, CUDA non prouvé), lot_2 FERMÉ, lot_3 BLOQUÉ (dataset-v1-validation exit 2, revue humaine requise), lot_4 FERMÉ | — |
| F4 | Exception de budget GPU conforme | NON PROUVÉ | — | Aucun artefact d'exception trouvé ; prévu « Étape 3 » (`AUDIT/00-DOSSIER-AUDIT.md`). |

## G. Comportement actuel de défaillance

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| G1 | Paire hors budget | PROUVÉ | `rag_hermes/retrieval.py:130` → `reranker_budget.py:22` lève `RerankerBudgetExceeded` ; `tests/test_production_retrieval.py:105,135` | Exception qui interrompt le lot ; **pas** de statut typé par requête, pas de dégradation gracieuse. |
| G2 | Aucun candidat rerankable | PROUVÉ | `rag_hermes/retrieval.py:132-133` (retourne `[]`) ; `scripts/run_bge_gpu_smoke.py:241` (`did_abstain = best_score is None or < 0.5`) | « Aucun candidat » → abstention (seuil provisoire 0,5). |
| G3 | Contrat typé ANSWERED/ABSTAIN_NO_EVIDENCE/REFUSED_SECURITY/ERROR_TOKEN_BUDGET/ERROR_BACKEND | CONTREDIT (inexistant) | Code actuel : booléens `should_abstain`/`did_abstain` + `technical_failure` (`rag_hermes/evaluation.py:22-23,58`) | `technical_failure` ≠ abstention est imposé (`evaluation.py:58-59`, `tests/test_evaluation.py:199`). Mais pas de REFUSED_SECURITY ni ERROR_TOKEN_BUDGET typés → contrat **partiel**. |

## H. Autres écarts constatés (README vs artefacts)

| # | Affirmation | Statut | Preuve | Remarque |
|---|---|---|---|---|
| H1 | Smoke GPU exécuté sur RTX 4090 | CONTREDIT | `data/results/bge_m3_gpu_smoke_report.json` (`hardware.gpu: NVIDIA A40`, 44,4 GiB) ; `AUDIT/00-DOSSIER-AUDIT.md` (« 1er smoke GPU réel sur A40 ») | Exécuté sur **A40**. Le manifeste nommé « rtx4090 » ≠ matériel réel. |
| H2 | Chiffres smoke README (2 945 chunks, 24,88 s, 118,38 chunks/s, 1,11 GiB) | CONTREDIT | Artefact committé : 7 371 chunks, `embedding.seconds: 54,37`, `chunks_per_second: 135,58`, `peak_allocated_vram_gib: 1,085` | Les chiffres du README ne correspondent pas à l'artefact committé. |
| H3 | « Aucune dépendance externe pour les tests du cœur » | CONTREDIT | `tests/test_acl_differential.py:5` importe `hypothesis` → `ModuleNotFoundError` (exécution 2026-10-08) | 1 test en erreur d'import cette session. |

## Comportement actuel documenté (pré-requis au contrat de défaillance)

- Paire > budget : exception `RerankerBudgetExceeded` (non typée par requête), interrompt le scoring du lot.
- Aucun candidat : liste vide → `best_score = None` → abstention (seuil 0,5 provisoire).
- Distinction panne technique vs abstention : présente (`evaluation.py:58-59`) ; distinction refus sécurité vs absence de preuve : **absente** au niveau d'un statut typé.
