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
`CanonicalAclError` (sous-classe de `PermissionError`) plutôt que de compter
une abstention honnête. Le pont élargit
la requête classée en cas de candidats rejetés (budget de 128) ; si le budget
est saturé, il échoue fermé. Le `minimum_score` du pont doit être identique à
celui du service (vérifié à la construction). Un payload contradictoire avec
la politique canonique échoue explicitement **s'il est retourné par le dépôt**
et si la politique autorise le demandeur ; un candidat refusé observé ne peut
pas bloquer un document légitime classé juste après lui. La réponse HTTP de
`QdrantRestClient.query` exige un `result.points` de type liste, au plus la
limite demandée et un score numérique fini par point ; il refuse aussi un
statut d'erreur **explicite** dans l'enveloppe HTTP. Le dépôt Qdrant répète
le contrôle du score même avec un client de requête injecté. Un résultat sans
score ne peut plus être converti en score zéro, donc en fausse abstention.
Une liste vide bien formée (ou une réponse sans champ `status`) reste acceptée :
ces contrôles ne prouvent ni sa complétude ni le bon index interrogé.

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
L'essai `scripts/smoke_g1_qdrant.py` sur **Qdrant 1.20.0 réel** vérifie
l'audit paginé, une réponse citée depuis une source JSONL épinglée, une
campagne synthétique **d'un cas** passée dans le vrai harnais audité (audit
d'ouverture et de clôture), puis le rejet à la clôture d'une seconde session
après falsification de l'ACL indexée. L'embedder et le générateur sont factices ;
la collection temporaire est effacée. Ce n'est pas un essai de qualité G1.
La source locale (`rag_hermes/canonical_snapshot.py`) vérifie l'empreinte du
fichier avant décodage, mais l'autorité de cette empreinte reste extérieure.
Dans le smoke test, les deux empreintes sont calculées à partir des données
créées pour l'essai : cela démontre le câblage, **pas** une approbation
indépendante des valeurs. `g1_wiring.py` impose un digest de manifeste épinglé
avant tout scroll et retourne une surface de réponse sans import ; l'objet
interne `_service` reste accessible à un appelant Python non fiable : cette
surface n'est **pas** une frontière de sécurité ni un verrou Qdrant. Les
anciens appels d'audit restent compatibles sans épingle : ce mode **ne
prouve pas** la provenance du manifeste. Une session peut aussi recevoir
l'épingle et l'exige à l'ouverture et à la clôture. Un test CPU raccorde la
source épinglée au vrai adaptateur de `run_audited_evaluation`, sans modèle
GPU ni seuil de qualité.

