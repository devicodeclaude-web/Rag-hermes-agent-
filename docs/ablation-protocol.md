# Protocole pré-inscrit — dataset v1 et ablations A/B/C

Statut : **gelé avant toute expérience A/B/C**.

## Révisions et artefacts

Chaque rapport doit contenir : `audited_commit`, date UTC, commande exacte,
code de sortie, versions Python/Qdrant, modèles et révisions, graine, SHA-256 du
présent protocole et SHA-256 du dataset. Un rapport sans ces champs est
invalide. Toute mesure doit appeler le pipeline de requête de production ; un
pipeline d'évaluation parallèle est interdit.

## Dataset v1

Le jeu décisionnel intermédiaire contient exactement 100 références et exclut
les sondes ACL. Catégories, dérivées du corpus réel :

- 25 questions simples ;
- 20 paraphrases ;
- 20 distracteurs proches ;
- 15 frontières de chunks ;
- 20 sans-réponse.

Le corpus étant actuellement monolingue anglais, aucune catégorie multilingue
n'est incluse. Les distracteurs sont minés avec BM25 lexical, jamais avec
BGE-M3. Les 20 % vérifiés manuellement constituent seulement un contrôle
initial ; leurs métriques sont publiées séparément. Aucune conclusion globale
de qualité n'est autorisée tant que les 100 références décisionnelles ne sont
pas validées ou arbitrées humainement.

## Métriques pré-déclarées

Pour chaque configuration et chaque cas : rang du premier pertinent,
Recall@1, Recall@3, Recall@10, MRR et nombre de paires refusées pour dépassement
de budget. Les agrégats incluent des intervalles de confiance bootstrap à 95 %
avec 10 000 réplications et graine `20260923`.

`nDCG@10` n'est calculé que pour un cas ayant plusieurs chunks pertinents avec
des gains de pertinence définis. Si chaque cas n'a qu'un pertinent, il est
exclu et le rapport doit écrire `ndcg_at_10: null` avec la raison
`single_relevant_redundant_with_mrr`.

## Seuils de décision (gelés avant résultats)

### Expérience A — ancien contre nouveau chunking

Même corpus, questions, retrieval, modèle et graine. Seul le chunking change.
Le nouveau chunking est retenu si :

- Recall@10 ne baisse pas de plus de 0,02 en valeur absolue ;
- MRR ne baisse pas de plus de 0,02 ;
- aucune paire n'est hors budget avec le nouveau chunking ;
- la borne basse bootstrap 95 % de la différence Recall@10 est >= -0,02.

### Expérience B — utilité du reranker

Même liste de candidats autorisés, comparaison avant/après reranking. Le
reranker est retenu si :

- Recall@10 ne baisse pas ;
- MRR augmente d'au moins 0,02 ;
- la borne basse bootstrap 95 % de la différence de MRR est > 0 ;
- aucune paire n'est hors budget.

### Expérience C — sécurité

Matrice obligatoire : tenants croisés, groupes, utilisateurs nominatifs,
clearance insuffisante et suffisante, champs ACL absents ou nuls, droit
révoqué, `acl_version` obsolète, visibilité publique. Chaque catégorie publie
son nombre d'essais et sa graine. Critère éliminatoire : zéro fuite observée.
Le rapport publie aussi la borne haute unilatérale approximative à 95 % par la
règle de trois, `3/N`; elle ne doit jamais être décrite comme un risque nul.

## Anti-circularité et revue

Les labels et distracteurs ne sont jamais produits par BGE-M3. Le statut de
revue humaine est explicite par cas (`pending`, `validated`, `arbitrated`). Les
métriques du sous-ensemble humainement vérifié sont isolées. Un contrôle de
20 cas n'est pas une validation du jeu complet.

## Arrêt et interprétation

Le run A40 reste suspendu. Aucun résultat historique ne peut être réinterprété
comme provenant de ce protocole. Échec d'environnement, preuve absente ou
code de sortie non nul donne le statut **BLOQUÉ**, jamais **FERMÉ**.
