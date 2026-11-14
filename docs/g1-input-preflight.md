# G1 — prévol des entrées, pas une campagne

Avant de comparer G1 (R3 + ACL + génération + citations) à G0, lancer depuis la
racine du dépôt :

```sh
PYTHONPATH=. /root/work/venv/bin/python scripts/preflight_g1_inputs.py
```

Le script vérifie hors ligne : le snapshot de référence `human-154` (154 identifiants
uniques), son SHA-256 dans les deux reçus v2 consommables, les identifiants des
cas retrieval et la capture des **154 sorties textuelles G0** (réponses ou
abstentions, question, étiquette et texte non vide). Le drapeau `did_abstain`
doit correspondre au texte d'abstention après `strip()` ; les comptes et taux
d'abstention du rapport, ainsi que la liste des cas à relire, sont confrontés
aux sorties. Les champs `generation.temperature` et `generation.max_tokens`
doivent également respecter le décodage épinglé dans le manifeste. L'identité
déclarée du générateur G0 y est comparée. Chaque reçu doit aussi attester le
**chemin et le SHA-256 de son manifeste local à chemin fixe**. Le manifeste
G0 doit lui-même déclarer `classification=infrastructure_smoke_only` et
`protocol.configuration=G0` ; il refuse les constantes JSON non standard
(`NaN`/`Infinity`), sans vérifier les clés dupliquées ni les débordements
de nombres annexes. Le bloc `corpus` du rapport G0 doit désigner ce même
snapshot et sa classification doit rester « essai d'infrastructure, pas
benchmark qualité ». Les statuts des rapports retrieval et G0 doivent indiquer
une exécution complète (distincte du statut de l'enveloppe v2). Le rapport G0
doit avoir `generation_failures = 0` et `total = 154` en face des 154 verbatims :
sinon un rapport prétendant 154 pannes et 154 réponses passerait. L'identité du
générateur est comparée sur `repo_id`, `revision`, `engine`, `quantization`,
`served_model_name` et `decoding`, chacun devant être **présent et non vide dans
le manifeste** — une clé absente des deux côtés ne vaut pas une concordance.

Portée exacte des garanties : un reçu v2 dont le rapport a été modifié **sans
recalcul de son hash** est rejeté, mais un rapport réécrit *avec* son hash
recalculé reste un reçu v2 valide — le hash protège l'intégrité, pas la
provenance. Il ne vérifie pas non plus que les fichiers locaux sont encore ceux
d'un commit donné : les hashes sont comparés aux reçus, pas à une ancre externe.
De même, l'identité du modèle servi est **déclarée par l'opérateur**,
jamais prouvée cryptographiquement. Les révisions de code des deux campagnes
peuvent être différentes : on exige une révision de forme SHA-1, sa cohérence
interne et le **même dataset en octets**, pas le même commit ni sa présence
vérifiée dans git. Le prévol ne compare pas `job_id` ni le statut de gel du
protocole entre manifeste et rapport ; ces champs demandent une vérification
séparée avant toute mesure pré-inscrite.

Ce prévol ne donne jamais un feu vert G1 : même `inputs_aligned=true` ne prouve
ni l'index interrogé, ni le filtrage ACL, ni les vecteurs, ni la qualité des
réponses. L'ancien rapport BGE-M3 sur 154 cas est un **composant retrieval en
mémoire**, pas une campagne générative G1, et son seuil de qualité n'est pas une
preuve de production. Le jeu QA actif de 300 cas est une piste distincte du
snapshot `human-154` utilisé ici.

État vérifié lors de la création de ce prévol : le reçu BGE-M3 v2 est lisible et
son dataset atteste le SHA-256 du snapshot suivi par git. Il n'existe **pas de
reçu G0 v2 valide** dans `data/results/` : le précédent artefact erroné a été
retiré ; le run G0 avec capture des réponses reste à refaire sur GPU externe,
par transfert du fichier réel et validation avec `load_consumable_receipt_v2`.
Le script affiche donc `missing_verified_g0_receipt` et sort avec le code 1.

Après réception d'un vrai reçu G0, l'ordre de travail G1 reste :

1. Câbler la source de candidats dense+sparse/RRF désormais opt-in, son recontrôle
   canonique et l'étage de reranking (`g1_reranking.py`) avec modèles et
   paramètres épinglés — l'étage existe en CPU avec de faux modèles, le
   checkpoint réel reste porté par le manifeste ;
   aujourd'hui `g1_wiring.py` assemble encore un dépôt Qdrant dense, et le runner
   BGE-M3 calcule R3 en mémoire séparément. Ni le score RRF brut ni le score de
   reranking ne peuvent servir de seuil d'abstention.
2. Sur un index Qdrant contrôlé, lier le client de requête et la collection au
   manifeste audité, puis exécuter l'audit d'ouverture et de clôture autour du
   même service de réponse. La session existante vérifie les points et payloads,
   mais **n'empêche pas les écritures** et l'appelable de campagne pourrait
   ignorer cette collection. L'audit ne compare pas les vecteurs.
3. Produire un reçu autonome G1 avec réponses et citations par cas, erreurs
   terminales et provenance vérifiables ; comparer G0/G1 sur les mêmes cas,
   puis faire la revue humaine aveugle. Une exécution sur `human-154` avant
   gel du protocole v2 est un **essai d'infrastructure**, pas une mesure de
   qualité pré-inscrite. Les seuils et le gel nécessitent l'accord humain ; la
   couverture privée/contradictions/injections de la piste finale reste à
   qualifier séparément.

Ne pas louer de GPU pour G1 tant que le pipeline R3 et le reçu G1 ne sont pas
implémentés et testés. Ne pas assimiler la suite CPU à une preuve GPU.
