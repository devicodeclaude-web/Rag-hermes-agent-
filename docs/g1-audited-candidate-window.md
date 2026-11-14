# G1 — fenêtre candidate-only encadrée par deux audits de payload

`run_audited_g1_candidate_window` assemble, **pour une seule question**, les
briques précédentes sans les brancher à `RagService` :

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

Le type `AuditedCandidateWindow` contient une liste immuable de candidats et
les deux rapports d'audit. Il ne contient ni réponse, ni citation, ni décision
`abstained`. **Une fenêtre vide n'est pas une abstention honnête** : les top-40
par voie, le préfiltre et l'absence de calibration peuvent cacher une preuve.
Les scores RRF et reranker sont des scores de rang non calibrés.

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
