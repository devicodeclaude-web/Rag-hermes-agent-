# G1 — reranking verrouillé sur les candidats canoniques (tranche CPU)

`RerankedCandidateSource` enveloppe `CanonicalHybridCandidates` : il demande au
plus `candidate_limit` candidats (défaut 20, comme `hybrid.reranker_candidates`
du manifeste), vérifie le budget de tokens de **chaque paire** avec le
tokenizer fourni, soumet les paires au cross-encodeur injecté, puis réordonne
et tronque à `top_k`.

Contrat d'échec fermé :

- une paire dépassant `max_length` (défaut 512, comme `reranker.max_length`)
  est **refusée**, jamais tronquée : un passage tronqué serait noté sur un
  texte différent de celui que la citation revendiquerait. Le reranker n'est
  alors même pas appelé ;
- le reranker doit renvoyer **exactement un score numérique réel fini par paire** ;
  les booléens et chaînes `"0.9"` sont refusés, les scalaires numériques NumPy
  sont acceptés, et `NaN`/`inf` échouent. Un flux de scores est consommé jusqu'à
  `nombre de paires + 1` au maximum (un flux sans fin ne bloque pas le test de
  cardinalité) ; si le modèle modifie les paires et que la modification reste
  **visible après l'appel**, l'étage avorte (une mutation suivie d'une
  restauration n'est pas observable) ;
- la sortie est construite en sélectionnant, puis en réordonnant, **uniquement**
  les candidats rendus par la barrière canonique : les scores seuls ne peuvent
  ni ajouter, ni renommer, ni ré-autoriser un passage. Un objet modèle arbitraire
  exécuté dans le même processus n'est **pas sandboxé** ; ses effets de bord
  hors de cette interface ne sont pas couverts. Une divergence ACL/provenance
  **qui fait échouer** la barrière avorte avant tout appel au modèle ; une ACL
  périmée observée avec un autre candidat valide peut être écartée sans
  avorter, et seul le candidat valide est alors soumis au modèle ;
- égalités tranchées de façon déterministe par `chunk_id` ;
- `max_length`, `batch_size`, `top_k` et `candidate_limit` sont validés au
  constructeur (entiers stricts, bornes, `top_k <= candidate_limit`), de même
  que la présence de `compute_score` et d'un tokenizer appelable.

`rerank_score` est **non calibré**, exactement comme `rrf_score` (conservé à
côté de lui) : ce n'est **pas** un seuil d'abstention et rien ici ne décide
qu'une question est sans réponse. Une liste vide signifie « fenêtre bornée sans
candidat utilisable », pas une abstention honnête.

Limites de cette tranche : les tests utilisent un faux tokenizer et un faux
cross-encodeur — **aucun** `BAAI/bge-reranker-v2-m3` réel, aucun GPU, aucune
mesure de qualité. L'étage vérifie le budget avec le tokenizer **injecté** ; il
ne prouve ni que celui-ci est le tokenizer interne du modèle, ni que le modèle
respecte `max_length` sans troncature propre. L'épinglage effectif du checkpoint,
de sa révision et du tokenizer est une obligation de l'appelant, décrite par le
manifeste GPU (`manifests/locks/bge-reranker-v2-m3.lock.json`) mais **non
vérifiée** par cette classe. Le snapshot canonique reste épinglé en mémoire à
la construction ; la révocation postérieure n'est pas recontrôlée par cet étage.
Rien n'est câblé à `RagService` ni à `g1_wiring` ; la génération citée, le reçu
G1 et la comparaison G0/G1 restent à faire.
