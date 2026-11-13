# G1 — ingestion hybride dans Qdrant (tranche CPU)

`QdrantChunkRepository` accepte un rappel optionnel `embed_hybrid` en plus de
`embed`. Quand il est fourni :

- le constructeur exige un appelable et lance `verify_collection_ready(...,
  require_sparse=True)` : une collection sans vecteur sparse nommé fait échouer
  l'instanciation plutôt que la première écriture. Le nom de collection est
  normalisé (`strip`) une seule fois, pour que la collection vérifiée soit
  exactement celle où l'on écrit ;
- `replace_document` encode chaque passage une seule fois
  (`dense, sparse = embed_hybrid(chunk.text)`) et écrit les deux vecteurs via
  `chunk_to_point(..., sparse_weights=...)`. L'identifiant de point et le
  payload restent **identiques** à ceux du chemin dense : seul le champ
  `vector` gagne l'entrée `sparse`. L'ordre des écritures ne change pas (upsert
  de la nouvelle révision, puis suppression des points périmés) ;
- un rappel qui ne renvoie pas un couple `(dense, sparse)` (tuple, liste ou
  `NamedTuple` de longueur 2), ou qui renvoie `sparse=None`, est refusé : en
  mode hybride, un point dense-seul serait une écriture silencieusement
  incomplète dans une collection provisionnée pour les deux vecteurs.

Sans `embed_hybrid`, le chemin dense historique et ses appelants sont
inchangés (aucune lecture de métadonnées de collection).

## Barrière de provenance (les deux chemins)

Les chunks sont fournis par l'appelant d'ingestion, pas calculés par le dépôt.
`replace_document` fige d'abord un instantané des faits du document
(`_DocumentSnapshot`), puis contrôle **deux fois** :

1. **avant l'encodage**, chaque chunk — pour qu'un passage étranger ne soit
   même pas envoyé à l'encodeur ;
2. **avant l'upsert**, le point sérialisé lui-même (aller-retour
   `json.dumps`/`json.loads`, `allow_nan=False`) — c'est-à-dire exactement ce
   que Qdrant stockera, payload et vecteurs compris.

Un chunk ou un point est refusé (`ValueError`) si :

- le type n'est pas exactement `Chunk` ;
- un champ textuel n'est pas exactement `str`, ou un champ entier exactement
  `int` (ni `bool`, ni sous-classe) ;
- un champ d'ACL/provenance (`document_id`, `tenant_id`, `owner_id`,
  `visibility`, `allowed_groups`, `allowed_users`, `classification`,
  `doc_version`, `acl_version`, `source_uri`) diffère de l'instantané ;
- `source_sha` ne vaut pas le SHA-256 du contenu du document, ou
  `content_hash` n'est ni vide ni ce même SHA-256 (c'est la règle que la
  barrière ACL canonique applique déjà à la lecture : accepter autre chose à
  l'écriture empoisonnerait l'index) ;
- les bornes `start_offset`/`end_offset` ne vérifient pas
  `0 <= start < end <= len(content)` ;
- `content[start_offset:end_offset]` ne reproduit pas exactement `text` ;
- deux chunks produisent le **même identifiant de point** (ils s'écraseraient
  l'un l'autre alors que `chunk_count` annoncerait les deux) ;
- l'identifiant de point n'est pas celui que `stable_point_id` dérive de
  l'identité vérifiée (c'est lui qui décide quel point stocké est remplacé) ;
- le vecteur dense n'est pas une liste non vide de nombres finis, ou sa
  dimension ne correspond pas à celle de la collection vérifiée (mode
  hybride) ; le vecteur sparse doit porter des indices uint32 uniques et des
  poids finis strictement positifs, en nombre égal aux indices.

Pourquoi ces règles, et pas de simples comparaisons `!=` :

- un hash qui porte sur le document entier ne détecte **pas** un texte de
  passage forgé, et des bornes négatives ou inversées découperaient
  silencieusement autre chose (ou rien) ;
