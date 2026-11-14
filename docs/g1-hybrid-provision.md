# G1 — provisionnement opt-in dense + sparse

`QdrantRestClient.create_collection(..., sparse=True)` crée une collection avec
les vecteurs nommés `dense` (Cosine) et `sparse` (sans modificateur IDF,
avec stockage/index float32 par défaut). Le prévol hybride accepte aussi le
modificateur explicite `none` et refuse les datatypes `uint8`/`float16` :
ce contrat évite de modifier silencieusement les poids fournis, sans prouver
l'intégrité de leur provenance ni leur identité bit à bit après stockage.
`provision_collection(..., sparse=True)` garde les index de payload ACL requis,
refuse une collection dense seule déjà existante **avant toute création d'index**,
et vérifie la présence du vecteur sparse dans les métadonnées après création.
`verify_collection_ready(..., require_sparse=True)` permet un prévol en lecture
seule du même schéma. Les appels sans ces options gardent le contrat dense
historique ; il n'y a ni migration implicite ni modification de la collection
dense existante.

Un test d'intégration conditionné par `QDRANT_INTEGRATION_URL` tente une création
réelle, l'écriture d'un point dense+sparse et une requête sparse avec préfiltre
locataire. Sans serveur, il est ignoré ; la CI doit confirmer son exécution.
Ce test ne prouve ni l'intégrité des vecteurs du corpus, ni la provenance des
points retournés, ni le câblage R3 de bout en bout. `QdrantChunkRepository`
expose maintenant `hybrid_candidates` **uniquement si `embed_hybrid` est fourni** :
il encode la requête en un appel, interroge séparément les top-40 dense et sparse
avec le préfiltre ACL, valide les points bruts (ID/payload/score), déduplique par
ID et fusionne les rangs avec `1/(60+rang)` par voie. Les candidats refusés par
l'ACL du payload sont exclus avant `output_limit`. Le résultat est un
`HybridCandidate` avec score RRF brut, **pas** un `SearchResult` directement
consommable par `RagService` : un score RRF n'est pas un seuil d'abstention.
Une intégration Qdrant réelle est couverte en CI avec trois passages autorisés
et un tenant étranger, mais ni BGE-M3 ni le reranker n'y sont exécutés.

Le service G1 reste sur le chemin dense : l'autorité ACL et la provenance
canonique, le reranking, l'abstention calibrée et la génération citée ne sont
**pas** branchés sur ces candidats. Les résultats bruts sparse/RRF ne peuvent
pas être exposés à l'utilisateur sans ces barrières, et cette tranche ne prouve
pas une qualité de retrieval ni une campagne G1.
