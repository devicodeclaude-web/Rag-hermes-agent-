# G1 — fenêtre encadrée par deux audits de payload (candidats, ou réponse citée)

Deux points d'entrée publics partagent le même moteur privé
`_run_audited_g1_window` et assemblent, **pour une seule question**, les briques
précédentes sans les brancher à `RagService` :
`run_audited_g1_candidate_window`, qui rend des candidats, et
`run_audited_g1_answer`, qui rend une réponse citée. Le rappel de génération
n'est **pas sur la surface publique** : il le serait, un appelant obtiendrait
les deux vrais rapports d'audit autour d'une réponse fabriquée tout en
contournant les gardes du pilote. Le préfixe `_` du moteur reste une
**convention**, pas une barrière : du code exécuté dans le même processus peut
l'importer, comme il peut forger l'objet de résultat directement. La frontière
de confiance est le processus, pas ce nom.

1. charge un JSONL documentaire et vérifie son SHA-256 attendu, puis reconstruit
   les chunks via un chunker fourni par l'opérateur ;
2. construit un client de scroll d'audit et un client de recherche REST séparés
   depuis le **même `base_url` et le même nom de collection**, et vérifie le
   schéma dense+sparse et les index ACL ;
3. ouvre `AuditedIndexSession` avec une empreinte de manifeste **attendue**, non
   calculée à partir de l'index ; l'audit exige les IDs et payloads de chaque
   point, y compris les points étrangers à la requête ;
4. interroge dense et sparse, fusionne RRF, recontrôle la provenance et l'ACL
   contre le JSONL, puis compare **l'ID et le payload de chaque candidat** au
   manifeste exact de cette session, par sérialisation JSON sensible aux types,
   **avant** de l'envoyer au tokenizer et au reranker injectés. Le dépôt vérifie
   d'abord le point brut de `query` contre le chunk décodé : cette chaîne de
   contrôles empêche un point absent du manifeste de devenir candidat, mais ne
   prouve ni que la requête a vu l'index audité ni l'identité des serveurs ;
5. rejoue l'audit **avant** de rendre la fenêtre de candidats. Une divergence
   à l'ouverture empêche la requête ; une divergence à la clôture empêche la
   restitution des candidats. Une exception ou une interruption pendant la
   requête invalide la session sans scroll de clôture.

Sur la voie réponse, la génération s'intercale **entre le reranking et l'audit
de clôture** : ordre observable `schéma → audit → dense → sparse → reranking →
génération → audit`. Conséquence à ne pas euphémiser : un générateur injecté —
donc potentiellement une API distante — voit les passages **avant** que l'audit
de clôture ait confirmé l'index. Si cet audit échoue, aucune réponse n'est
rendue à l'appelant et la session devient terminale, mais le texte est déjà
sorti. Ce qui est garanti avant tout appel au modèle ou au générateur : ACL et
provenance canoniques, et appartenance de chaque candidat au manifeste audité.

Après le retour du générateur et **avant** l'audit de clôture, chaque candidat
est **relié une seconde fois** au manifeste. Le générateur conserve pourtant
les références aux `Chunk` reçus et peut les modifier même **après** ce contrôle,
pendant le scroll final (`object.__setattr__` contourne `frozen=True`). La voie
réponse crée donc des **copies privées** des candidats, vérifie aussi chaque
copie contre le manifeste, et reconstruit les citations et la trace à partir de
ces copies sans rappeler le générateur. Une mutation ultérieure des objets que
ce dernier détient ne réécrit plus la fenêtre, le passage cité ou sa provenance
publiés. Le scroll ne vérifie toujours que l'index, pas ces objets Python.
Le type de la réponse est aussi vérifié (`type(answer) is str`) : une sous-classe
de `str` au `__eq__` menteur se faisait passer pour l'abstention exacte et
court-circuitait les deux gardes de citation.

Le type `AuditedCandidateWindow` contient une liste immuable de candidats et
les deux rapports d'audit. Il ne contient ni réponse, ni citation, ni décision
`abstained`. **Une fenêtre vide n'est pas une abstention honnête** : les top-40
par voie, le préfiltre et l'absence de calibration peuvent cacher une preuve.
Les scores RRF et reranker sont des scores de rang non calibrés.

Le type `AuditedG1Answer` porte la trace de réponse, la fenêtre reclassée qui
l'a produite et les deux rapports. Une fenêtre vide y lève `GenerationError`
— panne serveur — au lieu de devenir une abstention. Les marqueurs `[Sn]` sont
résolus sur cette seule fenêtre, et un marqueur hors fenêtre fait **échouer**
la requête (`strict_citations=True`) au lieu d'être silencieusement effacé du
texte publié. Une abstention émise par le générateur lui-même est conservée
telle quelle, mais elle n'est **pas calibrée** : ce n'est pas une décision
d'abstention du système. Comme `AuditedCandidateWindow`, ce type n'est **pas
une attestation** : `object.__new__`, `dataclasses.replace`, `pickle` et
`deepcopy` le reconstruisent avec n'importe quels champs à côté de rapports
d'audit authentiques. Un reçu G1 devra le verrouiller par une empreinte
recalculable, pas accepter l'objet. Son `repr` ne recopie ni le texte des
preuves ni celui des citations ; les attributs bruts, eux, restent sensibles.
`AuditedCandidateWindow`, lui, n'a **pas** de `repr` masquant : son `repr` par
défaut recopie le texte des chunks. Asymétrie assumée tant qu'aucun des deux
types n'est journalisé ; à harmoniser avant tout reçu G1.

Bornes de la preuve : les deux rapports dérivent du **même** manifeste ; leur
égalité n'est pas une confirmation indépendante. L'audit lit les IDs/payloads,
**pas** les vecteurs ; il n'empêche aucune écriture. Une mutation de l'index
annulée avant la clôture reste invisible. Les deux clients partagent la chaîne
URL/collection, mais un proxy, le DNS, des alias ou des écritures concurrentes
peuvent leur faire voir des états ou des serveurs différents : c'est un
câblage, **pas une preuve d'identité réseau ni un gel d'index**. Les SHA
attendus, la justesse du chunker, la synchronisation du snapshot et le gel des
écritures doivent venir de l'opérateur, indépendamment du serveur. Cette
fonction crée ses deux clients **sans identité réseau distincte** sur le même
endpoint : la séparation des classes Python ne protège pas le scroll
administrateur contre un autre code Python sur cet hôte. En déploiement réel,
une isolation réseau/identifiants séparés serait nécessaire mais **non fournie**
ici.

Un test d'intégration est prévu en CI contre un Qdrant réel : 40 points
étrangers dominent strictement un point autorisé sur les deux voies, et le
score RRF attendu exige les deux préfiltres. Il vérifie aussi un **second**
scroll à la clôture en y simulant un payload divergent ; son exécution doit être
confirmée par l'artefact du run correspondant. Il utilise uniquement embedder,
tokenizer et reranker factices : **aucune** exécution BGE-M3, aucun GPU, aucun
seuil d'abstention ou reçu G1. Ce n'est pas une campagne G1 ni un chemin de
réponse publiable.
