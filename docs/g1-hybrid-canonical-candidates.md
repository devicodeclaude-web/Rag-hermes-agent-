# G1 — candidats RRF confrontés à une source canonique (tranche CPU)

`CanonicalHybridCandidates` prend un `QdrantChunkRepository` hybride, le
chemin d'un fichier documentaire JSONL et un SHA-256 attendu fourni par
l'appelant. Son constructeur appelle **lui-même**
`load_pinned_document_snapshot` : un `PinnedDocumentSnapshot` construit à la
main ne peut pas contourner le contrôle des octets. L'origine indépendante de
l'empreinte attendue reste une obligation de l'opérateur — ce contrôle ne
l'authentifie pas. Pour chaque
requête, il récupère au plus 80 candidats de la fusion dense/sparse (top-40 par
voie), puis réutilise la barrière `CanonicalAclSearch._recheck` sans son seuil
de qualité : politique ACL canonique, version, locataire, propriétaire, URI,
SHA-256 du contenu et texte aux offsets sont comparés à la source indépendante
de l'index. Un document observé absent du snapshot, un payload contredisant
la source ou une ACL périmée sans autre candidat valable font échouer la
requête ; un candidat périmé n'empêche pas un suivant valide de passer.

Avant d'appeler la barrière, chaque candidat observé est confronté aux champs
ACL canoniques (locataire, visibilité, propriétaire, classification, groupes,
utilisateurs), **dans les deux sens** :

- **Index plus permissif que le canonique** (ex. document passé à un autre
  propriétaire, avec ou sans nouvelle `acl_version`) : la barrière n'examine la
  provenance qu'*après* avoir autorisé le demandeur, donc ce cas sortait en
  fenêtre vide. Il lève désormais `CanonicalAclError`.
- **Index plus restrictif que le canonique** : le candidat est écarté avant
  d'être vu. La source redemande explicitement les refusés
  (`hybrid_candidates(..., include_denied=True)`, drapeau
  `authorized_by_index=False`) et lève `CanonicalAclError` quand la politique
  canonique, elle, autorise le demandeur. **Portée réelle très limitée** : avec
  `QdrantRestClient`, le préfiltre serveur reçoit le même filtre ACL sur les
  deux voies et retire le point *avant* la réponse, donc aucun candidat refusé
  ne peut être matérialisé et ce cas sort en **fenêtre vide silencieuse**
  (figé par `test_server_side_prefilter_hides_the_restrictive_divergence`).
  Ce contrôle ne détecte donc qu'un client qui n'applique pas le préfiltre
  (adaptateur injecté, double de test, déploiement mal configuré) — ce n'est
  **pas** une détection générale de l'index trop restrictif. Un document
  inconnu du snapshot reste un candidat étranger ordinaire et n'est jamais
  renvoyé.

Les candidats marqués `authorized_by_index=False` servent **uniquement** à ce
diagnostic : ils ne sont ni renvoyés, ni citables, ni transmis à un générateur.
Le plafond `output_limit` du dépôt borne les candidats **autorisés** ; les
refusés sont ajoutés en plus et ne réduisent donc jamais la fenêtre utile.
`authorized_by_index` n'a **pas** de valeur par défaut : un site de
construction qui l'oublie échoue au lieu de fabriquer un candidat « autorisé ».

Limites connues de cette tranche, à lever avant tout branchement sur une règle
d'abstention :

- Le snapshot est **épinglé en mémoire à la construction** : une révocation
  écrite dans le JSONL après coup reste invisible pour une instance de longue
  durée. Reconstruire l'objet à chaque révision du corpus.
- **Snapshot en retard sur un index légitimement mis à jour** (révocation déjà
  appliquée à Qdrant, fichier pas encore ré-épinglé) : côté client non
  préfiltrant, la requête entière est avortée par `CanonicalAclError` et un
  candidat valide de la même fenêtre est perdu ; côté vrai client REST, le même
  cas dégrade en fenêtre vide silencieuse. Ré-épingler le snapshot **avant** de
  révoquer dans l'index.
- Un seul candidat de la fenêtre absent du snapshot (ou divergent) **avorte
  toute la requête** : le fichier épinglé doit couvrir le corpus indexé, un
  snapshot partiel rend la source inutilisable.
- Un locataire littéralement nommé `public` avec `visibility: private` sort en
  fenêtre vide silencieuse : `acl.filter_authorized` le traite comme un
  locataire ordinaire alors que `AclPolicy.allows` traite `public` comme
  global/public-only. Divergence **préexistante** hors de cette tranche.
- La garde `type(repository) is not QdrantChunkRepository` refuse aussi une
  sous-classe légitime (dépôt instrumenté) : choix fail-closed assumé.
- Avec `include_denied=True`, la liste du dépôt dépasse `output_limit` (bornée
  par les 80 points de la fusion) et transporte du texte non autorisé à
  l'intérieur du processus pour ce seul diagnostic ; le seul appelant actuel le
  jette sans le renvoyer.
- Le constructeur accepte un dépôt dense seul ; l'échec est différé au premier
  appel (`hybrid candidates require a hybrid encoder`).
- La validation du contexte vit dans le dépôt (`hybrid_candidates`), pas dans
  cette classe : dépendance d'ordre à conserver si l'appel est réorganisé.

Cette classe renvoie uniquement des `HybridCandidate` non calibrés. Une liste
vide signifie « aucun candidat utilisable dans cette fenêtre bornée », **pas**
« abstention honnête » : les top-40, le préfiltre Qdrant et le postfiltre local
peuvent cacher des points, et ni ce pont ni l'audit des payloads ne prouvent
l'exhaustivité du retrieval. La provenance de l'empreinte épinglée dépend de
l'opérateur. Aucun reranking, génération, citation, reçu G1 ou comparaison
G0/G1 n'est branché ici. Le chemin `RagService` reste dense ; ne pas lui
passer le score RRF brut comme seuil de confiance.
