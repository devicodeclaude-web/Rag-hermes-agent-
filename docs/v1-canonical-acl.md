# Autorité ACL canonique du chemin V1 (SEC-01)

Jusqu'à ce lot, `app_factory.build_service` passait un `QdrantChunkRepository`
**nu** à `RagService` : l'index Qdrant était alors sa propre autorité ACL. Un
payload d'index plus permissif que la politique réelle (bug d'ingestion,
réindexation partielle, écriture directe dans la collection) aurait été servi
sans contradiction possible. `CanonicalAclSearch` existait, mais n'était câblé
que sur les parcours d'évaluation G1.

Aucune fuite n'a été observée : le constat est un défaut de conception, classé
P0 avant tout déploiement multi-tenant.

## Ce qui est câblé

`rag_hermes/canonical_registry.py` fournit l'autorité manquante :

- `CanonicalDocumentRegistry` — registre documentaire local, persisté dans
  `<RAG_CANONICAL_STORE>/canonical_documents.jsonl` (append seul, dernière
  ligne d'un `document_id` faisant foi), **indépendant de Qdrant**. Il dérive la
  politique (`AclPolicy`) et sert de source de provenance (texte, offsets,
  `source_sha`, `source_uri`, versions) à la barrière.
- `CanonicalWriteThrough` — écrit la révision canonique **avant** l'index, et
  refuse une révision vide (une révision vide n'est pas une suppression).
- `wrap_repository_with_canonical_barrier` — assemble
  `CanonicalAclSearch(CanonicalWriteThrough(dépôt), registre.authority,
  source=registre.source)` avec le même `minimum_score` que le service.

`build_service` **refuse de démarrer** si `RAG_QDRANT_URL` est défini sans
`RAG_CANONICAL_STORE` (répertoire absolu existant), et refuse un
`RAG_RETRIEVAL_K` supérieur au budget de scan de la barrière (128) à la
construction plutôt qu'au milieu d'une requête.

## Contrôles stricts du registre

L'autorité compare en Python, où `True == 1` et où une sous-classe de `str`
peut surcharger `__eq__`/`__ne__`. Le registre impose donc des types
**absolus** (`type(x) is str` / `is int`, jamais `isinstance`), sur les
éléments des tuples d'ACL comme sur les conteneurs, refuse les entiers négatifs,
les champs d'identité vides ou porteurs de caractères de contrôle, et n'accepte
que des `Document` du type exact (pas de sous-classe). La relecture du fichier
est également stricte : aucune coercition `int()`/`tuple()` (contrairement à
`dataset._build_document`, acceptable pour un corpus de bench, pas pour une
autorité de sécurité).

Invariants rejoués à l'écriture **et** à la relecture, donc un fichier trafiqué
refuse le démarrage au lieu de servir une politique affaiblie :

- un `document_id` déjà enregistré par un **autre locataire** est refusé —
  l'autorité canonique indexe par `document_id` seul alors que le service
  indexe par `(tenant_id, document_id)` ; sans ce refus, la politique de l'un
  remplacerait celle de l'autre ;
- `doc_version` et `acl_version` ne peuvent pas **régresser** (anti-rejeu d'une
  ACL révoquée) ;
- l'`owner_id` d'un document ne peut pas **changer** (refus levé en
  `PermissionError`, rendu `403` par la couche HTTP). Ce refus est nécessaire
  *parce que* le registre écrit avant l'index : une tentative de reprise que le
  dépôt rejetterait ensuite laisserait sinon l'autorité canonique attribuer le
  document à l'usurpateur, et le vrai propriétaire se verrait refuser ses
  propres passages. La V1 ne transfère jamais la propriété.

Chaque enregistrement valide la **projection JSON réellement persistée**
(aller-retour `json.dumps`/`loads`, `allow_nan=False`, jeu de clés exact) avant
`fsync`, puis publie en mémoire : c'est cette ligne que relira le prochain
démarrage.

## Mutation testing des gardes

14 mutations appliquées hors du dépôt (copie `git archive` dans un répertoire
scratch, une sous-clause de garde retirée par mutant), tests ciblés rejoués :
**13 tuées, 1 survivante**. La survivante est le contrôle d'aller-retour JSON
de `register` : les validations de types strictes qui le précèdent rendent déjà
toute divergence inatteignable, donc le retirer ne change aucune sortie
observable. Il est gardé comme **défense en profondeur attendue inatteignable**
(il protégerait un futur champ ajouté au record sans validation), et non comme
un contrôle épinglé par un test — écrire un test identique au comportement de
la couche voisine serait un test vacant.

## Comportements observables (testés)

| Situation | Issue |
|---|---|
| Document importé puis interrogé par un ayant droit | répondu et cité |
| Chunk d'index absent du registre | refusé → abstention |
| Chunk d'un autre locataire | refusé → abstention |
| Payload d'index contredisant la politique, même `acl_version` | `CanonicalAclError` (échec fermé) |
| Révocation canonique sans réindexation, demandeur révoqué | abstention |
| Révocation canonique sans réindexation, demandeur toujours autorisé | `CanonicalAclError` (le payload d'index contredit la politique) |
| Révocation avec `acl_version` incrémentée, demandeur autorisé | `CanonicalAclError` « stale ACL index » |

La comparaison payload ↔ politique vient **après** l'autorisation du demandeur :
un demandeur que la politique canonique refuse n'atteint jamais ce contrôle,
d'où l'asymétrie abstention / échec fermé des deux dernières lignes.

## Limites assumées

- **Désynchronisation registre/index = abstention, pas diagnostic.** Un
  document inconnu du registre est traité comme non autorisé. Direction sûre
  (aucune fuite), mais une incohérence d'exploitation se lit en abstention.
- **Déni de service après révocation sans réindexation.** Tant que l'index
  porte l'ancien payload, le passage n'est plus servi à personne. C'est le prix
  du fail-closed ; la réindexation du document rétablit le service.
- **Verrou intra-processus seulement** (`threading.Lock`) : deux serveurs V1
  écrivant dans le même répertoire ne sont pas sérialisés.
- **Le registre atteste ce qu'un import authentifié a déclaré** ; il ne prouve
  pas l'origine des octets du document. L'identité du principal vient de
  `rag_hermes/auth.py` (`tenant_id`/`owner_id` forcés depuis le jeton).
- Ce lot ne traite ni SEC-02 (remplacement non atomique), ni SEC-03 (transport
  Qdrant), ni ARCH-01 (chunking du service en mots 420/40 alors que le pipeline
  évalué chunke en tokens 384/64). Le registre enregistre le **document**, pas
  les chunks : il est donc insensible au chunker utilisé.
- Les tests sont CPU, avec un dépôt double fidèle. Ils ne prouvent pas le
  parcours contre un vrai Qdrant ; la CI d'intégration Qdrant couvre le
  pré-filtrage/post-filtrage du dépôt, pas ce câblage.

## Exploitation

```bash
mkdir -p /srv/hermes/canonical          # l'opérateur crée le répertoire
export RAG_QDRANT_URL=http://127.0.0.1:6333
export RAG_CANONICAL_STORE=/srv/hermes/canonical
export RAG_EMBED_LOCK=manifests/locks/bge-m3.lock.json
python scripts/serve_v1.py
```

Le fichier `canonical_documents.jsonl` contient le **contenu intégral** des
documents importés : il porte la même sensibilité que le corpus et doit être
sauvegardé et protégé comme tel (droits restreints, chiffrement au repos selon
le déploiement). Le perdre revient à perdre l'autorité ACL : l'index seul ne
permet plus de répondre.