- une sous-classe de `str` qui surcharge `__eq__`/`__ne__` se compare égale au
  document tout en sérialisant un autre identifiant d'ACL : d'où le contrôle
  de type exact, y compris **sur les éléments** des listes d'ACL ;
- le payload est construit **après** le rappel d'encodage, à partir de
  conteneurs qui appartiennent encore à l'appelant : un rappel qui élargit la
  liste ACL partagée en cours de route produirait un point plus permissif que
  celui validé. L'instantané pris avant l'encodage et la revalidation du point
  sérialisé ferment ce décalage. C'est aussi le point **validé** (la projection
  JSON) qui est envoyé à Qdrant, pas l'objet d'origine ;
- la vérification de propriété du document s'appuie sur l'instantané, et
  `replace_document` exige un vrai `Document` : sinon un objet sosie dont
  `owner_id` change entre la vérification et la construction du payload passait
  le contrôle sur une valeur et écrivait l'autre (prise de contrôle du document
  d'un autre utilisateur, reproduite en revue).

## Identité de point liée au tenant (changement incompatible)

`stable_point_id` dérive désormais l'identifiant de
`tenant_id | document_id | chunk_id | source_sha | doc_version` (séparateur
`\x1f`). Avant, la clé n'était que `chunk_id:source_sha:doc_version` — et
`chunk_id` est lui-même un hash de `document_id`/`doc_version`/index/`source_sha` :
**deux tenants qui ingéraient le même document à la même version dérivaient le
même identifiant de point**, et le second upsert effaçait silencieusement les
passages du premier, alors que `replace_document` renvoyait son `chunk_count`
complet aux deux. `_assert_document_owner` ne voyait rien (son balayage est
filtré sur le tenant de l'appelant).

Conséquence opérationnelle : **les identifiants de point changent**. Un index
Qdrant existant doit être réingéré ; sinon les anciens points ne seront plus
reconnus comme la révision courante (ils seront supprimés par le balayage des
points périmés à la prochaine écriture du document).

Un refus intervient **avant** l'upsert : aucun appel `upsert`/`delete_points`
n'est émis (la vérification du propriétaire du document, elle, a déjà lu
l'index via `scroll`).

## Limites

Les tests utilisent un faux client Qdrant et un faux encodeur : aucun Qdrant
réel, aucun BGE-M3, aucun GPU n'est exercé ici. Cette tranche ne démontre pas
le retrieval hybride, la fusion RRF, le reranking, ni une quelconque qualité
G1 ; le service G1 ne branche pas encore `embed_hybrid` sur un vrai encodeur.

Le contrôle de dimension dense n'est automatique qu'en mode hybride (le
constructeur y lit les métadonnées de la collection). En mode dense seul, les
clients ne sont pas tenus d'exposer `get_collection` : l'appelant qui a déjà
lancé le prévol passe la taille vérifiée via `vector_size=` (c'est ce que fait
`build_service`). Sans cet argument, aucune dimension n'est confrontée.

Un encodeur qui renvoie un `numpy.ndarray` est refusé (`vector must be a
nonempty list or tuple of numbers`) : le point doit être sérialisable en JSON,
et la conversion est à la charge de l'appelant (`.tolist()`).

La barrière vérifie la cohérence chunk↔document **fourni** : elle ne prouve
pas que ce document corresponde à la source documentaire d'origine. Les champs
que le document ne permet pas de recalculer restent **attestés par le chunker,
non vérifiés** : `chunk_id` (seules sa non-vacuité et l'unicité du point
dérivé sont contrôlées), `section`, `token_count`, `tokenizer_name`,
`tokenizer_revision`. Un `chunk_id` forgé mais unique produit donc un point
dont l'identité n'est pas reproductible par le chunker ; il reste rattrapé par
le balayage de suppression des points périmés de la même paire (tenant,
document), mais la valeur elle-même n'est pas prouvée.
