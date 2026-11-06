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

Un second contrôle CPU (`rag_hermes/index_integrity.py`) compare les points
d'un **scroll non filtré et paginé** à la liste complète des chunks canoniques
fournie indépendamment de Qdrant. Il échoue si un point manque, est en trop,
est dupliqué ou si son payload/ACL diffère ; il détecte ainsi un `owner_id`
indexé trop restrictif qu'une requête préfiltrée n'aurait pas retourné. Le
scroll sans filtre (`QdrantAuditRestClient.scroll_page`) est destiné au seul
auditeur hors du chemin des requêtes utilisateur ; la séparation en classes
n'est **pas** une autorisation réseau. Utiliser des droits/identifiants
opérateur distincts et ne pas exposer ce client à l'API publique. L'audit
compare les payloads et IDs (types JSON inclus), **pas les vecteurs**.
Tests avec faux clients uniquement : aucune collection Qdrant réelle n'a été
auditée.

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
mesure d'évaluation G1, il faut une exécution réussie de l'audit complet sur
le **même index figé** pendant la campagne (ou une trace vérifiable des rejets
en amont). La fonction d'audit n'authentifie pas à elle seule la provenance du
manifeste et ne verrouille pas les écritures Qdrant : sans ces préconditions,
son succès CPU n'est pas un reçu G1. La V1 existante garde son comportement ;
la barrière n'est activée que lorsqu'un client l'enveloppe explicitement.