`AuditedIndexSession` est une **brique volontaire non intégrée au chemin des
requêtes ordinaires** : `run_audited_evaluation` l'appelle pour encadrer une
campagne explicite, mais elle n'intercepte ni ne bloque les autres requêtes.
Sans ce wrapper, lancer `open()` avant la première requête d'évaluation et
`close()` après la dernière est une **obligation de l'opérateur**. `close()`
rejoue l'audit et échoue si l'index a divergé du manifeste. Quatre limites
honnêtes : un échec d'`open()` ou de `close()` est **terminal** (le portillon
est fermé sous verrou avant tout audit, donc ni une reprise ni un appel
concurrent ne transforme une divergence détectée en succès — testé avec 100
essais à deux fils) ; l'erreur de clôture porte un message fixe
(`closing audit failed`, la cause restant dans `__cause__`) car une panne de
transport ou une réponse Qdrant malformée n'est pas une mutation d'index, ne
doit pas être étiquetée comme telle, et son texte peut contenir une URL ou des
identifiants ; les deux rapports
dérivent du même manifeste, donc leur égalité n'est pas une preuve indépendante
(le seul signal est que l'audit de clôture a été rejoué et a passé) ; et la
session n'empêche aucune écriture — une mutation annulée avant `close()`, ou ne
touchant que les vecteurs, reste invisible.

Ce n'est **pas encore G1 complet** : une source dense+sparse/RRF de candidats
existe désormais, avec recontrôle canonique opt-in (`g1_hybrid_candidates.py`),
mais elle n'est pas reliée à ce service ni à une règle d'abstention. Le
reranking verrouillé, la liaison des requêtes à la collection auditée et le
reçu de campagne restent à câbler et à tester. La traduction des erreurs par cas
est désormais câblée dans `run_evaluation` (voir ci-dessous), sans présumer
qu'une campagne réelle G1 a déjà été exécutée.
Le scoreur `evaluate` dérive déjà `answered` / `abstained` / `acl_error` /
`backend_error` depuis ses entrées. L'exclusivité est imposée **au constructeur**
(`EvaluationCase.__post_init__` refuse un cas qui prétendrait à la fois s'être
abstenu et avoir échoué) **et re-vérifiée au scoring** : `object.__new__`,
`copy.deepcopy` et `pickle` contournent `__post_init__`, et sans ce second
contrôle un cas forgé publiait un statut de panne pendant que
`terminal_status_source` affirmait encore `no_runtime_error_observed`. Ce n'est
donc pas une propriété du type, c'est une porte à deux étages, tous deux
fail-closed.

`run_evaluation` **alimente désormais ces statuts**. Le canal est explicite :
un `answer_fn` signale un cas inexécutable en levant
`CaseExecutionError(terminal_status)`, seule exception que le runner intercepte ;
tout le reste **remonte et avorte la campagne**. C'est volontaire — attraper une
classe large transformerait un bug du harnais ou une panne de transport en
`backend_error` publié, c'est-à-dire un constat d'audit faux dans un composant
censé produire de la preuve. La traduction du vocabulaire du service vit dans
l'adaptateur qui le connaît (`_answer_via_service`) : `CanonicalAclError`
(barrière ACL en échec fermé) → `acl_error`, `GenerationError` →
`backend_error`. Un `PermissionError` du stockage reste une erreur inattendue
qui avorte la campagne au lieu d'être blanchi en refus ACL. La cause
reste dans `__cause__` pour l'opérateur, mais son texte n'est **jamais** recopié
dans le message signalé ni dans le rapport : une erreur de transport embarque
souvent une URL, un corps de réponse ou des identifiants, et le rapport est un
artefact committé.

Frontière à ne pas confondre, verrouillée par un test à double sens : un cas
`no_answer` qui ne trouve **aucune preuve autorisée** s'abstient honnêtement
(`abstained`) ; seule une barrière qui **échoue fermé** devient `acl_error`. Si
le service levait `PermissionError` sur un résultat vide, toute abstention
honnête serait reclassée en panne et le rappel d'abstention s'effondrerait.

Un cas en panne conserve ses étiquettes de pertinence avec **zéro récupération** :
une panne compte donc comme un échec de récupération au lieu de disparaître du
rappel — même direction anti-gonflement que les dénominateurs d'abstention. Les
compteurs d'erreurs étant publiés à part, un lecteur peut recalculer l'autre
convention. Tant que la campagne tourne sur un service réel, ce n'est toujours
pas un reçu G1 : la source candidate-only dense+sparse/RRF (et son recontrôle
canonique optionnel) n'est pas câblée à ce parcours, le reranking verrouillé,
la liaison vérifiable entre les requêtes et la collection auditée, et le reçu de
campagne restent à câbler. La réconciliation des IDs de chunks avec le manifeste
s'applique au parcours audité, pas à `run_evaluation` direct.

`run_audited_evaluation` (`rag_hermes/evaluation_runner.py`) fait de l'audit une
précondition **pour ses appelants** : l'audit d'ouverture tourne avant la
première question, donc un index divergent ne fait répondre aucun cas, et
l'audit de clôture doit passer avant qu'un rapport soit renvoyé. Ce que cela
établit est borné : **l'index de la session** était conforme au manifeste aux
deux bouts de la campagne. `answer_fn` étant un appelable arbitraire, la
fonction ne peut pas vérifier que les questions ont réellement été servies par
la collection auditée — lier les deux reste le travail de l'opérateur. Le
rapport audité exige désormais `context_for_case` et une
`CanonicalAclAuthority` indépendante de l'index : le calcul des fuites compare
chaque chunk récupéré/cité à la politique canonique, à ses métadonnées ACL et
au contexte du cas (locataire, propriétaire, groupes, habilitation). Deux
documents privés de même visibilité ne sont donc pas automatiquement
mutuellement autorisés ; un document global public reste utilisable par un cas
privé quand la politique le permet. La visibilité des documents de référence
est confrontée à celle de l'autorité avant toute réponse, et chaque document
référencé doit être autorisé pour le contexte du cas ; sinon la campagne échoue.
Les identifiants de locataire, les champs de politique et le contexte sont
validés avec leurs types exacts (un booléen ne vaut pas l'entier 1).
Seules les classes exactes de session d'audit et d'autorité sont admises : une
sous-classe redéfinissant `open()`/`close()` ou `authorize()` ne peut simuler un
contrôle réussi. Le contexte n'est résolu qu'une fois et transmis à
`answer_fn(question, case, context)` ;
`build_contextual_service_answer_fn` l'utilise directement pour appeler le
service. Un appelable arbitraire peut néanmoins ignorer ce contexte : ce n'est
pas une preuve de l'identité réellement utilisée par le service. Le score
`security_gate_passed` vérifie les fuites ACL constatées, et, pour le parcours
**audité seulement**, chaque chunk autorisé récupéré ou cité est désormais
réconcilié avec l'ID et le payload complets du manifeste que la session a
contrôlé (comparaison JSON sensible aux types). Sur le chemin
`QdrantChunkRepository`, le point **brut de la requête** est aussi comparé à
son décodage AVANT de perdre son ID ou de convertir `true` en `1` : un ID Qdrant
inventé et un `doc_version: true` sont refusés. Ce contrôle local du point
renvoyé ne démontre toujours pas que l'appelable a utilisé la collection auditée.
Pour un chunk **autorisé dans le parcours audité**, ou un point traité par
`QdrantChunkRepository`, un ID inventé, une version ou une URI contrefaite
**avorte** la campagne au lieu de laisser une porte verte ; un chunk non
autorisé qui atteint le scoreur reste compté comme fuite et garde la porte rouge.
La voie distincte `postfilter_candidates` contrôle désormais les types exacts
`document_id`/`acl_version` et compare les champs ACL du payload à la politique
canonique avant d'accepter un candidat ; une contradiction observée échoue fermé.
Elle sert notamment à la matrice ACL ; le runner GPU en mémoire construit
maintenant un payload complet depuis chaque chunk avant de l'appeler (câblage
testé sur CPU, **sans nouveau run GPU**). Elle ne réconcilie **ni l'ID du
point ni le texte** avec une source indépendante : ne pas l'utiliser comme
preuve de provenance d'une réponse G1. Les candidats filtrés en amont restent invisibles.
Cette réconciliation ne prouve ni que le service a effectivement interrogé la
collection auditée (l'appelable peut renvoyer un chunk canonique sans requête),
ni que le manifeste a une provenance indépendante fiable, ni que la recherche
est complète ; l'audit reste borné à ses deux instantanés et n'empêche aucune
écriture. Sans ces deux paramètres, `run_evaluation` direct conserve un score
de fuite limité à la visibilité/liste fournie ; son `security_gate_passed`
n'est pas une preuve d'autorisation multi-tenant. Ce n'est
pas non plus une propriété du système : une campagne lancée directement via
`run_evaluation`, ou toute requête émise hors de cet appel, reste non auditée.
Une campagne interrompue invalide la session **sans auditer** : elle ne prétend
rien sur l'index, n'impose pas un scroll complet sur un Ctrl-C, et n'écrase pas
une erreur de divergence par l'erreur de scoring.

Le résolveur canonique de l'essai reste une source locale synthétique ; malgré
l'essai sur Qdrant réel décrit plus haut, le brancher à un stockage documentaire
fiable et exécuter une campagne sur un index de production contrôlé restent
préalables à toute garantie de production. Attention : un candidat écarté
**en amont** par le préfiltre Qdrant ou par `QdrantChunkRepository` est invisible pour ce pont ;
il peut masquer une ACL périmée ou une contradiction et produire une abstention
ordinaire. Le préfiltre transmis n'est donc pas une preuve de complétude du
contrôle ACL ni de la classe `abstained`. Avant d'utiliser ce statut comme
mesure d'évaluation G1, il faut une exécution réussie de l'audit complet sur
le **même index figé** pendant la campagne (ou une trace vérifiable des rejets
en amont). Même conforme, l'audit d'intégrité des points ne prouve pas que la
recherche/préfiltre a exploré tous les candidats utiles : à lui seul, il ne
qualifie aucune abstention. La fonction d'audit n'authentifie pas à elle seule
la provenance du manifeste et ne verrouille pas les écritures Qdrant : sans
ces préconditions, son succès CPU n'est pas un reçu G1. La V1 existante garde
son comportement ; la barrière n'est activée que lorsqu'un client l'enveloppe
explicitement.
