# Contre-revue indépendante de la PR #117 — code fusionné

Date UTC : 2026-11-28. SHA audité : `ffef872628c925560c9024168ac82b7df8702463` (arbre de la tête `cd0e4ab2a1063ef90b3326c4ca0a8f648608db8e`). Modèle du relecteur isolé : `gpt-6-sol` via `openai-codex`. Revue indépendante du premier auteur par sous-agent en lecture seule ; ce n'est ni une revue humaine ni un modèle d'un autre fournisseur. Transcript : `/root/.hermes/cache/delegation/live/deleg_172409eb/task-0.log` (preuve locale, non committée). Ancienne contre-revue sur `87c5201` non transposable au SHA final.

Verdict : **BLOQUANT pour poursuivre la réconciliation tant que le défaut P1 n'est pas corrigé dans une PR distincte**. Aucun endpoint de suppression n'est raccordé.

| Priorité | Observation et preuve | Portée |
|---|---|---|
| P1 | `rag_hermes/qdrant_write_lock.py:101-131` conserve dans un enfant issu de `fork` un descripteur de bail documentaire non nettoyé. Reproduction isolée : le détenteur sort sans dérouler son contexte, l'enfant reste vivant ; l'acquisition par un tiers expire, puis réussit après sortie de l'enfant. | Disponibilité des écrivains coopérants ; aucune preuve d'un endpoint exposé. |
| P2 | `rag_hermes/qdrant_repository.py:23-35,280-295` indexe l'assertion de bail par `(collection, tenant, document)` seulement. Deux dépôts sur deux répertoires distincts ont la même clé TLS : le cœur de B marque 2 points sous le bail de A sans verrou B ; l'enfant `fork` hérite de la clé. | Invariant défensif des cœurs privés ; le coordinateur public prend effectivement son bail. |
| P2 | `rag_hermes/canonical_tombstone.py:84-106` enveloppe une défaillance de relecture canonique dans `CanonicalMaskIndexError`. | Ne jamais conclure depuis cette seule exception que seul Qdrant est en panne. |

Tests réellement exécutés par le relecteur : `PYTHONPATH=. /root/work/venv/bin/python -m unittest tests.test_issue71_mask_coordinator tests.test_issue71_tombstone_preflight -q` → **31 OK**. Qdrant authentifié ignoré localement faute de serveur. CI `lock-install`, run `46060376548`, tête `cd0e4ab`, artefact téléchargé sous `/root/.hermes/cache/scratch/pr117-ci-proof/` : `exit-code.txt=0` ; `lock-install-x86_64-py312.txt:1382` test Qdrant réel `test_canonical_first_mask_over_scoped_clients_on_real_qdrant ... ok`, lignes 1817-1819 : **1436 tests, OK**. Le SHA d'artefact `ca004423…` est le merge de test de cette tête ; le relecteur a comparé son arbre à celui de `ffef872`. Aucune preuve CI des scénarios `fork` ci-dessus.

Suite : écrire des tests RED de bail `fork`/identité, corriger dans une PR dédiée, obtenir CI et contre-revue sur son SHA final ; attendre l'autorisation explicite de fusion avant reprise du chantier de réparation. Les garanties d'identité historique d'ingestion et de génération de collection restent non établies pour les données existantes et ne doivent pas être fabriquées a posteriori.
