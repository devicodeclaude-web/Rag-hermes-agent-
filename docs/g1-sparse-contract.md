# G1 — contrat de vecteur sparse (tranche CPU)

Cette tranche prépare la représentation Qdrant des poids lexicaux BGE-M3, sans prétendre livrer R3 ni un index hybride opérationnel.

- `lexical_weights_to_sparse_vector` accepte une correspondance non vide
  `{token_id décimal: poids positif fini}` et produit les tableaux triés
  `indices` (entiers uint32 uniques) et `values` (flottants Python d'origine).
  Chaque poids est vérifié : sa conversion en float32 doit rester finie et non
  nulle, sans pour autant renvoyer la valeur arrondie en float32. Les clés
  ambiguës, poids booléens/chaînes/nuls/négatifs/infini/NaN, débordements et
  sous-flux *jusqu'à zéro* en float32 sont refusés.
- `chunk_to_point(..., sparse_weights=...)` peut placer `dense` et `sparse` sous le même ID de point, sans changer le payload ACL. Sans cet argument, le chemin dense historique reste inchangé.
- `QdrantRestClient.query_sparse` construit le préfiltre Qdrant depuis un `AuthorizationContext` validé ; l'appelant ne peut pas fournir un filtre arbitraire. Elle applique les mêmes contrôles d'enveloppe, de nombre de résultats et de scores que `query` dense. Ce préfiltre ne prouve pas l'autorisation ni la provenance du point retourné : un postfiltre et une réconciliation canoniques restent requis avant génération/citation. Les résultats bruts de cette méthode ne doivent pas être exposés à l'utilisateur.

Les tests exercent la sérialisation et la requête HTTP simulée en local. Aucun index Qdrant réel ni embedding GPU n'est exercé : la collection actuelle ne déclare que `dense`, le dépôt n'ingère pas encore les deux représentations, aucune fusion RRF ni reranking n'est reliée au service G1. Ces étapes sont nécessaires avant une campagne ou une revendication de qualité.
