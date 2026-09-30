# État d'implémentation de la V1 locale

Ce document trace la correspondance entre les composants livrés et les critères
d'acceptation (`docs/acceptance-criteria.md`). Il ne remplace aucune
spécification : il indique seulement ce qui est réellement implémenté et vérifié,
et ce qui reste à faire. Aucun score de qualité n'est probant avant la piste
humaine annotée et les jeux gelés de 100 puis 300 questions.

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
| Outillage d'annotation humaine | `scripts/ingest_manual_batch.py`, `scripts/corpus_lookup.py`, `templates/manual_eval_batch.template.jsonl` | Ingestion atomique fail-closed ; provenance humaine ; validation stricte du schéma |
| Durcissement HTTP / UI | `rag_hermes/http_api.py`, `rag_hermes/web_ui.py` | En-têtes de sécurité sur toutes les réponses, CSP stricte, JS externalisé (`/app.js`), host loopback-only |

## Correspondance avec les critères d'acceptation

| Critère (`acceptance-criteria.md`) | État |
|---|---|
| Baseline sans retrieval exécutée avec les mêmes paramètres | **Implémentée** (closed-book activable par `RAG_BASELINE_*`) ; exécution avec un vrai endpoint LLM à venir |
| Revue humaine ≥ 20 % | **Outillée** (échantillon déterministe produit par le comparateur) ; la revue elle-même reste à réaliser |
| Fuite inter-tenant 0 absolu | Barrière ACL Qdrant réelle validée par ailleurs ; le rapport synthétique confirme leak_count 0 (corpus 100 % public) |
| Élargissement de recherche après erreur ACL 0 absolu | Garanti par le service (refus fermé) ; couvert par la suite de tests |
| Validité structurelle des citations 1,00 | Générateur RAG fail-closed sur citations invalides |
| ≥ 300 questions gelées + couverture (privé, abstention, contradictions, injections) | **À faire** (piste humaine vide ; jeu intermédiaire de 100 dont ≥ 30 manuelles d'abord) |
| Seuils de recall/MRR/abstention | Non probants tant que la piste humaine annotée et un récupérateur dense/reranké réels ne sont pas en place |

## Reste à faire

1. **Piste humaine** : rédiger ≥ 30 questions écrites à la main (sans voir le
   corpus), puis atteindre les cibles du gate `scripts/validate_dataset_v2.py`
   (100 EN + 40 paires FR, toutes revues). Outillage prêt.
2. **Endpoint LLM réel** : brancher `RAG_GENERATOR_*` et `RAG_BASELINE_*` sur un
   serveur OpenAI-compatible pour produire de vraies réponses RAG et closed-book,
   puis relancer le comparateur.
3. **Revue humaine ≥ 20 %** : juger la justesse des réponses appariées
   (fichier `data/results/campaign-review-sample.jsonl`).
4. **Smoke GPU** : réexécuter avec `rejected_pairs = 0` avant de retenir le
   reranker (nécessite un GPU cloud ; voir `docs/smoke-gpu-runbook.md`).
5. **Récupérateur dense/reranké réel** : persister les sorties dense+sparse dans
   Qdrant et mesurer le gain par rapport au plancher lexical.

## Discipline de développement

Chaque incrément ci-dessus a suivi : TDD (rouge → vert), suite complète avec
Qdrant 1.19.0 réel (0 skip), puis revue indépendante fail-closed jusqu'à
`passed=true`. Les verdicts sont conservés dans `.reviews/`.
