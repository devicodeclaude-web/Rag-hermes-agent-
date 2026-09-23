# Autorité ACL effectivement implémentée

Lecture du code effectuée avant modification de la seconde barrière.

PostgreSQL n'est pas présent dans ce dépôt : aucun schéma, client ou accès
PostgreSQL n'y définit les droits. L'autorité effectivement implémentée est
`CanonicalAclAuthority` dans `rag_hermes/acl_authority.py`. Il s'agit d'un
registre Python en mémoire construit à partir des métadonnées ACL des objets
`Document` : tenant, visibilité, propriétaire, groupes, utilisateurs,
classification et `acl_version`.

Le payload ACL Qdrant est un index dérivé. Le chemin de production applique le
filtre Qdrant avant retrieval, puis revérifie les candidats obtenus contre
`CanonicalAclAuthority` avant le reranking. Une version différente est refusée
avec le motif `stale_acl_version`; un document absent de l'autorité est refusé.

Limite : cette autorité canonique n'est pas persistante et n'est pas un service
externe partagé. La matrice locale prouve le comportement du registre en
mémoire et de Qdrant local, pas la cohérence d'une autorité déployée ni un
risque de fuite nul.
