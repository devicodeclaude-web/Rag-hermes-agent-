# Fiche de revue humaine — dataset v2 (lot de 20)

Statut : **modèle de travail**. Cette fiche organise la rédaction et la revue
des 20 premiers cas du dataset v2. Elle ne ferme pas le lot 3 : tant que les
100 références ne sont pas rédigées puis revues, aucune conclusion de qualité
n'est autorisée.

## Règle d'or anti-circularité

L'auteur des questions **ne regarde pas le corpus** au moment de rédiger. Il
écrit des questions qu'un utilisateur réel de Hermes poserait. La provenance de
chaque question est déclarée :

- `human_task_without_corpus_view` — question rédigée sans voir les documents ;
- `anonymized_real_user_question` — vraie question d'utilisateur, anonymisée.

Ce n'est **qu'après** la rédaction qu'un annotateur ouvre le corpus pour
identifier le passage pertinent (ou décider que la question est sans réponse).

## Pistes (condition expérimentale explicite)

- `en2en` : question **en anglais**, corpus anglais. BM25 y est une baseline
  valide.
- `fr2en` : question **en français**, même corpus anglais. Translingue ; BM25
  non comparable. Chaque cas FR reprend le `pair_id` de son équivalent EN et
  **le même passage** (on traduit la question, pas l'étiquette).

Cible : 100 cas `en2en`, dont 40 dupliqués en `fr2en` (donc 40 `pair_id`
complets). Ce lot en couvre 20 (par ex. 20 EN, dont 8 avec paire FR).

## Composition visée du lot de 20

| catégorie              | but                                              | ~n |
|------------------------|--------------------------------------------------|----|
| simple                 | réponse directe dans un document                 | 6  |
| paraphrase             | vocabulaire différent du document                | 4  |
| distracteur proche     | sujet voisin, un seul document réellement bon    | 4  |
| frontière de chunk     | passage à cheval entre deux chunks probables     | 3  |
| sans réponse           | hors périmètre du corpus, abstention attendue    | 3  |

Les sondes ACL restent **hors** de ce dataset de qualité.

## Procédure par cas

1. **Rédiger** la question sans ouvrir le corpus. Noter la provenance.
2. **Annoter** : ouvrir le corpus, trouver le passage pertinent, en copier le
   **texte exact** (verbatim). Pour un cas sans réponse : aucun passage,
   remplir `unanswerable_reason`.
3. **Enregistrer** avec l'outil (calcule offsets + SHA-256, valide le schéma) :

   ```
   .venv-audit/bin/python scripts/annotate_eval_case.py --case cas.json
   ```

4. **Revue** : un second relecteur vérifie que la question est naturelle, que le
   passage répond bien, et passe `reference_status` de `pending` à `validated`
   (ou `arbitrated` en cas de désaccord tranché).
5. **Contrôler le lot** :

   ```
   .venv-audit/bin/python scripts/validate_dataset_v2.py
   ```

## Gabarit d'un cas (JSON à remplir)

```json
{
  "case_id": "q-001-en",
  "pair_id": "q-001",
  "question": "…question rédigée sans voir le corpus…",
  "language": "en",
  "track": "en2en",
  "category": "simple",
  "access_scope": "public",
  "question_provenance": "human_task_without_corpus_view",
  "should_abstain": false,
  "unanswerable_reason": null,
  "reference_status": "pending",
  "relevant_passages": [
    {
      "document_id": "hermes-agent:…",
      "passage_text": "…texte exact copié du document…",
      "relevance_grade": 2
    }
  ]
}
```

- `relevance_grade` : `2` = passage central, `1` = pertinent secondaire.
- Cas sans réponse : `"should_abstain": true`, `"relevant_passages": []`,
  `"unanswerable_reason": "outside_corpus_scope"` (ou motif précis).
- Cas FR apparié : copier le cas EN, changer `case_id`/`language`/`track` et
  **traduire uniquement `question`** ; garder le même `pair_id` et les mêmes
  `relevant_passages`.

## Tableau de suivi de la revue (à remplir)

| case_id | pair_id | track | catégorie | rédigé | annoté | relu | statut    |
|---------|---------|-------|-----------|--------|--------|------|-----------|
| q-001-en| q-001   | en2en | simple    |        |        |      | pending   |
| q-001-fr| q-001   | fr2en | simple    |        |        |      | pending   |
| …       |         |       |           |        |        |      |           |

## Ce que ce lot ne prouve pas

- 20 cas ne suffisent à aucune conclusion de performance : c'est un contrôle
  initial, pas une validation du jeu.
- La revue des 100 références reste requise avant toute décision.
- Le corpus privé réel est absent : aucune mesure de qualité privée ici.
