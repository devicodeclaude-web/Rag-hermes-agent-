# DOSSIER D'AUDIT — Harnais RAG sécurisé (rag-hermes-agent)

Point d'étape au commit `5970956` (branche `main`).
Ce dossier est autoportant : il te permet d'auditer le travail sans relancer
l'historique de conversation. Toutes les preuves brutes sont dans `preuves/`.

---

## 1. LE PROJET EN UNE PHRASE

Construire et **vérifier honnêtement** un harnais de RAG (Retrieval-Augmented
Generation) multi-tenant sécurisé pour Hermes : ingestion → chunking →
embedding → recherche hybride filtrée par droits d'accès (ACL) → reranking,
avec des garde-fous de coût GPU et une discipline de preuve (rien n'est
"validé" sans exécution réelle).

---

## 2. SCHÉMA DE PARCOURS (d'où on part → où on va)

```
                          LIGNE DE TEMPS DU TRAVAIL
                          =========================

 [PASSÉ - avant cette session]
   ca55d8b  Audit fixes : chunking par tokens, ACL Qdrant réelle, garde-fous pod
   0df6571  Watchdog RunPod corrigé (liste de pods live)
   2e9e36b  1er smoke GPU réel sur A40  ......................... run GPU #1
   bbdd665  Cadrage : le smoke est un PASS conditionnel, pas prod
   ccfbee2  truncated_pairs marqué "non instrumenté" (honnêteté)

 [CETTE SESSION - audit contradictoire, 9 commits]
   3cbc67f  Commande exacte du test d'intégration Qdrant documentée
   6a92701  Runner CI strict : un test "skipped" devient un échec
   e80f1ee  Test ACL de bout en bout avec vecteur adverse
   19a8516  Ablation chunking CPU : 84-87% vs 0% hors budget
   208c951  Hygiène : scanner secrets + gitignore + hashes ......... (remplacé plus bas)
   c7f701f  Lock uv complet (75 paquets, 2170 hashes)
   44f8416  Scanner : ignore ses propres fixtures de test
   7038595  Wrapper non-root + limite PRoot documentée
   5970956  gitleaks intégré au CI + caveat CUDA du lock

 [À VENIR - reste à faire, dans l'ordre convenu]
   Étape 3   Protocole pré-inscrit + exception de budget avant compute_score
   Étape 4   Run A40 suspendu jusqu'à fermeture des quatre lots
   Étape 5   Compte rendu final consolidé
```

---

## 3. PIPELINE TECHNIQUE (ce que le harnais fait)

```
  Documents (corpus public Hermes + fixtures privées multi-tenant)
        │
        ▼
  [ingestion.py] chunk_document_tokens  ──► découpe par TOKENS (384/64)
        │                                    (l'ancien découpait par mots → trop long)
        ▼
  [qdrant_store.py] chunk_to_point  ──► vecteur + payload ACL complet
        │                               (tenant, visibility, groupes, users, clearance)
        ▼
  [qdrant_rest.py] upsert  ──► Qdrant 1.19.0 (base vectorielle)
        │
        ▼
  REQUÊTE utilisateur (tenant + user + groupes + clearance)
        │
        ▼
  [qdrant_filter.py] build_qdrant_filter  ──► filtre ACL (jamais de requête sans filtre)
        │
        ▼
  [qdrant_rest.py] query  ──► candidats AUTORISÉS uniquement
        │
        ▼
  reranking (bge-reranker-v2-m3, sur GPU)  ──► fenêtre 512 tokens, politique "reject"
        │
        ▼
  [evaluation.py] Recall@k, MRR, abstention, FUITE ACL = 0 exigée
```

Garde-fous transverses :
- `pod_budget.py` / `pod_watchdog.py` : plafond de coût, suppression auto du pod.
- `pod_security.py` / `local_hardening.py` : exécution non-root.
- `artifact_lock.py` / `manifest.py` : modèles verrouillés par hash/révision.

---

## 4. TABLEAU D'ÉTAT DES POINTS D'AUDIT

