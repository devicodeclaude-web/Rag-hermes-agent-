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
points retournés, ni le câblage R3 : le dépôt et le service G1 restent sur le
chemin dense, sans fusion RRF ni reranking branchés. Les résultats bruts sparse
ne peuvent pas être exposés sans réconciliation ACL/provenance canonique.
