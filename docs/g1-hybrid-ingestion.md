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
  `vector` gagne l'entrée `sparse`. L'ordre des écritures est : upsert
  conditionnel de la nouvelle révision, relecture des IDs écrits, puis
  suppression des seuls anciens IDs réellement vus lors du scan complet ;
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
`tenant_id | document_id | chunk_id | source_sha | doc_version`, chaque partie
étant **préfixée par sa longueur** pour que l'encodage soit injectif : un
simple séparateur déplacerait la frontière entre deux champs dès qu'un champ
le contient lui-même (`document_id` vient du client), ce qui ramène
exactement l'écrasement silencieux ci-dessous. En défense en profondeur,
`document_id`, `tenant_id`, `owner_id` et `chunk_id` sont refusés s'ils
contiennent un caractère de contrôle Unicode (catégorie `Cc`, C0, DEL et C1).
Avant, la clé n'était que `chunk_id:source_sha:doc_version` — et
`chunk_id` est lui-même un hash de `document_id`/`doc_version`/index/`source_sha` :
**deux tenants qui ingéraient le même document à la même version dérivaient le
même identifiant de point**, et le second upsert effaçait silencieusement les
passages du premier, alors que `replace_document` renvoyait son `chunk_count`
complet aux deux. `_assert_document_owner` ne voyait rien (son balayage est
filtré sur le tenant de l'appelant).

Conséquence opérationnelle : **les identifiants de point changent**. Un index
Qdrant existant doit être réingéré ; sinon les anciens points ne seront plus
reconnus comme la révision courante (ils seront supprimés s'ils sont présents
parmi les anciens IDs lus jusqu'au curseur terminal lors de la prochaine
écriture du document).

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

`replace_document` exige le type exact `Document` (une sous-classe pourrait
redéfinir l'accès aux attributs et réouvrir le décalage ci-dessus) ; une
extension doit composer, pas hériter. La liste de chunks doit contenir au
moins un passage : les deux chunkers peuvent rendre `[]` sur un document vide
ou blanc, et cette liste n'est **jamais** interprétée comme une suppression.
`RagService.import_document` refuse également une importation sans passage,
y compris sur son dépôt en mémoire. `chunk_document_tokens` lève aussi si une
entrée tokenisée ne produit aucune fenêtre de largeur positive, mais cette
garde seule ne ferme pas les sorties `return []` en amont. Il n'existe pas
encore d'API de suppression explicite dans ce dépôt. La contre-revue a
reproduit deux dangers qui empêchent de l'exposer : le contrôle du propriétaire
ne prouvait pas la complétude au-delà de la première page du `scroll` Qdrant
(défaut corrigé par cette tranche : le contrôle suit désormais le
`next_page_offset` jusqu'à `null`, dans une limite de 100 000 points et refuse
les réponses/cursors incohérents). Les clients Qdrant injectés par les
appelants doivent désormais implémenter
`scroll_filtered_page(collection, *, query_filter, limit, offset)` et renvoyer
`(points, next_page_offset)` ; l'ancien `scroll(...)` qui ne renvoie que des
points n'est plus accepté pour un remplacement, car il ne prouve pas la
complétude. Les anciens adaptateurs doivent migrer ou échouer explicitement
avant toute écriture. Avec Qdrant **1.19.0** (version fixée en CI), le client
REST transmet `update_filter` sur l'upsert : les points déjà présents qui ne
correspondent pas à `(tenant_id, document_id, owner_id)` sont laissés intacts.
Chaque champ est aussi exclu s'il contient une **autre** valeur (`must_not` +
`match.except`) : Qdrant fait correspondre `match.value` à un élément de tableau,
mais un tableau `owner_id: ["alice", "bob"]` correspond aussi à `match.except:
["alice"]`, donc ne peut plus être écrasé par Alice. Ce contrôle est appliqué
également au filtre de suppression des anciens IDs ; les tableaux ne contenant
que la valeur attendue restent possibles et ne constituent pas une preuve de
type scalaire. Qdrant ne signale pas les points ignorés ; `replace_document`
exige d'abord `result.status: completed` (un `wait_timeout` n'autorise jamais
une suppression),
puis relit les IDs demandés par `retrieve_points(collection, ids)` après
l'upsert avec `with_payload: true` et `with_vector: true`, et refuse un ID,
payload ou vecteur manquant, étranger ou incohérent **avant toute suppression**.
Le vecteur dense est comparé aux valeurs attendues ; leur normalisation
Cosine (float32 toléré, tolérance relative seulement) n'est admise que si la
distance `Cosine` et le stockage `float32` (ou l'absence de `datatype`, valeur
par défaut) sont vérifiés dans les métadonnées avant le remplacement ; le
prévol hybride impose déjà ces paramètres. Une collection dense `float16` ou
`uint8` est refusée **avant tout upsert**, plutôt que d'écrire puis d'échouer
sur la quantification non représentable à cette tolérance. Sans
`get_collection` sur un client dense injecté, seule l'égalité numérique sans
normalisation est admise : une collection Cosine derrière cet adaptateur doit
exposer les métadonnées pour que le remplacement réussisse. Le sparse est
comparé par indice indépendamment de l'ordre. Le client injecté doit
implémenter cette relecture et accepter `update_filter=` sur
`upsert(...)` ; adapter les anciens clients (pas de repli non conditionnel).

