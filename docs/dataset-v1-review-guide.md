# Revue humaine initiale — 20 questions du dataset v1

Fichier à remplir : `data/review/dataset-v1-initial-20.csv`. L'échantillon est
stratifié selon la composition du jeu : 5 simples, 4 paraphrases, 4
distracteurs proches, 3 frontières de chunks et 4 sans-réponse.

## Limite connue avant revue

Ces questions ne proviennent pas d'un chunk cible et les distracteurs ont été
minés lexicalement avec BM25, jamais avec BGE-M3. Toutefois, le document cible
a été choisi avant la rédaction et la question a été fabriquée principalement
à partir de son titre. Le jeu est donc fortement couplé à ses labels et ne doit
pas être considéré comme un jeu décisionnel indépendant sans réécriture et
validation humaines.

## Procédure

Pour chaque ligne, le réviseur humain doit lire le document proposé et le
distracteur BM25, puis renseigner :

- `reviewer_decision` : `validate`, `rewrite`, `reject` ou `arbitrate` ;
- `corrected_relevant_document_ids` : liste séparée par `;` ;
- `reviewer_name` ;
- `review_date_utc` ;
- `notes`, notamment la question réécrite si la décision est `rewrite`.

Une question n'est comptée comme contrôlée que si la décision, le nom et la
date sont présents. Les 20 lignes constituent un contrôle initial, pas une
validation du dataset. Aucune conclusion globale n'est permise tant que les
100 références ne sont pas validées ou arbitrées humainement.

## Interdictions

- Ne pas consulter les scores BGE-M3 ou du reranker pendant la revue.
- Ne pas valider une question parce que le document proposé contient simplement
  son titre.
- Ne pas transformer une question multilingue en cas sans-réponse déguisé.
- Ne pas inclure de sonde ACL dans ce dataset de qualité.
