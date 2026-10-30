# État d'implémentation de la V1 locale

Ce document trace la correspondance entre les composants livrés et les critères
d'acceptation (`docs/acceptance-criteria.md`). Il ne remplace aucune
spécification : il indique seulement ce qui est réellement implémenté et vérifié,
et ce qui reste à faire. Aucun score de qualité n'est probant avant une piste
finale gelée, annotée et conforme à tous les critères de couverture.

## Composants livrés (code + tests + revue indépendante)

| Composant | Module / script | Vérification |
|---|---|---|
| Générateur RAG OpenAI-compatible (optionnel) | `rag_hermes/generator.py` (`RAG_GENERATOR_*`) | Anti-SSRF loopback-only, no-redirect, cap réponse, citations `[Sn]` validées par chaîne (pas d'`int()`), abstention exacte, fail-closed |
| Reranker cross-encodeur budgété (optionnel) | `rag_hermes/reranker.py` (`RAG_RETRIEVAL_K`/`RAG_TOP_K`) | Ne réordonne que des chunks autorisés ; budget de tokens vérifié avant scoring ; défaillance de composant → `GenerationError` → HTTP 502 |
| Runner d'évaluation chunking-indépendant | `rag_hermes/evaluation_runner.py` | Validation schéma stricte avant scoring ; offsets/texte canoniques ; détection de fuite ; anti-collision de labels |
| Baseline générative SANS retrieval (closed-book) | `rag_hermes/closed_book.py`, `closed_book_eval.py` (`RAG_BASELINE_*`) | Sans sources, sans citations, abstention honnête, durcissement réseau partagé ; harnais d'abstention hors-ligne |
| Comparateur RAG vs closed-book | `rag_hermes/campaign_compare.py`, `scripts/compare_campaigns.py` | Abstention des deux campagnes (sentinelles distinctes) ; échantillon de revue humaine déterministe ≥ 20 % |
| Piste d'évaluation synthétique | `rag_hermes/synthetic_dataset.py`, `scripts/migrate_v1_to_synthetic.py` | 100 cas, provenance `synthetic_generated_from_corpus` jamais quality-eligible (non-circularité), spans document entier |
| Rapport-témoin synthétique | `rag_hermes/synthetic_report.py`, `scripts/synthetic_eval_report.py` | recall@k document-niveau sur corpus réel ; leak_count 0, gate actif |
| Rapport lexical humain | `rag_hermes/human_report.py`, `scripts/human_eval_report.py` | 154 cas humains revus ; résultats globaux, EN→EN, FR→EN et catégories ; publication checksum puis rapport-marqueur + vérification SHA-256 ; FR→EN diagnostic seulement |
| Rapport dense persisté (plomberie) | `rag_hermes/dense_report.py`, `scripts/dense_eval_report.py` | Pipeline persisté réel : ingestion corpus → Qdrant 1.19.0 → recherche ANN → préfiltre ACL → scoring ; embedder **déterministe, pas une embedding sémantique** → `quality_eligible=false`, `retriever=qdrant_deterministic_not_an_embedding` ; prouve la plomberie (leak_count 0), pas la qualité ; BGE-M3 réel injecté seulement au smoke GPU |
| Outillage d'annotation humaine | `scripts/annotate_eval_case.py`, `scripts/precheck_manual_batch.py`, `scripts/ingest_manual_batch.py`, `scripts/corpus_lookup.py`, `templates/manual_eval_batch.template.jsonl` | Écrit uniquement dans `data/benchmark/dataset-v2-quality-candidate.jsonl`, initialisé comme copie exacte du snapshot humain 154 ; refuse une candidate absente ou dont le préfixe gelé dérive ; n'écrit jamais dans le QA actif ni dans le snapshot immuable ; ingestion atomique fail-closed, provenance humaine et validation stricte du schéma |
| Durcissement HTTP / UI | `rag_hermes/http_api.py`, `rag_hermes/web_ui.py` | En-têtes de sécurité sur toutes les réponses, CSP stricte, JS externalisé (`/app.js`), host loopback-only |

## Correspondance avec les critères d'acceptation

| Critère (`acceptance-criteria.md`) | État |
|---|---|
| Baseline sans retrieval exécutée avec les mêmes paramètres | **Implémentée** (closed-book activable par `RAG_BASELINE_*`) ; exécution avec un vrai endpoint LLM à venir |
| Revue humaine ≥ 20 % | **Outillée** (échantillon déterministe produit par le comparateur) ; la revue elle-même reste à réaliser |
| Fuite inter-tenant 0 absolu | Barrière ACL Qdrant réelle validée par ailleurs ; le rapport synthétique confirme leak_count 0 (corpus 100 % public) |
| Élargissement de recherche après erreur ACL 0 absolu | Garanti par le service (refus fermé) ; couvert par la suite de tests |
| Validité structurelle des citations 1,00 | Générateur RAG fail-closed sur citations invalides |
| ≥ 300 questions gelées + couverture (privé, abstention, contradictions, injections) | **Critère non atteint** : après revue indépendante, deux cas invalides ont été rejetés et archivés (`v3na-115`, `v3cb-091`). Le dataset QA actif contient 298 cas actifs uniques, tous aux statuts `validated`, et passe `check_dataset_qa.py` (76 simples, 60 paraphrases, 60 distracteurs proches, 44 frontières de chunks, 58 sans réponse). Le déficit de 2 cas n'autorise pas à réintroduire les rejets. Cette piste reste distincte du snapshot de 154 cas humains éligibles qualité et ne couvre pas explicitement privé, contradictions et injections. |
| Seuils de recall/MRR/abstention | Baseline lexicale humaine mesurée : Recall@10 global 0,3361, MRR 0,1737, rappel d'abstention 0 ; comparaison dense/rerankée et intervalles de confiance encore absents |

## Reste à faire

1. **Qualifier et compléter le jeu final** : préserver séparément les 298 cas
   actifs revus du schéma QA, les deux rejets archivés et le snapshot historique
   de 154 cas humains. Ajouter au moins deux nouveaux cas valides puis
   revoir, dans une piste finale gelée et éligible qualité, les catégories privé,
   contradictions et injections ; ne pas assimiler le seul compte de 300 à une
   satisfaction du critère d'acceptation.
2. **Endpoint LLM réel** : brancher `RAG_GENERATOR_*` et `RAG_BASELINE_*` sur un
   serveur OpenAI-compatible pour produire de vraies réponses RAG et closed-book,
   puis relancer le comparateur.
3. **Revue humaine ≥ 20 %** : juger la justesse des réponses appariées
   (fichier `data/results/campaign-review-sample.jsonl`).
4. **Smoke GPU** : réexécuter avec `rejected_pairs = 0` avant de retenir le
   reranker (nécessite un GPU cloud ; voir `docs/smoke-gpu-runbook.md`).
5. **Récupérateur dense/reranké réel** : la **plomberie** dense persistée est
   faite et vérifiée sur Qdrant réel (`scripts/dense_eval_report.py`, embedder
   déterministe, `leak_count 0`). Reste à injecter le **vrai** BGE-M3 au smoke
   GPU pour mesurer le gain sémantique par rapport au plancher lexical.

## Discipline de développement

Chaque incrément ci-dessus a suivi : TDD (rouge → vert), suite complète avec
Qdrant 1.19.0 réel (0 skip), puis revue indépendante fail-closed jusqu'à
`passed=true`. Les verdicts sont conservés dans `.reviews/`.
