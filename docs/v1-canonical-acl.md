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

**Protection du registre (documents privés en clair).** Le répertoire doit
appartenir à l'UID effectif du service et ne donner aucun droit au groupe ni
aux autres (`0700` au plus) ; le fichier doit être régulier, appartenir au
même UID et ne donner aucun droit au groupe ni aux autres (`0600` au plus).
Chaque ouverture valide les descripteurs réels avec `fstat` avant de lire ou
d'écrire ; les liens symboliques sur le répertoire final et le fichier sont
refusés. Le fichier neuf est créé par `os.open(..., mode=0o600)` avec
`O_NOFOLLOW`, ancré au descripteur du répertoire : un `umask 022` ne peut
donc pas élargir ses droits à `0644`. Une modification de droits après le
démarrage fait échouer l'écriture au lieu de continuer silencieusement.
Un ancien fichier déjà en `0644` est **refusé sans changement de droits** :
une permission corrigée après coup n'efface pas une divulgation éventuelle.
L'opérateur doit vérifier l'exposition passée puis corriger les droits hors
ligne avant de relancer. Cette porte POSIX ne chiffre pas les données et ne
protège pas contre un processus du même UID, root, ou une sauvegarde exposée.

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
- une modification de la politique ACL (`visibility`, `classification`,
  `allowed_groups`, `allowed_users`) exige une augmentation de `acl_version`,
  même si `doc_version` augmente ; une modification du contenu ou de sa
  provenance (`source_uri`) exige une augmentation de `doc_version`, même si
  `acl_version` augmente. À versions égales, seul un document inchangé peut
  être réimporté. L'ancien ensemble d'utilisateurs autorisés ne peut donc pas
  être rejoué après révocation à la même `acl_version` ;
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

Lot du verrou de transaction (même méthode, 9 mutants) : fermeture par jeton
après `fork`, fermeture des descripteurs hérités, réinitialisation de l'état
de bail, remplacement des mutex d'instance hérités, refus de l'élévation
lecture→écriture, verrou de lecture dans `CanonicalAclSearch.search`, verrou
de lecture dans `RagService.answer_with_trace` et verrou d'écriture de
`CanonicalWriteThrough` — **tous tués**. Seule survivante : le contrôle de PID
sur un bail déjà détenu, rendu inatteignable par la réinitialisation de l'état
de bail au `fork` ; il est conservé et annoté comme défense en profondeur, pas
épinglé par un test.

## Comportements observables (testés)

| Situation | Issue |
|---|---|
| Document importé puis interrogé par un ayant droit | répondu et cité |
| Chunk d'index absent du registre | refusé → abstention |
| Chunk d'un autre locataire | refusé → abstention |
| Payload d'index contredisant la politique, même `acl_version` | `CanonicalAclError` (échec fermé) |
| Révocation sans incrémenter `acl_version` | `ValueError`, autorité et index inchangés |
| Révocation avec `acl_version` incrémentée, avant réindexation, demandeur révoqué | abstention |
| Révocation avec `acl_version` incrémentée, avant réindexation, demandeur autorisé | `CanonicalAclError` « stale ACL index » |

La comparaison payload ↔ politique vient **après** l'autorisation du demandeur :
un demandeur que la politique canonique refuse n'atteint jamais ce contrôle,
d'où l'asymétrie abstention / échec fermé des deux dernières lignes. Un
changement ACL à version égale est désormais refusé au registre (et au
redémarrage si une ligne rejouée est ajoutée au fichier), non testé comme une
révocation valable.

## Limites assumées

- **Désynchronisation registre/index = abstention, pas diagnostic.** Un
  document inconnu du registre est traité comme non autorisé. Direction sûre
  (aucune fuite), mais une incohérence d'exploitation se lit en abstention.
- **Déni de service après révocation sans réindexation.** Tant que l'index
  porte l'ancien payload, le passage n'est plus servi à personne. C'est le prix
  du fail-closed ; la réindexation du document rétablit le service.
- **Registre partagé local** : les lectures contrôlent le fichier sous `flock`
  partagé et rejouent les lignes si l'identité du fichier a changé
  (`st_dev`, inode, taille, mtime et ctime en nanosecondes) ; les écritures
  rejouent toujours le fichier sous `flock` exclusif avant le contrôle monotone.
  Deux processus partageant le même inode sur un
  système de fichiers qui respecte `flock` ne peuvent plus rejouer une ancienne
  ACL à partir d'un cache obsolète ; un lecteur déjà démarré voit une révocation
  au prochain accès. Une disparition, troncature ou restauration d'une révision
  antérieure à celles déjà vues est refusée, sans créer de nouveau fichier.
  La relecture après changement reste proportionnelle à tout l'historique ;
  le contrôle de métadonnées n'est pas une preuve cryptographique contre une
  modification hostile qui reproduirait la même signature. Un processus qui
  démarre sur une ancienne sauvegarde n'a pas de repère indépendant pour la
  rejeter. Ce n'est pas un registre distribué scalable.
  Un montage réseau sans garantie de verrouillage équivalente est hors champ.
