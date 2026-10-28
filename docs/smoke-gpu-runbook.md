# Runbook — smoke GPU sécurisé (chunking tokenizer + garde budget)

Ce runbook est la seule procédure autorisée pour relancer le smoke GPU après l’audit.
Aucun Pod ne doit être créé tant que les portes 0 à 3 ne sont pas vertes.

> **État live au 2026-10-18 : porte 3 fermée.** `runpodctl 3.0.1` et
> l’API/MCP de création inspectée n’exposent aucune expiration automatique de Pod.
> La campagne Pod est donc bloquée sans dépense. L’alternative Serverless est
> analysée dans `docs/serverless-gpu-campaign-feasibility.md` et reste `PARTIAL`,
> non autorisée au déploiement.

## Porte 0 — Prérequis secrets (préparés par l’utilisateur, jamais transmis)

1. Clé API RunPod temporaire dédiée au smoke. Dans l’interface actuelle,
   la gestion/suppression des Pods par `runpodctl` exige
   `api.runpod.io/graphql: Read/Write`; il n’existe pas de permission « Pods
   uniquement ». Cette permission donne un accès très large au compte : ne jamais
   transmettre la clé, la conserver dans `~/.runpod/config.toml` en mode `0600`,
   puis la révoquer dès la fin du smoke. Laisser `api.runpod.ai` sur `No access`.
2. Avant toute location, vérifier le droit de suppression sans toucher à une
   ressource réelle :
   ```bash
   runpodctl pod delete watchdog-permission-probe-does-not-exist
   ```
   La réponse attendue est `not_found`. Une réponse `forbidden` interdit le
   provisionnement : le watchdog ne pourrait pas supprimer le Pod.
3. Clé SSH ED25519 dédiée au smoke. Deux modes sont admis :
   - passphrase + `ssh-agent` sur une machine où l’agent est durable ;
   - sans passphrase pour l’automatisation Termux/PRoot, uniquement avec une clé
     dédiée et un fichier privé en mode `0600`. Dans ce mode, verrouiller le
     téléphone et supprimer/révoquer la clé après la campagne.
   La campagne Termux utilise `/root/.ssh/runpod_rag_bge_auto` et passe
   explicitement `-i /root/.ssh/runpod_rag_bge_auto` à SSH ; elle ne dépend pas
   d’un agent partagé entre processus PRoot.
4. Enregistrer uniquement la moitié publique sur RunPod, sans écraser d’autres clés,
   puis vérifier que l’empreinte distante correspond à l’empreinte locale.

## Porte 1 — Validation locale hors dépense

```bash
cd /root/rag-hermes-agent
QDRANT_INTEGRATION_URL=http://127.0.0.1:<PORT> .venv-audit/bin/python -m unittest discover -s tests -v
PYTHONPATH=. .venv-audit/bin/python scripts/plan_bge_gpu_job.py --manifest manifests/gpu/bge-m3-human-154.json
```

La première commande est la commande normative de validation Qdrant réelle. Le
serveur Qdrant 1.19.0 doit déjà répondre sur le port choisi, et la sortie doit
contenir explicitement le test d'intégration réel suivi de `OK`, sans skip :

```text
test_real_server_enforces_tenant_clearance_and_global_public ... ok
OK
```

Sans `QDRANT_INTEGRATION_URL`, la même suite affiche `skipped 'Qdrant integration
disabled'`. Ce run local reste utile, mais ne doit jamais être décrit comme une
validation Qdrant réelle. Le nombre total de tests évolue avec le dépôt ; ne pas
le figer dans le runbook.

Exigences : suite verte, intégration Qdrant réelle incluse, contrat de chunking
(question 96 / passage 384 / overlap 64 / réserve 32 ≤ 512) validé.

## Porte 2 — Preuve ACL sur Qdrant réel

Serveur épinglé 1.19.0, vecteurs identiques, fuite absolue = 0
(`data/results/qdrant_acl_audit_report.json`). Aucune revendication de qualité
sémantique : les vecteurs sont `deterministic-test-only-not-an-embedding`.

## Porte 3 — Garde budget/durée armée AVANT le workload

Le watchdog est un superviseur indépendant. Il ne lit aucune sortie du benchmark.

