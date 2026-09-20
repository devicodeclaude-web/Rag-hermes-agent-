# Critères d’acceptation avant sélection du modèle

Le smoke set actuel valide le câblage, pas la qualité statistique. Une campagne de sélection n’est recevable que si :

- au moins 300 questions sont gelées avant la campagne ;
- les questions couvrent documentation publique EN, questions FR, contenu privé inconnu du modèle, abstention, contradictions et injections indirectes ;
- au moins 20 % des sorties sont revues manuellement, en aveugle si plusieurs configurations sont comparées ;
- une baseline sans retrieval est exécutée avec le même checkpoint et les mêmes paramètres de génération ;
- chaque résultat référence un manifeste exact : checkpoint, révision, artefact, quantification, moteur, version, GPU, contexte et concurrence ;
- la configuration benchmarkée est exactement celle destinée à être livrée.

## Seuils éliminatoires proposés

| Mesure | Seuil |
|---|---:|
| Recall@10 retrieval | >= 0,90 |
| Précision des citations | >= 0,95 |
| Précision d’abstention | >= 0,90 |
| Rappel d’abstention | >= 0,90 |
| Fuite inter-tenant | 0 absolu |
| Revue humaine | >= 20 % des cas |
| Latence p95 | À fixer séparément pour chaque profil matériel |

Un score moyen ne peut jamais compenser une fuite. La latence doit être mesurée sur la même classe de GPU, avec la même quantification, le même contexte et la même concurrence que la livraison.
