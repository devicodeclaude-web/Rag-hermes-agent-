# Lot 3 — chemin ACL : filtre Qdrant réel + contrôle d'autorité après retrieval

- Date d'exécution : 2026-10-08 (UTC). Qdrant 1.19.0 réel démarré localement
  (`127.0.0.1:6333`, commit `74f3e85…`, conforme à `qdrant/runtime.lock.json`,
  archive SHA-256 vérifiée). Vecteurs déterministes de test (pas d'embeddings,
  pas de GPU).
- Commit audité == HEAD de la branche : `cc041e7…`.
- Aucun nouveau code : les deux maillons existaient déjà ; ce lot les EXERCE à
  HEAD cette session et prouve fuite = 0. Aucun défaut mesuré → rien ajouté.

## Maillon 1 — filtre du vrai Qdrant (prefilter)

`rag_hermes/retrieval.py:retrieve_authorized_candidates` →
`build_qdrant_filter(context)` envoyé au vrai Qdrant.

Preuves (exécutées cette session) :
- `AUDIT/2026-10-08-acl-path/acl_matrix_qdrant.json` — stage `qdrant_prefilter`
  sur 100 essais × 9 catégories : `qdrant_ids ⊆ reference_ids` à chaque essai.
  Catégories bloquées DÈS le filtre Qdrant (0 candidat renvoyé) :
  `cross_tenant`, `clearance_insufficient`, `acl_missing_or_null`.
- `AUDIT/2026-10-08-acl-path/qdrant_acl_smoke.json` — corpus RÉEL (465 docs,
  2 945 chunks) : alpha/beta/gamma ne voient que leur tenant + public ;
  alpha à clearance 0 ne voit que public. `leak_count = 0`.

## Maillon 2 — contrôle d'autorité canonique APRÈS le retrieval

`rag_hermes/retrieval.py:postfilter_candidates` → `CanonicalAclAuthority.authorize`
(`unknown_document` / `stale_acl_version` / `denied`), autorité séparée des
payloads Qdrant (« derived indexes »).

Preuve du DIFFÉRENTIEL (l'autorité bloque ce que l'index aurait rendu) —
`acl_matrix_qdrant.json`, colonnes qdrant_candidates vs production_candidates :

| catégorie | qdrant_cand | production_cand | fuites |
|---|---:|---:|---:|
| revoked_right | 100 | 0 | 0 |
| stale_acl_version | 100 | 0 | 0 |
| cross_tenant | 0 | 0 | 0 |
| clearance_insufficient | 0 | 0 | 0 |
| acl_missing_or_null | 0 | 0 | 0 |
| clearance_sufficient | 100 | 100 | 0 |
| groups | 50 | 50 | 0 |
| named_users | 50 | 50 | 0 |
| public_visibility | 10000 | 10000 | 0 |

`revoked_right` et `stale_acl_version` : le prefilter Qdrant renvoie 100
candidats, mais l'autorité canonique en laisse passer 0 → le re-contrôle
post-retrieval est NÉCESSAIRE et EXERCÉ. Le stage `expected_target_visibility`
vérifie en plus que la cible n'est visible que si `index_reference_allows ET
authority_allows`.

## Fuite inter-tenant

- `observed_leaks` total = 0 ; par catégorie, borne haute 95 % (règle de trois) = 0,03.
- 0 fuite observée n'est PAS une preuve de risque nul (limite déclarée dans le rapport).

## Contrat de défaillance (sécurité vs absence de preuve)

- La réponse utilisateur ne révèle jamais un document non autorisé : la barrière
  retire les candidats non autorisés AVANT le scoring (différentiel ci-dessus →
  0 candidat en production pour revoked/stale). Un cas purement non autorisé
  devient une abstention « absence de preuve ».
- Distinction dans les JOURNAUX : `AclBarrierCounters{examined, accepted,
  stale_acl_version, denied_by_authority}` (`retrieval.py`) enregistre les refus
  de sécurité séparément.
- Gap honnête (décision à prendre, hors périmètre Lot 3) : au niveau du RAPPORT
  d'évaluation, aucune métrique ne distingue une abstention induite par filtrage
  de sécurité d'une abstention « vrai manque de preuve ». Les compteurs de barrière
  existent mais ne sont pas remontés comme métrique dédiée.

## Non prouvé / limites

- Autorité canonique = registre en mémoire ; aucune autorité externe persistante
  (ex. PostgreSQL) n'existe ni n'est exercée.
- Qdrant local, pas un service déployé.
- Vecteurs déterministes de test : barrière ACL prouvée, PAS la qualité sémantique.

## Rejouer

```
# Qdrant 1.19.0 aarch64 (sha256 verifie) sur 127.0.0.1:6333, puis :
PYTHONPATH=. python3 scripts/run_acl_matrix.py \
  --qdrant-url http://127.0.0.1:6333 \
  --output AUDIT/2026-10-08-acl-path/acl_matrix_qdrant.json
PYTHONPATH=. python3 scripts/qdrant_smoke.py --url http://127.0.0.1:6333 \
  --collection hermes_acl_path_20261008 \
  --documents data/generated/hermes_public_documents.jsonl \
  --documents data/fixtures/private_and_synthetic_documents.jsonl
```
