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

Lot du repère persisté (même méthode, 22 mutants) : contrôle de l'ancre au
rejeu et sur fichier absent, empreinte des enregistrements, égalité stricte du
compte (un `>=` permissif comme l'absence de contrôle sont tués), refus d'un
recul de version et d'un document ancré perdu, publication de l'ancre AVANT
l'append, inclusion de la nouvelle ligne dans l'empreinte, comptage des lignes
plutôt que des documents, typage strict de l'ancre, `O_NONBLOCK` avant la
validation `S_ISREG`, `O_EXCL` sur le temporaire et nettoyage de ce temporaire,
distinction entre « rien n'a été écrit » et « seule la durabilité a échoué »,
refus d'écriture sur un magasin déjà incohérent, et seconde observation du
fichier absent — **tous tués dans le lot historique**. Les deux survivantes
de ce lot étaient alors le cas « ancre absente équivaut à ancre vide » et le
drapeau « magasin incohérent » doublé par l'invalidation de signature. **La
politique a changé depuis** : une ancre absente avec un historique non vide
est désormais refusée avant tout service ; ne pas réutiliser les anciens
chiffres de mutants comme preuve de cette nouvelle garde.

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
- **Registre partagé local** : les lectures contrôlent le JSONL **et son
  ancre** sous `flock` partagé et rejouent l'historique si l'identité de l'un
  ou de l'autre change (`st_dev`, inode, taille, mtime et ctime en nanosecondes) ;
  les écritures rejouent toujours le fichier sous `flock` exclusif avant le
  contrôle monotone.
  Deux processus partageant le même inode sur un
  système de fichiers qui respecte `flock` ne peuvent plus rejouer une ancienne
  ACL à partir d'un cache obsolète ; un lecteur déjà démarré voit une révocation
  au prochain accès. Une disparition, troncature ou restauration d'une révision
  antérieure à celles déjà vues est refusée, sans créer de nouveau fichier.
  La relecture après changement reste proportionnelle à tout l'historique ;
  le contrôle de métadonnées n'est pas une preuve cryptographique contre une
  modification hostile qui reproduirait la même signature.
  Ce n'est pas un registre distribué scalable.
  Un montage réseau sans garantie de verrouillage équivalente est hors champ.
- **Repère persisté hors du JSONL (`canonical_anchor.json`, 0600)** : il porte
  le nombre de **lignes** rejouées, l'**empreinte SHA-256 de ces enregistrements
  canonicalisés** (les chaînes effectivement rejouées, pas un hachage brut du
  fichier : un bourrage de lignes blanches ou un `CRLF` est donc accepté, car il
  décrit les mêmes documents) et, par document, les `doc_version`/`acl_version`
  atteintes. Il est publié par remplacement atomique (temporaire créé en
  `O_EXCL`, validé par `fstat`, `fsync`, `rename`, `fsync` du répertoire)
  **avant** chaque append, sous le même `flock` exclusif.
  Conséquence exploitée comme contrôle : le fichier n'est jamais légitimement
  en avance sur son repère, donc l'égalité du nombre d'enregistrements est
  exigée **strictement**. Sont refusés à chaque relecture — y compris au
  **démarrage d'un processus neuf**, ce que le cache mémoire ne pouvait pas
  couvrir : une ligne déjà ancrée dont le contenu a changé (même à compte et
  versions constants, donc une ACL réécrite en place), un historique tronqué,
  restauré depuis une sauvegarde antérieure, compacté, supprimé alors qu'une
  ancre non vide existe, **et une ligne ajoutée sans republication de l'ancre**
  (sinon une révision forgée à `acl_version` supérieure suffirait à annuler une
  révocation sans toucher au repère). Une ancre remise à zéro ne vaut donc pas
  « pas d'ancre » : face à un historique non vide, elle échoue fermé.
  Un FIFO ou un périphérique posé à la place du JSONL, de l'ancre ou de son
  temporaire **échoue fermé** (`O_NONBLOCK` avant la validation `S_ISREG`) au
  lieu de suspendre indéfiniment la requête en tenant les verrous.
  Le constat « fichier absent » est **réobservé une seconde fois** avant de
  conclure à une disparition : l'historique ne peut que croître, et un processus
  neuf qui démarre pendant la toute première écriture d'un autre processus se
  refuserait sinon lui-même par erreur. Cette reprise n'acquiert aucun verrou,
  volontairement : la lecture tient déjà le mutex d'instance alors que
  l'écriture prend le bail de transaction **avant** lui, donc y prendre le bail
  produirait un interblocage ABBA (constaté en revue sur un magasin neuf).
  Un registre **non vide sans ancre** échoue désormais fermé au démarrage,
  même s'il vient d'une installation historique ; seul un magasin neuf et
  vide peut faire son premier enregistrement sans ancre, qui est alors publiée
  avant la ligne JSONL. L'absence d'ancre après une révocation était autrement
  indiscernable d'un vrai magasin ancien et réadmettait l'ancienne ACL au
  redémarrage. **Aucune migration automatique ni outil de restauration d'un
  registre historique sans ancre n'est livré ici** : arrêter le service,
  préserver les originaux et définir une migration hors ligne adossée à une
  preuve de confiance indépendante avant de tenter de le rouvrir ; ne jamais
  générer aveuglément une ancre à partir du JSONL présent. Une ancre illisible,
  exposée, symbolique ou malformée échoue également fermé, sans réparation
  silencieuse. Un repère vivant dans le même répertoire et sous le même UID ne
  protège toujours pas d'un adversaire qui réécrirait **les deux fichiers**
  de façon cohérente : il faudrait une ancre hors de l'hôte ; enfin la
  publication réécrit la carte complète des documents à chaque enregistrement,
  coût proportionnel au nombre de documents.
- **Panne d'append après la publication de l'ancre** — pas seulement un crash :
  `ENOSPC`, `EIO`, un quota. Deux cas sont distingués en relisant le fichier
  sous le verrou exclusif encore tenu, au lieu de condamner sur la seule
  exception : si **rien n'a été écrit**, l'ancre est en avance, le registre se
  marque **incohérent** et refuse désormais lectures *et* écritures (le cache
  porte précisément l'ACL que l'écriture voulait remplacer, et une écriture
  suivante avancerait l'ancre sur un historique faux, voire pousserait vers
  Qdrant un document que le registre refuse) ; le redémarrage échoue
  identiquement et la reprise est hors ligne. Si en revanche la ligne **est**
  sur le disque et que seule la barrière de durabilité a échoué, l'état est
  cohérent : l'écriture est signalée comme non confirmée
  (`canonical record durability is not confirmed`), l'état relu est adopté, et
  ni le processus vivant ni un redémarrage ne sont bloqués. L'ancre atteste le
  compte, les versions et l'empreinte des enregistrements ; elle ne peut pas
  valider le contenu d'une ligne ajoutée pendant une réparation hors ligne.
  **Vérification préalable, sans réparation :** après arrêt du service et
  conservation des originaux, l'opérateur peut fournir une copie privée (0600)
  de la **ligne JSONL originale exacte**, terminée par `\n` :
  `PYTHONPATH=. python scripts/check_canonical_recovery.py --store /chemin/prive --candidate /chemin/prive/ligne-originale.jsonl`.
  Le vérificateur prend des baux partagés, ne crée ni n'écrit aucun fichier et
  refuse si l'ancre n'est pas en avance d'exactement UNE ligne, si l'historique
  se termine par une ligne partielle, si le candidat n'est pas canonicalisé,
  ou si son ajout simulé ne reproduit pas l'empreinte ET les versions de l'ancre.
  L'empreinte porte sur les enregistrements **rejoués** (`ligne + LF`) et non
  sur tous les octets historiques : lignes blanches et CRLF anciens sont
  normalisés par le lecteur ; le candidat, lui, doit être canonicalisé exactement.
  Le succès ne reconstitue pas une ligne perdue, ne répare pas le JSONL, ne
  valide pas Qdrant et ne vaut pas autorisation de redémarrer : une reprise
  exige sauvegarde vérifiée, contrôle hors ligne et réconciliation de l'index.
  **Copie de reprise isolée (jamais une mutation de la source) :** avec le même
  candidat exact, ajouter `--output-dir /autre/repertoire/prive/reprise` à la
  commande ci-dessus. Le parent de sortie doit déjà exister, appartenir à
  l'UID du service, être inscriptible et ne donner aucun droit groupe/autres
  (0700 convient ; la porte accepte aussi d'autres modes privés utilisables).
  La cible ne doit pas exister ni se trouver sous le registre source. Sous les baux
  partagés, le programme copie le JSONL + la ligne candidate et l'ancre dans
  un répertoire temporaire privé, rejoue les enregistrements et vérifie leur
  cohérence avec l'ancre **par descripteurs de fichier** (sans résoudre une
  seconde fois le chemin du staging), puis la publie sans écraser une cible
  concurrente (`renameat2`/`RENAME_NOREPLACE`).
  Les fichiers sont fsyncés avant publication. Si la publication ou son fsync
  final échoue, **vérifier la cible** : elle peut exister même si la commande a
  rendu un refus ; la source reste intacte. En cas d'échec du nettoyage, un
  staging privé (`.*.recovery-*`, mode 0700) peut rester : il n'est PAS une
  copie publiée, le préserver pour diagnostic avant suppression manuelle.
  La copie possède un NOUVEL inode de verrou : ne jamais la substituer à chaud,
  arrêter tous les processus et réconcilier Qdrant avant toute mise en service.
  Les contrôles de contenance comparent les inodes ouverts et l'ascendance du
  parent avant création et avant publication ; ils ne constituent pas une
  défense contre un autre processus du même UID qui déplace les répertoires
  hors des verrous coopératifs pendant ou après ces contrôles. Exécuter cette
  procédure sur un hôte arrêté et une arborescence maîtrisée. Ce chemin ne
  prouve pas l'origine de la ligne fournie ni la cohérence de l'index.
  **Diagnostic d'index en lecture seule (tranche suivante) :** après arrêt
  de TOUS les écrivains sur le registre ET Qdrant, conserver la copie privée
  publiée et obtenir hors de cette copie une empreinte SHA-256 approuvée de
  `canonical_anchor.json`. Exécuter avec les mêmes fichiers `tokenizer.json`
  et lock approuvés que le service V1 (moteur `tokenizers==0.22.2`) :
  `PYTHONPATH=. RAG_QDRANT_G1_AUDIT_API_KEY=<jeton-r-collection> python scripts/audit_canonical_copy.py --copy /autre/repertoire/prive/reprise --anchor-sha256 <empreinte-independante> --qdrant-url <url> --collection <collection> --tokenizer-lock <lock> --tokenizer-file <tokenizer.json>`.
  Le jeton doit donner uniquement `r` sur cette collection (Qdrant vérifie
  sa signature) ; ne jamais passer la clé admin à cet outil. Avant le scroll
  non filtré, le programme rejoue le JSONL contre son ancre et compare celle-ci
  au digest approuvé ; il régénère les chunks depuis les documents canoniques
  et refuse un document qui ne génère aucun passage ainsi que tout point absent,
  supplémentaire, en doublon ou dont le payload diverge. Aucun fichier source
  ou point Qdrant n'est réparé par cet outil. Un REFUS signifie que la
  concordance n'a PAS été établie : divergence, configuration ou panne de
  transport sont à diagnostiquer séparément. Une concordance signifie
  seulement que les IDs/payloads OBSERVÉS correspondaient
  au manifeste de la copie lors du scroll : ni les vecteurs, ni les écritures
  non coopératives/multi-hôte, ni l'immuabilité ultérieure, ni la provenance
  de l'empreinte fournie par l'opérateur ne sont prouvés. Le script exige un
  vrai profil tokenizer approuvé ; les tests CPU avec chunker factice ne le
  valident pas. NE PAS mettre la copie en service sur ce seul diagnostic :
  revue humaine, réparation contrôlée des divergences et nouvelle vérification
  restent à concevoir. Même après réussite, SEC-02 reste ouvert.
  Ce diagnostic prend le verrou partagé du répertoire inspecté **en lecture
  seule** (aucun descripteur en écriture, aucun fichier créé), donc il reste
  utilisable sur un support monté en lecture seule ; mais `flock` ne coordonne
  que des processus coopérants du même hôte : n'auditer qu'une copie hors
  service et sans écrivains.
  **Plan de réconciliation (`--plan`, lecture seule lui aussi) :** l'audit
  échoue fermé sur la première anomalie et ne dit pas QUOI réparer. Avec les
  mêmes arguments plus `--plan` (et éventuellement
  `--surplus-budget N`, défaut 1000), le programme énumère les points
  **manquants**, **inattendus** et **divergents** sous le même bail partagé,
  la même empreinte d'ancre approuvée et le même rejeu : pour un point
  divergent le plan en mémoire ne contient que les **noms de champs** en
  écart, jamais une valeur. `repr(plan)` et `str(plan)` limitent **chacun des
  cinq champs** à un entier validé par la garde partagée
  `rag_hermes/redacted_repr.py` (un champ forgé est masqué et ne peut ni
  fuiter sa longueur ni faire lever le rendu). `render_divergence_report` est
  plus strict : son en-tête masque les **deux** compteurs de la même façon,
  mais les **trois champs de collection** sont *refusés* en échec fermé
  (`plan de divergence invalide`) si leur forme est forgée, chaque champ étant
  lu une seule fois ; sur un plan valide leurs comptes viennent d'un `len()`
  sur tuple réel. Cette branche d'échec est de la **défense en profondeur** :
  le constructeur du plan n'émet que des tuples exacts, donc un index hostile,
  qui ne contrôle que des *valeurs*, ne l'atteint pas.
  Limites restant ouvertes, bornées par la **frontière de processus** : une
  *sous-classe* du plan dont un compteur est une propriété qui lève fait lever
  `repr`, et `is_clean` n'est pas durci (un `__bool__` hostile propage son
  message). Les deux exigent du code attaquant dans le processus, pas un index
  hostile. Ne pas journaliser/sérialiser (`asdict`, attributs
  bruts) le plan en mémoire :
  un nom de clé Qdrant inconnu peut lui-même contenir un secret. Le rendu CLI
  imprime **tous les champs du schéma canonique connus** (ACL comprise) même si
  de nombreuses clés inconnues les précèdent ; les clés inconnues ne sont
  **jamais imprimées**, seulement comptées par point. Les identifiants de
  points viennent aussi de l'index : seules les formes UUID et entières non
  signées (64 bits) sont affichées ; toute autre chaîne, même imprimable, est
  remplacée par un marqueur compté. Le numéro de ce marqueur recommence dans
  chaque section et ne permet pas de retrouver l'ID masqué dans Qdrant :
  pour diagnostiquer un tel point, l'opérateur doit consulter l'index dans
  un environnement contrôlé, sans publier le nom brut dans un journal.
  Une valeur secrète qui aurait elle-même la forme d'un ID valide reste
  affichable : la sortie ne doit pas être traitée comme déclassifiée.
  Le nombre de lignes affichées et la longueur de chaque ligne sont bornés
  par les champs canoniques fixes, afin d'empêcher une clé malveillante de
  fabriquer de fausses lignes ou de gonfler le journal. Toute évolution du
  schéma payload doit mettre à jour l'ensemble approuvé et le test de parité.
  Un identifiant de point ENTIER (légal dans Qdrant, possible si un outil tiers
  a écrit) est énuméré comme intrus au lieu de bloquer tout le plan. `--surplus-budget`
  plafonne le nombre **TOTAL** de points lus (attendus + surplus) : c'est une
  borne mémoire, pas un plafond du nombre d'intrus listés. Code de sortie :
  `0` plan vide, `1` divergence énumérée, `2` refus. Un plan au-delà du budget
  échoue fermé plutôt que de collecter sans borne. **Un plan vide n'est pas une
  preuve de concordance** : seul l'audit est la porte en échec fermé, et le
  plan n'écrit rien, ne décide rien et n'autorise aucun redémarrage — la
  réparation des points listés puis un nouvel audit restent à la charge de
  l'opérateur.
  Ne jamais inventer le contenu manquant à partir des seules versions.
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
  concurrence sur un serveur Qdrant réel. Le repère persisté décrit plus haut
  couvre le redémarrage du registre, **pas** la cohérence registre/Qdrant.
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
