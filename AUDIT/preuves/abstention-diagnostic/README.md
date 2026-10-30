# Diagnostic d'abstention — le signal lexical ne peut pas abstenir

## Verdict

**Résultat négatif, établi par les données.** Un seuil appliqué au signal lexical
(ratio de recouvrement des mots de la requête, ou score BM25 brut) **ne peut pas**
séparer les 32 cas hors corpus des 122 cas répondables sans détruire le Recall.
L'abstention correcte exige un signal sémantique (embeddings denses + reranker),
pas lexical.

Niveau de preuve : **intégration de composant** (chemin de retrieval réel sur le
corpus public de 461 documents, dataset humain validé de 154 cas). Ce n'est pas
une preuve de qualité held-out ; c'est une mesure diagnostique descriptive.

## Contexte

Le rapport BM25 (`code_revision 7638fc0`) donne `abstention_recall = 0` : le
système ne s'abstient jamais sur les 32 questions hors corpus. L'abstention est
décidée dans `RagService.answer_with_trace` : s'abstenir = aucun résultat dont
`effective_threshold_score >= minimum_score` (défaut 0,05).

Hypothèse testée : « il suffit de monter `minimum_score` ». Le diagnostic la
réfute.

## Données

Pour chaque cas, meilleur score parmi le top-10 récupéré (ACL appliquée).

### effective_threshold_score (ratio de recouvrement des termes de la requête)

| Population | n | min | p25 | médiane | p75 | max |
|---|---:|---:|---:|---:|---:|---:|
| Abstention (hors corpus) | 32 | 0,1250 | 0,4000 | 0,6307 | 0,7857 | 1,0000 |
| Répondable | 122 | 0,1818 | 0,3846 | 0,8516 | 0,9000 | 1,0000 |

Chevauchement massif : 37/122 répondables sont sous la médiane des abstentions
(0,6307) ; 5/32 abstentions sont au-dessus de la médiane des répondables (0,8516).

### BM25 brut

| Population | n | min | médiane | max |
|---|---:|---:|---:|---:|
| Abstention | 32 | 0,8970 | 0,9314 | 0,9543 |
| Répondable | 122 | 0,8506 | 0,9348 | 0,9812 |

Médianes quasi identiques : BM25 brut est encore moins séparant (attendu — une
question hors corpus partage du vocabulaire courant avec un gros corpus).

### Balayage de seuil (effective_threshold_score)

| Seuil | Abstentions correctes /32 | Répondables perdus /122 |
|---:|---:|---:|
| 0,05 | 0 | 0 |
| 0,10 | 0 | 0 |
| 0,15 | 1 | 0 |
| 0,20 | 1 | 1 |
| 0,25 | 4 | 6 |
| 0,30 | 7 | 15 |
| 0,40 | 8 | 31 |
| 0,50 | 10 | 35 |

Aucune zone où les abstentions correctes montent sans perte proportionnellement
plus grande de cas répondables. Pour récupérer 10 abstentions sur 32, il faudrait
sacrifier 35 cas répondables sur 122. Le compromis est défavorable à tous les
seuils.

## Interprétation

Le signal lexical mesure *combien de mots de la question apparaissent quelque part*,
pas *si un passage répond réellement à la question*. Une question hors corpus
(ex. « quelle constante lunaire Hermes prescrit-il ? ») partage « Hermes » et des
mots courants avec le corpus → recouvrement élevé, alors qu'aucun passage n'est
pertinent. Ce défaut est intrinsèque au lexical et ne se corrige pas par un
paramètre de seuil.

## Décision

Ne pas introduire de seuil lexical d'abstention : il dégraderait le Recall sans
bénéfice net. Le levier correct est le pipeline dense persistant (BGE-M3 sur GPU)
plus un reranker cross-encoder, qui portent un signal de pertinence sémantique.
Mesurer l'abstention sur ce pipeline, avec un seuil calibré sur un jeu distinct.

## Artefacts

- `separability-summary.txt` : sortie brute (stats + balayage de seuil) ;
- `per-case-scores.json` : score par cas pour les 154 cas (32 abstention, 122
  répondable) ;
- `SHA256SUMS` : empreintes des deux fichiers ci-dessus.

Reproduction : recherche top-10 via `RagService._search` sur le corpus public,
`minimum_score=0.0001` pour ne filtrer aucun candidat, mesure du meilleur
`effective_threshold_score` et `score` BM25 par cas. `code_revision 7638fc0`.

## Limites

1. Mesure descriptive sur le dataset complet (pas de jeu held-out ni d'intervalles
   d'incertitude).
2. FR→EN reste un diagnostic lexical non équitable.
3. Aucun embedding dense, reranker ou générateur exercé ici — précisément le
   point : ce diagnostic motive leur usage.