La suppression utilise un filtre contenant **uniquement les IDs périmés vus
pendant le scan complet** (`has_id`), conjointement aux prédicats tenant,
document et propriétaire. Quand il n'y a aucun ancien ID périmé, aucune
suppression n'est émise ; sinon `result.status: completed` est exigé avant de
retourner un succès. Ainsi un point apparu avec un *nouvel* ID après le
scan, même avec un `owner_id` en tableau, n'entre plus dans la suppression.

**Barrière mono-hôte entre écrivains coopérants, PAS une transaction Qdrant.**
`replace_document` prend un `fcntl.flock` exclusif par `(collection, tenant_id,
document_id)` avant le prévol de métadonnées et le scan, et le conserve pendant
l'encodage, l'upsert conditionnel, la relecture et la suppression. Tous les
processus doivent utiliser le **même répertoire sur un système de fichiers local**
et le même UID : `RAG_QDRANT_LOCK_DIR=/chemin/absolu/prive` dans `build_service`
(ou `lock_dir=` dans `QdrantChunkRepository`). Par défaut, c'est
`~/.local/state/rag-hermes/qdrant-locks` pour ce compte utilisateur. Le
répertoire doit être privé (pas d'accès groupe/autres), possédé par l'UID du
processus et non symbolique ; les fichiers de verrou sont privés, réguliers et
ne doivent **jamais être effacés ni remplacés** pendant que des écrivains
fonctionnent. Un chemin relatif ou une configuration de permissions dangereuse
échoue avant le scan/l'écriture. Après 30 secondes de contention (paramètre
`lock_timeout=` pour les appelants directs), l'opération échoue **sans commencer
le remplacement** ; le verrou est libéré aussi en cas d'exception.

`update_filter` ne rend toujours pas atomiques le scan et les mutations : un
écrivain qui parle directement à Qdrant, un autre UID/chemin, un autre hôte ou
conteneur non raccordé au **même verrou local** peut réutiliser un ID périmé
pendant le remplacement. Ce verrou consultatif ne protège que les processus
coopérants du même hôte ; il ne constitue **pas** un verrou distribué ni une
preuve de conservation durable face aux écrivains externes. La politique de
tombstone/suppression explicite reste à définir et l'API de suppression n'est
pas exposée. Garder #71 ouverte jusqu'à la revue indépendante et l'intégration
Qdrant réelle de cette tranche.

Un encodeur qui renvoie un `numpy.ndarray` est refusé (`vector must be a
nonempty list or tuple of numbers`) : le point doit être sérialisable en JSON,
et la conversion est à la charge de l'appelant (`.tolist()`).

La barrière vérifie la cohérence chunk↔document **fourni** : elle ne prouve
pas que ce document corresponde à la source documentaire d'origine. Les champs
que le document ne permet pas de recalculer restent **attestés par le chunker,
non vérifiés** : `chunk_id` (seules sa non-vacuité, l'absence de caractère de
contrôle et l'unicité du point dérivé sont contrôlées), `section`,
`token_count`, `tokenizer_name`, `tokenizer_revision`. Un `chunk_id` forgé mais
unique produit donc un point dont l'identité n'est pas reproductible par le
chunker ; il reste rattrapé par le balayage de suppression des points périmés
de la même paire (tenant, document), mais la valeur elle-même n'est pas prouvée.
