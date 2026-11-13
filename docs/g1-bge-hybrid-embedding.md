# G1 — encodage dense+sparse BGE-M3 (tranche CPU)

`LockedBgeM3Embedder.embed_hybrid(text)` appelle une seule fois le modèle
BGE-M3 épinglé : `return_dense=True`, `return_sparse=True` et
`return_colbert_vecs=False`. La méthode exige exactement une ligne dense de
la dimension verrouillée et un lot sparse d'une seule correspondance
`lexical_weights` (pas une correspondance utilisée comme lot) ; elle refuse
les lignes denses non numériques (y compris dictionnaires/octets), les valeurs
non finies, celles qui débordent en float32 ou dont un élément non nul devient
zéro après conversion. Les valeurs denses rendues sont **arrondies en float32** :
une valeur Python légèrement supérieure au maximum float32 peut être acceptée
si elle s'arrondit vers une valeur finie ; il ne s'agit pas d'une garantie de
représentabilité exacte du flottant d'entrée. Les poids
sparse passent par le contrat `lexical_weights_to_sparse_vector` (IDs uint32
uniques et poids dont la conversion float32 reste positive et finie), puis
reviennent sous forme de correspondance triée par ID décimal. Le résultat est
compatible avec `chunk_to_point(..., sparse_weights=...)`. Contrairement aux
valeurs denses, les poids sparse renvoyés ne sont pas arrondis explicitement :
Qdrant déterminera leur représentation effective lors de l'écriture.

Les tests utilisent un faux modèle et un tableau NumPy pour exercer le format
des sorties, y compris la production des deux vecteurs depuis le même appel.
Aucun modèle BGE-M3 réel ni GPU n'est lancé dans cette tranche. Le dépôt Qdrant
et le service G1 n'appellent pas encore `embed_hybrid` ; ce code ne démontre ni
l'ingestion du corpus, ni le retrieval hybride/RRF, ni la qualité G1. Le chemin
`embed()` dense historique et ses appelants restent inchangés.
