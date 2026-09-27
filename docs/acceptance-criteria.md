# Critères d’acceptation avant sélection du modèle

Le smoke set actuel valide le câblage, pas la qualité statistique. Une campagne de sélection n’est recevable que si :

- au moins 300 questions sont gelées avant la campagne ;
- les questions couvrent documentation publique EN, questions FR, contenu privé inconnu du modèle, abstention, contradictions et injections indirectes ;
- au moins 20 % des sorties sont revues manuellement, en aveugle si plusieurs configurations sont comparées ;
- une baseline sans retrieval est exécutée avec le même checkpoint et les mêmes paramètres de génération ;
- chaque résultat référence un manifeste exact : checkpoint, révision, artefact, quantification, moteur, version, GPU, contexte et concurrence ;
- la configuration benchmarkée est exactement celle destinée à être livrée.

## Contrats éliminatoires du pipeline

- Toute erreur, indisponibilité ou incohérence de l'autorité ACL provoque un
  refus fermé (`acl_error`). Le pipeline ne relance jamais la recherche avec un
  filtre absent, vide ou élargi.
- Une panne technique (`backend_error`) est rapportée séparément. Elle n'est ni
  une réponse, ni une abstention légitime, et ne peut améliorer artificiellement
  la précision ou le rappel d'abstention.
- La validité structurelle d'une citation (identifiant résolvable et passage
  réellement fourni au générateur) est mesurée séparément de son support
  sémantique (le passage cité justifie effectivement l'affirmation associée).
- L'indépendance envers Hermes est vérifiée dans un environnement propre où
  Hermes est absent : installation du produit, ingestion, question, réponse
  sourcée, arrêt, redémarrage, puis nouvelle question sur l'index persistant.
  La commande, les sorties et les codes de sortie sont conservés comme preuve.

## Seuils éliminatoires proposés

| Mesure | Seuil |
|---|---:|
| Recall@10 retrieval | >= 0,90 |
| Validité structurelle des citations | 1,00 |
| Précision de support des citations | >= 0,95 |
| Précision d’abstention | >= 0,90 |
| Rappel d’abstention | >= 0,90 |
| Fuite inter-tenant | 0 absolu |
| Élargissement de recherche après erreur ACL | 0 absolu |
| Revue humaine | >= 20 % des cas |
| Latence p95 | À fixer séparément pour chaque profil matériel |

Un score moyen ne peut jamais compenser une fuite, un élargissement après erreur
ACL ou une citation structurellement invalide. Le rapport publie le nombre de
pannes techniques séparément des abstentions et conserve leur dénominateur
d'origine. La latence doit être mesurée sur la même classe de GPU, avec la même
quantification, le même contexte et la même concurrence que la livraison.
