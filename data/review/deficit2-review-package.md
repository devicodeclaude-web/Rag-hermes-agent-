# Dossier de revue HUMAINE INDEPENDANTE — cas deficit-2 (2 cas)

Ces deux cas `no_answer` ont ete REDIGES par devicodeclaude-web puis valides
par lui-meme (auteur == relecteur initial). Une revue agent-independante les a
confirmes, mais le critere complet exige un **relecteur HUMAIN distinct du
redacteur**. Juge, pour chaque cas : (1) la question est-elle plausible et
in-domain ? (2) le fait demande est-il reellement ABSENT du corpus (donc
`no_answer` justifie) ? (3) les distracteurs sont-ils de vrais pieges qui ne
repondent PAS ? Puis remplis la grille (validate / rewrite / reject). Aucune
reponse attendue ni score n'est montre ici.

## v3na-169 — `no_answer`  (provenance : `user_written_from_scaffold_intent`)
**Question.** Quand plusieurs jobs cron sont planifiés pour se déclencher exactement à la même minute, dans quel ordre s'exécutent-ils ? Y a-t-il une règle de priorité, un ordre FIFO ou un autre mécanisme de départage documenté ?

- Cible : *(aucune — no_answer ; `relevant_document_ids` doit rester vide)*
- **Preuve d'absence.** Recherche corpus entier (FIFO / order / ordre / priorite / tie-break / simultane / 'same time' / 'one after another' / 'execution order' / max_parallel) sur les 6 docs cron + fixtures : AUCUNE regle d'ordre, de priorite ou de departage pour des jobs dus a la meme minute. cron-internals.md (Tick Cycle) itere les jobs dus sans ordre specifie ; cron.md ne definit que cron.max_parallel_jobs (plafond de concurrence) ; cron-troubleshooting.md confirme l'execution SEQUENTIELLE ('one after another') mais ne dit jamais lequel passe en premier. Fait absent et non derivable.
- Distracteur (piege) `hermes-agent:user-guide/features/cron.md` — extrait (ne doit PAS repondre a la question) :

  > ## Lifecycle actions
  > Cron jobs now have a fuller lifecycle than just create/remove.
  > ### Chat
  > ```bash
  > /cron list
  > /cron pause <job_id>
  > /cron resume <job_id>
  > /cron run <job_id>
  > /cron remove <job_id>
  > ```
  > ### Standalone CLI
  > ```bash
  > hermes cron list
  > hermes cron pause <job_id_or_name>
  > hermes cron resume <job_id_or_name>
  > hermes cron run <job_id_or_name>
  > hermes cron remove <job_id_or_name>
  > hermes cron edit <job_id_or_name> [...flags]
  > hermes cron status
  > hermes cron tick
  > ```
  > What they do:
  > - `pause` — keep the job but stop scheduling it
  > - `resume` — re-enable the job. A recurring job whose slot came due while it was paused keeps that slot due, s
- Distracteur (piege) `hermes-agent:guides/cron-troubleshooting.md` — extrait (ne doit PAS repondre a la question) :

  > ### Check 4: Permissions on jobs.json
  > Jobs are stored in `~/.hermes/cron/jobs.json`. If this file is not readable/writable by your user, the scheduler will fail silently:
  > ```bash
  > ls -la ~/.hermes/cron/jobs.json
  > chmod 600 ~/.hermes/cron/jobs.json   # Your user should own it
  > ```
  > ---
  > ## Performance Issues
  > ### Slow job startup
  > Each cron job creates a fresh AIAgent session, which may involve provider authentication and model loading. For time-sensitive schedules, add buffer time (e.g., `0 8 * * *` instead of `0 9 * * *`).
  > ### Too many overlapping jobs
  > The scheduler executes jobs sequentially within each tick. If multiple jobs are due at

## v3na-170 — `no_answer`  (provenance : `user_written_from_scaffold_intent`)
**Question.** Existe-t-il une limite de longueur (en caractères) pour le titre ou la description d'une carte kanban ?

- Cible : *(aucune — no_answer ; `relevant_document_ids` doit rester vide)*
- **Preuve d'absence.** Recherche corpus entier (char / caractere / length / longueur / limit / max / 1-64 / title / titre / description / card / carte) sur tous les docs kanban + fixtures : AUCUNE limite de longueur sur le titre ou le body d'une carte. Les seuls plafonds sont des attracteurs sur AUTRE chose : slug de board (1-64), troncature d'affichage (~3800), resume d'evenement (400). Les champs de carte sont 'title' / 'body', sans plafond de caracteres. Fait absent.
- Distracteur (piege) `hermes-agent:user-guide/features/kanban.md` — extrait (ne doit PAS repondre a la question) :

  > ### Two surfaces: the model talks through tools, you talk through the CLI
  > The board has two front doors, both backed by the same `~/.hermes/kanban.db`:
  > - **Agents drive the board through a dedicated `kanban_*` toolset** — `kanban_show`, `kanban_list`, `kanban_complete`, `kanban_request_review`, `kanban_request_changes`, `kanban_block`, `kanban_heartbeat`, `kanban_comment`, `kanban_attach`, `kanban_attach_url`, `kanban_attachments`, `kanban_create`, `kanban_link`, `kanban_unblock`. The dispatcher spawns each worker with these tools already in its schema; orchestrator profiles can also enable the `kanban` toolset explicitly. The model reads
