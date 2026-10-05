# Dossier d'audit — Dataset d'évaluation v2 (annotation manuelle)

Ce dossier rassemble les preuves vérifiables de la construction du jeu
d'évaluation `data/benchmark/dataset-v2.jsonl` (questions bilingues EN/FR,
annotées à la main selon un protocole anti-circularité).

## Niveau de preuve

Niveau **intégration de composant** (tooling d'annotation + validateur canonique
+ suite de tests). Ce n'est **pas** une preuve de qualité statistique ni de
production : aucune métrique de retrieval (recall/MRR/abstention) n'est mesurée
ici. Le volume cible EN (100) n'est pas tout à fait atteint (99) après le
retrait d'un doublon — voir plus bas.

## Protocole (anti-circularité)

1. L'utilisateur rédige chaque question **de tête, sans voir le corpus**
   (`question_provenance: human_task_without_corpus_view`).
2. L'annotateur trouve ensuite le passage qui répond, vérifié **verbatim + unique**
   (`corpus_lookup.py check` → même résolveur que l'ingesteur). Le format d'entrée
   d'un lot est `relevant_passages` + `passage_text` ; les offsets et le SHA-256
   sont calculés par `build_case`, donc les labels restent indépendants du chunking.
3. Ingestion atomique du lot (`ingest_manual_batch.py` : tout-ou-rien).
4. Revue indépendante fail-closed (second relecteur, contexte neuf) ; une paire
   ambiguë, insuffisamment couverte, ou en doublon sémantique bloque.
5. Seules les paires explicitement approuvées passent `validated`.

Remède autorisé quand un passage ne couvre pas la question d'origine : on
**réduit** la question à ce que le passage prouve (jamais l'inverse).

## Composition à l'instant de l'audit

- Total : **139 cas** — **99 EN** + **40 paires FR**, tous `validated`, 0 `pending`.
- Répondables : 121 cas ; abstention (`no_answer`, hors périmètre corpus) : 18 cas.
- Gate canonique : `structural: valid`, `pending: 0`, `reviewed: 139`,
  `targets_met: false` → **EXIT 2 = volume EN incomplet (99/100)**, comportement
  attendu et honnête. Reste 1 cas EN pour la cible.
- Suite de tests dataset-focalisée : 33 tests, **OK**, 0 skip.

## Doublon sémantique détecté et corrigé

Lors de la revue pré-commit indépendante (6 lots en parallèle), **deux relecteurs
indépendants** (lots 05 et 06) ont signalé le **même** doublon sémantique :

- `m-103-en` (« At what fraction of the context limit does Hermes auto-compress
  by default? » → 0.50) et `m-112-en` (« Which Hermes config key, set under
  compression, sets the auto-compress threshold? » → `threshold`) reposaient sur
  le **span strictement identique** : `cli.md` 27035–27101, ligne
  `threshold: 0.50 # Compress at 50% of context limit by default` (même SHA-256).
- Une seule preuve atomique ne doit pas fonder deux cas (règle fail-closed).
- **Correction appliquée : `m-112-en` a été retiré** (span moins complet — il
  n'incluait pas le parent `compression:` que sa question invoque), `m-103-en` conservé.

Les verdicts bruts des deux relecteurs qui ont détecté le doublon sont conservés
tels quels dans `revues/` — ce sont des preuves que le gate de revue a un réel
pouvoir de détection, pas des échecs à masquer.

## Fichiers de preuve

| Fichier | Contenu |
|---|---|
| `gate-dataset-v2.txt` | Sortie du validateur canonique `validate_dataset_v2.py` (EXIT 2 = volume EN incomplet). |
| `tests-dataset-focalise.txt` | Suite `unittest` dataset-focalisée : 33 tests, OK, 0 skip. |
| `precheck-lot031.txt` | Précontrôle du dernier lot ingéré (m-118, m-121) + note d'honnêteté sur le refus idempotent après ingestion. |
| `inventaire-paires.txt` | Table des 139 cas : statut, catégorie, abstention, document+span, question. |
| `revues/revue-precommit-lot0{1..6}-*.txt` | Verdicts BRUTS des 6 relecteurs indépendants pré-commit (lots 05/06 = détection du doublon). |
| `revues/*` (antérieurs) | Verdicts bruts des revues initiales (m-004..m-030). |
| `SHA256SUMS-dataset-v2` | Empreintes de tous les fichiers de preuve + snapshot du dataset. |

Les fichiers `revues/*` sont des **sorties brutes de relecteurs** : evidence,
ne pas éditer.

## Limites

- Aucune métrique recall/MRR/abstention mesurée ici.
- Corpus privé réel absent : pas de mesure de qualité privée.
- Un gate `pending=0` prouve l'état du fichier courant, pas l'existence d'une
  preuve de revue — celle-ci est conservée dans `revues/`.
- Volume EN à 99/100 : une question EN propre reste à ajouter pour atteindre READY.
