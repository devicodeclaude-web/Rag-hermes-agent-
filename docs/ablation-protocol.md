# Protocole pré-inscrit — dataset v1 et ablations A/B/C

Statut : **gelé avant toute expérience A/B/C**.

## Révisions et artefacts

Chaque rapport doit contenir : `audited_commit`, date UTC, commande exacte,
code de sortie, versions Python/Qdrant, modèles et révisions, graine, SHA-256 du
présent protocole et SHA-256 du dataset. Un rapport sans ces champs est
invalide. Toute mesure décisionnelle A/B/C doit appeler le pipeline de requête
de production ; un pipeline d'évaluation parallèle ne peut jamais ouvrir un
gate de production.

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

## Campagne intermédiaire humaine 154 — abstention BGE-M3

Cette extension est gelée avant son exécution GPU. Elle utilise les 154 cas de
`data/benchmark/dataset-v2-human-154.jsonl` : 107 EN, 47 FR, 122 répondables et 32 cas
d'abstention. Les 154 questions sont de provenance humaine indépendante du
corpus et portent un statut `validated` ou `arbitrated`.

Cette campagne est explicitement une étude de composants en mémoire : elle
exerce l'embedder, la fusion hybride, le reranker, la barrière ACL canonique et
le seuil d'abstention, mais pas Qdrant ni le chemin de requête de production.
Ses métriques de passages et d'abstention sont intermédiaires et ne peuvent pas
être réinterprétées comme une validation end-to-end du service.

Le seuil d'abstention du reranker n'est jamais choisi sur l'ensemble des 154
cas. Les groupes sont définis par `pair_id` (repli sur `case_id`) afin qu'une
paire EN/FR reste d'un seul côté. L'affectation est déterministe : parité du
SHA-256 de `bge-m3-abstention-v1:<group_id>`.

Partition figée avant calcul GPU :

- calibration : 81 cas — EN 47 répondables + 8 abstentions ; FR 22 + 4 ;
- holdout : 73 cas — EN 38 répondables + 14 abstentions ; FR 15 + 6.

Sur la calibration uniquement, les seuils candidats sont les frontières
induites par les scores observés. Le seuil maximise la balanced accuracy
(moyenne du rappel d'abstention et du rappel de réponse) ; en cas d'égalité, le
seuil le plus bas est retenu afin de limiter les abstentions excessives. Le
seuil est ensuite appliqué une seule fois au holdout, globalement et par piste.
Les deux rappels sont accompagnés d'intervalles de Wilson bilatéraux à 95 %.
Le seuil fixe historique 0,5 reste un diagnostic séparé et ne constitue pas le
résultat confirmatoire.

Le rapport doit enregistrer le commit Git complet vérifié contre un checkout
propre. Le reçu autonome est l'unique artefact consommable : il est publié
atomiquement après la fin du processus et embarque le rapport complet sous
`report`, la commande exacte, les variables non secrètes, le code de sortie et
le SHA-256 de `receipt.report` encodé en JSON canonique UTF-8. Le chemin de
rapport fourni au runner n'est qu'un staging non consommable, toujours supprimé
par le lanceur. Le rapport embarqué enregistre aussi le SHA du dataset et du protocole,
les révisions des modèles, les partitions par cas, `rejected_pairs` et les
métriques holdout. Tant
que la frontière interne de `FlagReranker.compute_score` n'est pas instrumentée,
`truncated_pairs` doit rester `null` avec la limite explicitée ; le précontrôle du
tokenizer externe ne permet pas d'affirmer zéro troncature interne. Ce run
constitue une preuve intermédiaire ; il ne peut pas ouvrir le gate final de 300
cas.

## Arrêt et interprétation

Aucun résultat historique ne peut être réinterprété comme provenant de cette
extension 154. Échec d'environnement, preuve absente, paire hors budget ou
code de sortie non nul donne le statut **BLOQUÉ**, jamais **FERMÉ**.