```bash
export RUNPOD_API_KEY=...          # clé Restricted
NAME="rag-bge-m3-guarded-$(date -u +%Y%m%dT%H%M%SZ)"
CREATED_AFTER="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PROVIDER_TERMINATE_AFTER="35m"
PROVIDER_DEADLINE="$(python -c 'from datetime import datetime,timedelta,timezone; import sys; print((datetime.fromisoformat(sys.argv[1].replace("Z","+00:00"))+timedelta(minutes=35)).astimezone(timezone.utc).isoformat().replace("+00:00","Z"))' "$CREATED_AFTER")"
WATCHDOG_READY="/tmp/${NAME}.watchdog-armed.json"
WATCHDOG_LOG="/tmp/${NAME}.watchdog.jsonl"
WATCHDOG_SESSION="watchdog-${NAME}"
export NAME CREATED_AFTER PROVIDER_TERMINATE_AFTER PROVIDER_DEADLINE WATCHDOG_READY WATCHDOG_LOG WATCHDOG_SESSION
runpodctl pod create --help | grep -q -- "--terminate-after"
test ! -e "$WATCHDOG_READY"
tmux new-session -d -s "$WATCHDOG_SESSION" "cd '$PWD' && exec env PYTHONPATH=. python scripts/pod_watchdog.py --name '$NAME' --created-after '$CREATED_AFTER' --hourly-rate-usd 0.59 --max-duration-minutes 30 --max-total-cost-usd 0.50 --provider-deadline '$PROVIDER_DEADLINE' --max-delete-attempts 3 --ready-file '$WATCHDOG_READY' --poll-seconds 30 >>'$WATCHDOG_LOG' 2>&1"
for _ in $(seq 1 60); do test -s "$WATCHDOG_READY" && break; tmux has-session -t "$WATCHDOG_SESSION" 2>/dev/null || exit 1; sleep 1; done
test -s "$WATCHDOG_READY"
python -c 'import json,os; p=json.load(open(os.environ["WATCHDOG_READY"])); assert p["event"] == "watchdog_armed" and p["name"] == os.environ["NAME"]; print(json.dumps(p, indent=2))'
tmux has-session -t "$WATCHDOG_SESSION"
```

Le provisionnement est interdit tant que les deux dernières commandes n'ont pas
réussi. Le fichier prêt est créé exclusivement après la photographie initiale des
Pods ; un fichier préexistant fait échouer le watchdog. La session `tmux` détache
le superviseur du terminal opérateur : fermer le shell ou perdre SSH/Termux ne le
tue pas. Conserver `WATCHDOG_SESSION`, `WATCHDOG_READY` et `WATCHDOG_LOG` jusqu'à
la suppression confirmée et vérifier `tmux has-session` juste avant le
provisionnement.

Le watchdog :
- photographie les Pods avant création et refuse tout conflit de nom préexistant ;
- calcule l’échéance de terminaison et le coût estimé ;
- refuse un plan dont le coût dépasse le plafond ;
- sélectionne uniquement le nouvel ID apparu sous le nom exact après armement ;
- échoue fermé si plusieurs Pods correspondent ou si aucun Pod n’a jamais été observé ;
- supprime le Pod à l’échéance même si le benchmark a planté ;
- si la liste des Pods échoue à l'échéance, tente directement de supprimer l'ID
  déjà observé dans la limite de trois tentatives, puis poursuit la surveillance ;
- borne les suppressions à trois tentatives et surveille ensuite jusqu'à l'échéance
  fournisseur, sans prétendre que la suppression est confirmée ;
- exige deux listings successifs sans le Pod après suppression avant de confirmer
  son absence ; une omission isolée ne termine jamais le watchdog ;
- termine avec l'état distinct `unconfirmed_at_provider_deadline` si le Pod ou son
  absence ne peuvent pas être confirmés à l'échéance fournisseur.

Le délai fournisseur `--terminate-after 35m` est une garde indépendante du watchdog :
il borne le Pod même si Termux, `tmux`, le listing ou la boucle locale deviennent
indisponibles. Le watchdog reste la première garde à 30 minutes. Si la vérification
de capacité `--terminate-after` ci-dessus échoue, la version locale de `runpodctl`
est insuffisante et le provisionnement est interdit jusqu'à sa mise à niveau.

