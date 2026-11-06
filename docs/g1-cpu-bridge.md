# G1 — première tranche CPU : seconde barrière ACL

`CanonicalAclSearch` (`rag_hermes/retrieval.py`) enveloppe un dépôt classant ses
résultats via `search(question, context=..., limit=...)`. Configuré comme
`repository` de `RagService`, il réévalue **avant génération et citations** les
candidats contre `CanonicalAclAuthority` et leur ACL indexée. Pour tout candidat
autorisé, il exige une source canonique de `Document` **indépendante de l'index**
(`source(document_id)`) et compare locataire, ACL, version documentaire, hash du
contenu, tranche de texte et URI. Sans source, il refuse les candidats autorisés.
Une version ACL périmée **observée par le pont** est écartée ; si aucun
autre passage autorisé n'atteint le seuil de score, le parcours lève
`PermissionError` plutôt que de compter une abstention honnête. Le pont élargit
la requête classée en cas de candidats rejetés (budget de 128) ; si le budget
est saturé, il échoue fermé. Le `minimum_score` du pont doit être identique à
celui du service (vérifié à la construction). Un payload contradictoire avec
la politique canonique échoue explicitement **s'il est retourné par le dépôt**
et si la politique autorise le demandeur ; un candidat refusé observé ne peut
pas bloquer un document légitime classé juste après lui.

Le test `tests/test_g1_canonical_bridge.py` exerce sur CPU : requête Qdrant
préfiltrée (client simulé), seconde barrière, réponse factice `[S1]` et citation
limitée au document autorisé. Le client simulé vérifie **la transmission** du
filtre à Qdrant, pas son application réelle. Il vérifie aussi un candidat
inter-tenant, une ACL périmée, un payload contradictoire et un texte/URI/version
forgés. Aucune inférence GPU ni score de qualité n'est impliqué.

Ce n'est **pas encore G1 complet** : la source de candidats R3 dense+sparse,
le reranking verrouillé, le mapping explicite des statuts terminaux
`answered` / `abstained` / `acl_error` / `backend_error`, la provenance des
identifiants de chunks et le reçu de campagne restent à câbler et à tester.
Le résolveur canonique des tests est une source locale factice ; le brancher à
un vrai stockage documentaire fiable et exercer Qdrant réel sont préalables
à une garantie de production. Attention : un candidat écarté **en amont** par
le préfiltre Qdrant ou par `QdrantChunkRepository` est invisible pour ce pont ;
il peut masquer une ACL périmée ou une contradiction et produire une abstention
ordinaire. Le préfiltre transmis n'est donc pas une preuve de complétude du
contrôle ACL ni de la classe `abstained`. Avant d'utiliser ce statut comme
mesure d'évaluation G1, il faut un chemin vérifiable des candidats rejetés en
amont ou une porte d'intégrité de l'index indépendant. La V1 existante garde
son comportement ; la barrière n'est activée que lorsqu'un client l'enveloppe
explicitement.