| # | Point soulevé | Statut | Preuve |
|---|---------------|--------|--------|
| 1 | Clé API RunPod révoquée (401 avant purge locale) | BLOQUÉ | preuve 401 non retrouvée dans `AUDIT/historique/` |
| 2 | `truncated_pairs` codé en dur / tautologique | BLOQUÉ | correction codée, mais aucune preuve standardisée sur l'`audited_commit` |
| 3 | Test Qdrant "skipped" en silence en CI | BLOQUÉ | en attente de `preuves/tests-ci-strict.txt` sur l'`audited_commit` |
| 4 | ACL prouvée seulement sur 3 vecteurs jouets | BLOQUÉ | en attente de `preuves/tests-ci-strict.txt` sur l'`audited_commit` |
| 5 | Incohérence "60 tests dont Qdrant" vs "1 skip" | BLOQUÉ | en attente de `preuves/tests-ci-strict.txt` |
| 6 | Diff causal chunking (rejets 190→0) non prouvé | 🟠 EN COURS | CPU seulement ; Recall GPU suspendu |
| 7 | Hygiène : gitleaks réel, hashes, clé SSH | BLOQUÉ | en attente de `preuves/lock-install.txt` et `preuves/runtime-identity.txt` |
| 8 | Hermes root dans le PRoot | 🟠 EN COURS | risque accepté ; mitigation : absence de secret persistant ; PRoot n'est pas une frontière de sécurité |
| 9 | `truncated_pairs` mesuré réellement | 🟠 EN COURS | nécessite run GPU, actuellement suspendu |
| 10 | Recall avant/après reranking (utilité reranker) | 🟠 EN COURS | nécessite run GPU, actuellement suspendu |

\* Limite mesurée : le PRoot Termux n'applique pas l'isolation UID au niveau
filesystem (voir `docs/non-root-hardening.md`). Le durcissement réel repose sur
l'absence de secret persistant, pas sur une barrière FS locale.

---

## 5. VERDICT ACTUEL

- **Smoke GPU** : PASS conditionnel (technique), PAS un PASS production.
- **Sécurité ACL** : code et tests existent, mais fermeture bloquée sans preuve
  standardisée sur l'`audited_commit`.
- **Hygiène secrets** : revendication bloquée tant que la preuve historique et
  l'installation depuis le lock ne sont pas dans le bundle validé.
- **Qualité sémantique** : NON prouvée (10 questions ≠ signal statistique).
  Un vrai jugement qualité exige 100 puis 300 questions (voir
  `docs/acceptance-criteria.md`).

---

## 6. OÙ TROUVER QUOI (pour auditer)

| Preuve | Fichier |
|--------|---------|
| Historique des commits | `preuves/git-log.txt` |
| Arbre git propre | `preuves/git-status.txt` |
| Suite de tests (hors Qdrant) | `preuves/tests-sans-qdrant.txt` |
| gitleaks sur tout l'historique | `preuves/gitleaks-historique.txt` |
| Ablation chunking CPU (résultat) | `preuves/chunking_ablation_cpu.json` |
| Rapport smoke GPU A40 | `preuves/bge_m3_gpu_smoke_report.json` |
| Runbook GPU sécurisé | `../docs/smoke-gpu-runbook.md` |
| Critères d'acceptation | `../docs/acceptance-criteria.md` |
| Limite non-root PRoot | `../docs/non-root-hardening.md` |
| Réconciliation d'audit | `../docs/audit-reconciliation.md` |

---

## 7. PROCHAINES ACTIONS (reprise après la pause)

1. **Étape 3 (gratuit)** : protocole pré-inscrit dans
   `docs/ablation-protocol.md`. Le budget est une exception explicite levée
   juste avant `compute_score`, jamais un `assert` désactivable par `python -O`.
2. **Étape 4 (~0,05 $)** : un seul run A40 borné, clé API à périmètre minimal,
   révoquée immédiatement après. Mesure : `truncated_pairs` réel + Recall
   avant/après reranking.
3. **Étape 5** : compte rendu final consolidé.