Pour la campagne humaine 154, le tarif live A40 vérifié est 0,59 USD/h : le
coût maximal calculé sur 30 minutes est donc 0,295 USD. Si le tarif live change,
le lancement est bloqué jusqu'à mise à jour du draft et nouvelle approbation.

Preuve réelle effectuée le 2026-09-21 sur un Pod CPU jetable : événement
`deleted` à l’échéance, puis `confirmed_absent`; listes RunPod CLI et MCP
vides après vérification. Coût calculé du test : environ 0,002 USD.

Smoke GPU réel effectué le 2026-09-21 sur une A40 sécurisée 48 Gio à
0,49 USD/h, après indisponibilité de l'A5000. Le Pod a été supprimé
manuellement dès la récupération du rapport, puis le watchdog a émis
`confirmed_absent`; la dépense RunPod est revenue à 0 USD/h.

## Porte 4 — Provisionnement non-root

Définir l'image approuvée, puis créer le Pod avec le nom exact et la terminaison
fournisseur obligatoire. Ne jamais retirer `--terminate-after` :

```bash
: "${POD_IMAGE:?définir l'image RunPod approuvée}"
runpodctl pod create --name "$NAME" --image "$POD_IMAGE" --gpu-id "NVIDIA A40" --gpu-count 1 --terminate-after "$PROVIDER_TERMINATE_AFTER"
```

La porte 4 devient verte uniquement après la création réussie du Pod, la
confirmation que son nom et son GPU correspondent à la commande, et la
validation du checkout non-root décrite ci-dessous.

Puis, sur le Pod :

```bash
# bootstrap non-root (généré par rag_hermes.pod_security.build_non_root_bootstrap)
useradd --create-home --shell /bin/bash ragbench
install -d -m 0750 -o ragbench -g ragbench /opt/ragbench
chown -R ragbench:ragbench /opt/ragbench
# /opt/ragbench doit être un checkout Git du commit audité, avec .git présent
runuser -u ragbench -- bash -lc 'cd /opt/ragbench && AUDITED_COMMIT=<COMMIT_40_HEX> && test "$(git rev-parse HEAD)" = "$AUDITED_COMMIT" && test -z "$(git status --porcelain=v1 --untracked-files=all)" && PYTHONPATH=. python scripts/run_bge_gpu_campaign.py --manifest manifests/gpu/bge-m3-human-154.json --output data/results/bge_m3_human_154_report.json --receipt data/results/bge_m3_human_154_execution_receipt.json --code-revision "$AUDITED_COMMIT"'
```

Le runner refuse l'exécution humaine si `.git` est absent, si
`RAG_CODE_REVISION` diffère de `git rev-parse HEAD`, ou si l'arbre de travail
contient une modification suivie ou non suivie. Les commandes Git neutralisent
les variables héritées `GIT_*` afin qu'un autre dépôt ne puisse pas usurper la
révision auditée. Le manifeste doit être un fichier régulier non symbolique situé
dans le dépôt ; son chemin relatif et son SHA-256 sont transmis au runner,
vérifiés avant chargement, puis conservés dans le rapport embarqué. Le lanceur
invalide d'abord tout staging ou reçu ancien aux chemins déclarés. `--output`
reste accepté pour compatibilité, mais désigne un staging non consommable. Après
la fin du processus, le lanceur ouvre ce staging sans suivre les liens, lit et
valide son objet JSON, puis publie atomiquement un reçu autonome contenant la
commande réelle, les variables non secrètes, le code de sortie, le rapport
complet sous `report` et son SHA-256 canonique. Le reçu est l'unique source de
vérité ; le staging est toujours supprimé. Un échec ne laisse ni staging ni reçu
`completed` consommable.

## Porte 5 — Smoke reconstruit et portée de la validation

Le runner régénère le corpus avec le chunking tokenizer, encode dense+sparse,
récupère jusqu’à 20 candidats autorisés en mémoire, rejette avant scoring toute
paire dépassant le budget mesuré, puis appelle le reranker. La retokenisation
interne de `FlagReranker.compute_score` n'étant pas instrumentée, le rapport garde
`truncated_pairs = null` et décrit explicitement cette limite. **Ce smoke GPU ne
persiste rien dans Qdrant et ne teste pas le filtre ACL
Qdrant.** Cette preuve séparée appartient au test d’intégration Qdrant réel.

