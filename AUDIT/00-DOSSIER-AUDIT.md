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

 [CETTE SESSION - audit contradictoire, 7 commits]
   3cbc67f  Commande exacte du test d'intégration Qdrant documentée
   6a92701  Runner CI strict : un test "skipped" = ÉCHEC ............ ✅ FERMÉ
   e80f1ee  Preuve ACL de BOUT EN BOUT (vecteur adverse) ........... ✅ FERMÉ
   19a8516  Ablation chunking CPU : 84-87% vs 0% hors budget ....... ✅ FERMÉ (partie CPU)
   208c951  Hygiène : scanner secrets + gitignore + hashes ......... (remplacé plus bas)
   c7f701f  Lock uv complet (75 paquets, 2170 hashes) .............. ✅ FERMÉ
   44f8416  Scanner : ignore ses propres fixtures de test
   7038595  Wrapper non-root + limite PRoot documentée ............. ✅ FERMÉ (avec limite)
   5970956  gitleaks intégré au CI + caveat CUDA du lock ........... ✅ FERMÉ   <-- ON EST ICI

 [À VENIR - reste à faire, dans l'ordre convenu]
   Étape 3   Protocole d'ablation ÉCRIT AVANT le run (Recall avant/après)
             + assert avant compute_score .......................... 🟠 À FAIRE (gratuit)
   Étape 4   UN SEUL run A40 : mesure truncated_pairs réelle +
             Recall reranking, clé API minimale, révoquée après ..... 🟠 À FAIRE (~0,05 $ GPU)
   Étape 5   COMPTE RENDU FINAL consolidé ......................... 🎯 CIBLE
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
| 1 | Clé API RunPod révoquée (401 avant purge locale) | ✅ Fermé | 401 obtenu avant nettoyage ; config.toml sans apiKey |
| 2 | `truncated_pairs` codé en dur / tautologique | ✅ Corrigé | mis à `null` + "not_instrumented" (ccfbee2) ; 2 revues indépendantes |
| 3 | Test Qdrant "skipped" en silence en CI | ✅ Fermé | `run_ci_strict.py` : skip = échec dur (6a92701) |
| 4 | ACL prouvée seulement sur 3 vecteurs jouets | ✅ Fermé | test e2e vecteur adverse, code de prod (e80f1ee) |
| 5 | Incohérence "60 tests dont Qdrant" vs "1 skip" | ✅ Fermé | commande exacte documentée (3cbc67f) |
| 6 | Diff causal chunking (rejets 190→0) non prouvé | 🟠 Partiel | CPU prouvé 84-87%→0% (19a8516) ; Recall GPU à faire |
| 7 | Hygiène : gitleaks réel, hashes, clé SSH | ✅ Fermé | gitleaks "no leaks" ; lock 75 pkgs ; clés SSH purgées |
| 8 | Hermes root dans le PRoot | ✅ Fermé* | workload sous uid 10177 ; *limite PRoot documentée |
| 9 | `truncated_pairs` mesuré réellement | 🟠 À faire | nécessite run GPU (étape 4) |
| 10 | Recall avant/après reranking (utilité reranker) | 🟠 À faire | nécessite run GPU (étape 4) |

\* Limite mesurée : le PRoot Termux n'applique pas l'isolation UID au niveau
filesystem (voir `docs/non-root-hardening.md`). Le durcissement réel repose sur
l'absence de secret persistant, pas sur une barrière FS locale.

---

## 5. VERDICT ACTUEL

- **Smoke GPU** : PASS conditionnel (technique), PAS un PASS production.
- **Sécurité ACL** : bout-en-bout prouvé sur Qdrant réel avec cas adverse.
- **Hygiène secrets** : gitleaks "no leaks" sur tout l'historique.
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

1. **Étape 3 (gratuit)** : écrire et figer le protocole d'ablation AVANT le run
   (Recall@10 avant vs après reranking, seuils prédéfinis), puis ajouter
   l'`assert` de budget juste avant `compute_score`.
2. **Étape 4 (~0,05 $)** : un seul run A40 borné, clé API à périmètre minimal,
   révoquée immédiatement après. Mesure : `truncated_pairs` réel + Recall
   avant/après reranking.
3. **Étape 5** : compte rendu final consolidé.