- **SEC-02, portée mono-hôte coopérante uniquement** : le fichier privé
  `canonical_transaction.lock` est ouvert sous le répertoire canonique et
  verrouillé par `flock` partagé pendant `RagService.answer_with_trace`
  (recherche Qdrant, recontrôle ACL, reranking, génération et citations), ou
  exclusif pendant `CanonicalWriteThrough.replace_document` (publication du
  registre puis remplacement Qdrant). `CanonicalAclSearch.search` seul prend
  aussi la lecture partagée. Les appels imbriqués dans le même fil réutilisent
  le verrou ; écrire sous une lecture échoue. Au `fork`, le processus enfant
  ferme les descripteurs de verrou hérités, réinitialise l'état de bail et
  remplace les mutex d'instance hérités : sans cela, un enfant gardait un
  verrou partagé du parent ou se bloquait sur un mutex pris par un autre fil.
  Deux processus partageant ce répertoire/inode sur un système de fichiers
  local compatible `flock` ne voient plus la fenêtre upsert/suppression via
  ces chemins coopérants. Les écritures Qdrant directes et les autres
  hôtes/stockages ne sont pas bloqués.
  Le fichier de verrou ne doit jamais être supprimé ou remplacé pendant le
  service : cela créerait des inodes et des verrous indépendants. Une génération
  lente bloque les imports jusqu'à sa fin ; aucune limite de temps n'est posée
  par cette barrière. Des réponses déjà commencées peuvent achever leur
  génération avant la publication de la révocation : ce n'est pas une coupure
  immédiate. Le verrou est relâché dès que `RagService.answer_with_trace`
  construit l'`AnswerTrace`, **avant** la sérialisation et la livraison HTTP
  WSGI : un corps calculé sous l'ancienne ACL peut donc être transmis après
  une révocation qui vient de finir. La barrière assure l'ordre des opérations
  du service coopérant, pas l'annulation des réponses déjà calculées. Un crash
  ou échec après l'écriture canonique mais avant la fin du remplacement Qdrant
  laisse une divergence qui doit être réparée hors ligne ; les candidats
  observés divergents échouent fermés, mais les points masqués par le préfiltre
  ne sont pas prouvés exhaustifs. La séquence Qdrant
  n'est toujours pas une transaction : clients non coopérants et déploiement
  multi-hôte restent hors garantie. **SEC-02 général reste ouvert** ; cette
  tranche ne revendique pas d'atomicité native Qdrant ni de preuve de
  concurrence sur un serveur Qdrant réel.
- **Reprise après crash** : une dernière ligne incomplète fait échouer les
  lectures et le démarrage. Ne jamais la tronquer automatiquement ni restaurer
  une sauvegarde sans vérifier hors ligne la dernière version connue de chaque
  document auprès d'une ancre indépendante. Arrêter le service, préserver le
  fichier original pour l'enquête et rétablir l'intégrité avant redémarrage.
- **Le registre atteste ce qu'un import authentifié a déclaré** ; il ne prouve
  pas l'origine des octets du document. L'identité du principal vient de
  `rag_hermes/auth.py` (`tenant_id`/`owner_id` forcés depuis le jeton).
- Ce lot ne clôt ni SEC-02 (remplacement non atomique), ni les limites de SEC-03
  (privilèges Qdrant). Le chemin V1 Qdrant exige un profil de tokenizer épinglé
  (lot ARCH-01) ; le mode mémoire reste découpé en mots. Le registre enregistre
  le **document**, pas les chunks : il est donc insensible au chunker utilisé.
  Les candidats renvoyés par Qdrant sont comparés aux passages régénérés depuis
  ce document avec le profil verrouillé. Un point ancien échoue fermé s'il est
  observé ; le démarrage n'audite pas exhaustivement la collection et un point
  caché par le préfiltre reste indétectable. Migrer/réingérer hors ligne.
- Les tests ciblés du registre sont CPU, avec un dépôt double fidèle ; **les
  tests système HTTP de la CI exercent aussi ce câblage contre un vrai Qdrant**
  (import, redémarrage du service, registre relu du disque, réponse citée,
  tentative de reprise de propriété refusée). Cela ne prouve ni l'atomicité
  du remplacement (SEC-02), ni un déploiement multi-instance.

## Exploitation

```bash
install -d -m 700 /srv/hermes/canonical # créé pour l'UID qui exécute le service
export RAG_QDRANT_URL=http://127.0.0.1:6333
export RAG_CANONICAL_STORE=/srv/hermes/canonical
export RAG_EMBED_LOCK=manifests/locks/bge-m3.lock.json
export RAG_TOKENIZER_LOCK=manifests/locks/bge-reranker-v2-m3.lock.json
export RAG_TOKENIZER_FILE=/chemin/local/du-checkpoint/tokenizer.json
python scripts/serve_v1.py
```

Le fichier `canonical_documents.jsonl` contient le **contenu intégral** des
documents importés : il porte la même sensibilité que le corpus et doit être
sauvegardé et protégé comme tel (droits restreints, chiffrement au repos selon
le déploiement). Le perdre revient à perdre l'autorité ACL : l'index seul ne
permet plus de répondre.