### Verdict du run A40 du 2026-09-21

**PASS conditionnel pour le smoke technique (8/10), NON-PASS production.**
Le champ machine `quality_gate_passed` reste donc `false`.

Réellement validé :
- A40, CUDA 12.8 et PyTorch 2.8 fonctionnels ;
- chunking tokenizer borné à 384 tokens ;
- maximum observé question+passage : 396/512 tokens ;
- `rejected_pairs = 0` ;
- Recall@10 inchangé à 1,0 avant/après reranking sur ce smoke ;
- détail avant/après disponible pour les 10 questions ;
- aucune fuite inter-tenant détectée par le préfiltrage Python ;
- rapport récupéré, Pod supprimé, facturation revenue à 0 USD/h.

Limites et résultats négatifs :
- 10 questions ne donnent aucun signal statistique de qualité ;
- le reranker n’améliore pas Recall@10 et dégrade le MRR de 1,0 à 0,9167 ;
- l’absence de fuite ne couvre que le préfiltrage Python en mémoire, pas Qdrant ni
  le système multitenant complet ;
- le rapport brut exécuté ne contient pas `truncated_pairs`. Pour ce run,
  l'absence de rejet au précontrôle et le maximum observé 396 < 512 prouvent
  uniquement que les paires respectaient le budget du tokenizer externe. Ils ne
  prouvent pas l'absence de troncature lors de la retokenisation interne du
  reranker ; cette métrique reste donc non instrumentée ;

### Critères restant nécessaires pour un futur PASS production

- conserver la campagne intermédiaire humaine de 154 cas comme preuve de
  composants ; préserver séparément les 300 cas actifs du schéma QA, qui ne
  constituent pas encore le jeu final ; puis exécuter via le pipeline de
  production une **piste finale distincte**, gelée, d'au moins 300 cas,
  **éligible qualité** et couvrant les strates de sécurité requises ;
- inclure au moins 30 questions écrites à la main sans regarder les chunks ;
- définir à l’avance des intervalles de confiance et des seuils de non-régression ;
- démontrer un bénéfice du reranker sur une métrique préenregistrée, sans dégrader
  les autres métriques critiques ;
- exercer la persistance et le filtrage ACL dans Qdrant pendant le pipeline évalué ;
- instrumenter la frontière réelle de scoring avant de revendiquer
  `truncated_pairs`, et conserver `rejected_pairs` ainsi que les métriques par cas ;
- conserver fuite ACL = 0 et vérifier l’isolation multitenant de bout en bout.

## Porte 6 — Récupération et arrêt

1. Copier uniquement `bge_m3_human_154_execution_receipt.json` hors du Pod. Le
   fichier `--output` est un staging et doit être absent après le retour du lanceur.
2. Charger le reçu avec le validateur partagé ci-dessous. Il refuse tout reçu qui
   n'est pas une v2 `completed` à code zéro, avec rapport objet, encodage et portée
   canoniques, SHA-256 hexadécimal valide et hash correspondant. Vérifier ensuite
   séparément la commande et les variables attendues, puis extraire le résultat
   exclusivement via `receipt["report"]` :
   ```python
   import json
   from pathlib import Path
   from rag_hermes.execution_receipt import load_consumable_receipt_v2

   receipt = load_consumable_receipt_v2(
       Path("bge_m3_human_154_execution_receipt.json")
   )
   print(json.dumps(
       {"command": receipt["command"], "environment": receipt["environment"]},
       indent=2,
       allow_nan=False,
   ))
   report = receipt["report"]
   ```
3. Vérifier dans le rapport embarqué le même chemin de reçu et le même commit audité.
4. Laisser le watchdog confirmer la suppression, ou supprimer manuellement.
5. Vérifier que `runpodctl pod list --all` ne renvoie plus le Pod.
6. Estimer le coût à partir de la durée observée, en le qualifiant d’estimation.
7. Révoquer la clé API temporaire et retirer la clé SSH publique dédiée.
