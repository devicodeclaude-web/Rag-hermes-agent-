# G1 — ingestion hybride dans Qdrant (tranche CPU)

`QdrantChunkRepository` accepte un rappel optionnel `embed_hybrid` en plus de
`embed`. Quand il est fourni :

- le constructeur exige un appelable et lance `verify_collection_ready(...,
  require_sparse=True)` : une collection sans vecteur sparse nommé fait échouer
  l'instanciation plutôt que la première écriture ;
- `replace_document` encode chaque passage une seule fois
  (`dense, sparse = embed_hybrid(chunk.text)`) et écrit les deux vecteurs via
  `chunk_to_point(..., sparse_weights=...)`. L'identifiant de point et le
  payload restent **identiques** à ceux du chemin dense : seul le champ
  `vector` gagne l'entrée `sparse`. L'ordre des écritures ne change pas (upsert
  de la nouvelle révision, puis suppression des points périmés).

Sans `embed_hybrid`, le chemin dense historique et ses appelants sont
inchangés.

## Barrière de provenance (les deux chemins)

Les chunks sont fournis par l'appelant d'ingestion, pas calculés par le dépôt.
Avant toute écriture, `replace_document` refuse (`ValueError`) tout chunk dont :

- le type n'est pas exactement `Chunk` ;
- un champ d'ACL/provenance (`document_id`, `tenant_id`, `owner_id`,
  `visibility`, `allowed_groups`, `allowed_users`, `classification`,
  `doc_version`, `acl_version`, `source_uri`) diffère du document — en valeur
  **et** en type, pour qu'un substitut vrai-ish (`1` vs `True`, liste vs
  tuple) ne passe pas ;
- `source_sha` ne vaut pas le SHA-256 du contenu du document ;
- les bornes `start_offset`/`end_offset` ne sont pas des entiers vrais avec
  `0 <= start < end <= len(content)` ;
- `content[start_offset:end_offset]` ne reproduit pas exactement `text`.

Les deux dernières règles sont nécessaires : un hash qui porte sur le document
entier ne détecte PAS un texte de passage forgé, et des bornes négatives ou
inversées découperaient silencieusement autre chose (ou rien). Un chunk refusé
l'est **avant** l'upsert ; aucun appel `upsert`/`delete_points` n'est émis.

## Limites

Les tests utilisent un faux client Qdrant et un faux encodeur : aucun Qdrant
réel, aucun BGE-M3, aucun GPU n'est exercé ici. Cette tranche ne démontre pas
le retrieval hybride, la fusion RRF, le reranking, ni une quelconque qualité
G1 ; le service G1 ne branche pas encore `embed_hybrid` sur un vrai encodeur.
La barrière de provenance vérifie la cohérence chunk↔document fourni : elle ne
prouve pas que ce document correspond à la source documentaire d'origine.
