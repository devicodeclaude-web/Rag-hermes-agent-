# Recherche hybride — contrat exact

Le terme « recherche hybride » désigne ici le chemin de production partagé par
le runner GPU, pas une simple concaténation informelle de scores.

- Stockage dense : vecteurs `float32` BGE-M3 en mémoire dans le smoke actuel ;
  le champ Qdrant cible est le vecteur nommé `dense`.
- Stockage sparse : dictionnaires `lexical_weights` BGE-M3 en mémoire dans le
  smoke actuel. Ils ne sont pas encore persistés dans Qdrant ; cette limite
  interdit de présenter le smoke comme une validation hybride Qdrant.
- Liste dense : 40 meilleurs chunks autorisés.
- Liste sparse : 40 meilleurs chunks autorisés.
- Fusion : weighted Reciprocal Rank Fusion, `k=60`, poids dense `1.0`, poids
  sparse `1.0`.
- Déduplication : union par `chunk_id` avant la coupe finale.
- Reranker : au plus 20 candidats issus de la fusion.

Ces paramètres sont explicites dans
`manifests/gpu/bge-m3-smoke-rtx4090.json`. L'implémentation commune est
`rag_hermes.retrieval.hybrid_rrf_indices`; le runner de mesure l'appelle au
lieu de réimplémenter le calcul.

Limite connue : le smoke GPU historique stockait dense et sparse uniquement en
mémoire et n'exerçait pas Qdrant. Tant que les deux représentations ne sont pas
persistées et requêtées dans Qdrant par le chemin de production, la preuve porte
sur l'algorithme hybride en mémoire, pas sur un déploiement hybride complet.
