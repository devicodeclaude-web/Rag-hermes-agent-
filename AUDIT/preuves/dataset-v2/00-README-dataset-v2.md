# Dossier d'audit — Dataset d'évaluation v2 (annotation manuelle)

Ce dossier rassemble les preuves vérifiables de la construction du jeu
d'évaluation `data/benchmark/dataset-v2.jsonl` (questions bilingues EN/FR,
annotées à la main selon un protocole anti-circularité).

## Niveau de preuve

Niveau **intégration de composant** (tooling d'annotation + validateur canonique
+ suite de tests). Ce n'est **pas** une preuve de qualité statistique ni de
production : aucune métrique de retrieval (recall/MRR/abstention) n'est mesurée
ici. Le volume cible est **atteint** : au moins 100 cas EN, 40 paires FR et
20 % d'abstentions dans chaque langue, gate `READY`.

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

- Total : **154 cas** — **107 EN** + **47 FR**, tous `validated`, 0 `pending`.
- Répondables : 122 cas ; abstention (`no_answer`, hors périmètre corpus) : 32 cas.
- Taux d'abstention : EN **22/107 = 20,6 %** ; FR **10/47 = 21,3 %**
  (minimum du gate : 20 % par langue).
- Gate canonique : `structural: valid`, `pending: 0`, `reviewed: 154`,
  `targets_met: true` → **EXIT 0 = READY** (volume cible atteint).
- Suite de tests dataset-focalisée : 39 tests, **OK**, 0 skip.

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

## Extension des abstentions à 20 % par langue

Sept paires hors-Hermes ont été ajoutées et validées (`m-123`, `m-124`,
`m-126` à `m-130`). La première revue indépendante a refusé `m-125` (question
sur la chute du mur de Berlin) : le corpus canonique contenait déjà la question
et sa réponse dans `productivity-memento-flashcards.md`. La paire a été retirée,
pas reformulée. Une nouvelle question humaine (`m-130`, botanique) a ensuite
fait l'objet d'une revue indépendante fraîche et a été validée.

Le validateur impose désormais `target_min_abstention_rate: 0.2` séparément sur
les tracks EN et FR. Le seuil est donc une propriété vérifiée du dataset, pas
seulement un constat ponctuel dans ce dossier.

## Fichiers de preuve

| Fichier | Contenu |
|---|---|
| `gate-dataset-v2.txt` | Sortie du validateur canonique `validate_dataset_v2.py` (EXIT 0 = READY, volume atteint). |
| `tests-dataset-focalise.txt` | Suite `unittest` dataset-focalisée : 39 tests, OK, 0 skip. |
| `tests-full-unit.txt` | Suite complète : 348 tests OK, 14 intégrations Qdrant ignorées car désactivées. |
| `precheck-lot031.txt` | Précontrôle du dernier lot ingéré (m-118, m-121) + note d'honnêteté sur le refus idempotent après ingestion. |
| `inventaire-paires.txt` | Table des 154 cas : statut, catégorie, abstention, document+span, question. |
| `revues/revue-precommit-lot0{1..6}-*.txt` | Verdicts BRUTS des 6 relecteurs indépendants pré-commit (lots 05/06 = détection du doublon). |
| `revues/revue-precommit-lot07-m122.txt` | Verdict BRUT de la revue du 100e cas EN (m-122, Ctrl+G → $EDITOR). |
| `revues/revue-extension-abstentions-m123-m129.txt` | Verdict BRUT fail-closed : six paires approuvées, m-125 bloquée car répondable dans le corpus. |
| `revues/revue-extension-abstention-m130.txt` | Verdict BRUT de la revue indépendante fraîche de la paire de remplacement m-130. |
| `revues/*` (antérieurs) | Verdicts bruts des revues initiales (m-004..m-030). |
| `SHA256SUMS-dataset-v2` | Empreintes de tous les fichiers de preuve + snapshot du dataset. |

Les fichiers `revues/*` sont des **sorties brutes de relecteurs** : evidence,
ne pas éditer.

## Limites

- Aucune métrique recall/MRR/abstention mesurée ici.
- Corpus privé réel absent : pas de mesure de qualité privée.
- Un gate `pending=0` prouve l'état du fichier courant, pas l'existence d'une
  preuve de revue — celle-ci est conservée dans `revues/`.
- Volume cible atteint (107 EN / 47 FR, au moins 20 % d'abstentions par langue,
  gate READY) ; la qualité statistique de
  retrieval reste à mesurer séparément.
