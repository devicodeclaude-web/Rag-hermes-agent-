# Dossier d'audit — Dataset d'évaluation v2 (annotation manuelle)

Ce dossier rassemble les preuves vérifiables de la construction du jeu
d'évaluation `data/benchmark/dataset-v2.jsonl` (questions bilingues EN/FR,
annotées à la main selon un protocole anti-circularité).

## Niveau de preuve

Niveau **intégration de composant** (tooling d'annotation + validateur canonique
+ suite de tests avec Qdrant 1.19.0 réel). Ce n'est **pas** une preuve de qualité
statistique ni de production : le jeu n'a pas encore atteint le volume cible
(100 cas EN + 40 paires FR) et aucune métrique de retrieval n'est mesurée ici.

## Protocole (anti-circularité)

1. L'utilisateur rédige chaque question **de tête, sans voir le corpus**
   (`question_provenance: human_task_without_corpus_view`).
2. L'annotateur trouve ensuite le passage qui répond, vérifié **verbatim + unique**
   (`corpus_lookup.py check` → même résolveur que l'ingesteur).
3. Ingestion atomique du lot (`ingest_manual_batch.py` : tout-ou-rien).
4. Revue indépendante fail-closed (second relecteur, contexte neuf) ; une paire
   ambiguë ou insuffisamment couverte bloque et reste `pending`.
5. Seules les paires explicitement approuvées passent `validated`.

Remède appliqué quand un passage ne couvrait pas la question d'origine : on
**réduit** la question à ce que le passage prouve (jamais l'inverse). Cas concrets :
m-024 (réduit au périmètre de la skill de tri) et m-010 (réduit à « quel rôle peut
encore appeler delegate_task »).

## Composition à l'instant de l'audit

- Total : 54 cas (27 paires EN/FR complètes), tous `validated`, 0 `pending`.
- Répondables : 48 cas ; abstention (`no_answer`, hors périmètre corpus) : 6 cas
  (m-004 Afrique, m-005 chromosomes, m-006 départements).
- Gate canonique : `structural: valid`, `targets_met: false`
  (EXIT 2 = volume incomplet, comportement attendu et honnête).
- Reste pour les cibles : 73 cas EN, 13 paires FR.

Les 3 premières paires initiales (m-001..m-003) ont été **retirées** : elles
avaient été reformulées APRÈS consultation du corpus tout en gardant la provenance
« sans corpus » — violation d'anti-circularité. À remplacer par des questions
aveugles fraîches.

## Fichiers de preuve

| Fichier | Contenu |
|---|---|
| `gate-dataset-v2.txt` | Sortie du validateur canonique `validate_dataset_v2.py` (EXIT 2 = volume). |
| `tests-full-qdrant-reel.txt` | Suite complète `unittest`, Qdrant 1.19.0 aarch64 RÉEL : 346 tests, OK, 0 skip. |
| `precheck-lot006.txt` | Pré-contrôle dry-run du gros lot (40 lignes), 0 problème, rien écrit. |
| `inventaire-paires.txt` | Table des 27 paires : statut, catégorie, abstention, document+span, question. |
| `revues/revue-qualite-m011-m030.txt` | Verdict fail-closed des 20 paires (19 pass, m-024 bloqué puis corrigé). |
| `revues/revue-qualite-m007-m010.txt` | Verdict fail-closed m-007 (pass) + m-010 (bloqué puis reformulé/corrigé). |
| `revues/revue-commit-dataset-initial.txt` | Revue du 1er commit de dataset (6 cas, passed=true). |
| `revues/refs-m0*.txt` | Sorties brutes des recherches de passages (preuves verbatim+unique). |
| `SHA256SUMS-dataset-v2` | Empreintes de tous les fichiers ci-dessus + du dataset. |

Les fichiers `revues/*` sont des **sorties brutes de relecteurs** : evidence,
ne pas éditer. Un verdict `passed=false` est une preuve que le gate de revue a un
réel pouvoir de détection, pas un échec à masquer.

## Limites

- Aucune métrique recall/MRR/abstention mesurée ici.
- Corpus privé réel absent : pas de mesure de qualité privée.
- Un gate `pending=0` prouve seulement l'état du fichier courant, pas l'existence
  d'une preuve de revue — celle-ci est conservée dans `revues/`.
