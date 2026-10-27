# Dossier de revue indépendante — lot v2+ (32 cas)

Construction **assistée** (scaffold Hermes + rédaction LLM). L'évaluateur
**doit être distinct des rédacteurs** (cf. `provenance_detail`). Les cas
restent `pending` jusqu'à décision. Aucun verdict ni score ici : juge si la
cible répond et si le distracteur ne répond pas, puis remplis la grille.

## v2p-001 — `simple`  (provenance : `claude_written`)
**Question.** Je viens de finir l'installation : comment j'obtiens une première conversation qui marche, et quoi vérifier si l'agent ne répond rien ?

- Cible `hermes-agent:getting-started/quickstart.md` — extrait indicatif (vérifier que la cible répond) :

  > **Rule of thumb:** if Hermes cannot complete a normal chat, do not add more features yet. Get one clean conversation working first, then layer on gateway, cron, skills, voice, or routing.
  > ---
  > ## 1. Install Hermes Agent
  > ### With the Hermes Desktop installer on macOS or Windows (recommended)
  > To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it.
  > ### Without Hermes Desktop:
  > For a command-line only install without Hermes Desktop, run:
  > #### Linux / macOS / WSL2 / Android (Termux)
  > ```bash
  > curl -fsSL https://hermes-agent.nousresea
- Distracteur `hermes-agent:getting-started/installation.md` — extrait (ne doit PAS mieux répondre) :

  > # Installation
  > Get Hermes Agent up and running in under two minutes!
  > :::tip Platform Support
  > For the full platform support matrix (which OSes, distribution methods, and
  > platform-gated features are supported), see **[Platform Support](./platform-support.md)**.
  > :::
  > ## Quick Install
  > ### With the Hermes Desktop installer on macOS or Windows (recommended)
  > To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it.
  > :::note
  > The macOS installer is **Apple Silicon only**. macOS on x86 (Intel) processors is [not a supported platform](./pl

## v2p-002 — `simple`  (provenance : `claude_written`)
**Question.** Est-ce que je peux coller une capture d'écran directement dans le terminal pour que l'agent analyse ce qu'il y a dessus ?

- Cible `hermes-agent:user-guide/features/vision.md` — extrait indicatif (vérifier que la cible répond) :

  > ## Why Terminals Can't Paste Images
  > This is a common source of confusion, so here's the technical explanation:
  > Terminals are **text-based** interfaces. When you press Ctrl+V (or Cmd+V), the terminal emulator:
  > 1. Reads the clipboard for **text content**
  > 2. Wraps it in [bracketed paste](https://en.wikipedia.org/wiki/Bracketed-paste) escape sequences
  > 3. Sends it to the application through the terminal's text stream
  > If the clipboard contains only an image (no text), the terminal has nothing to send. There is no standard terminal escape sequence for binary image data. The terminal simply does nothing.
  > This is why Hermes uses a separate clip
- Distracteur `hermes-agent:user-guide/features/deliverable-mode.md` — extrait (ne doit PAS mieux répondre) :

  > ## Encouraging the agent to produce artifacts
  > The agent doesn't reach for artifacts by default — it has to know to.
  > Two ways to nudge it:
  > **Per-session:** ask explicitly ("send me the comparison as a chart",
  > "return the data as a CSV") or write your own custom-instructions /
  > personality entry that biases toward artifact-style replies on
  > messaging platforms.
  > **Project-level:** add the bias to `AGENTS.md` / `CLAUDE.md` /
  > `.cursorrules` in a project the agent works from, to your global
  > persona in `~/.hermes/SOUL.md`, or as a named preset under
  > `agent.personalities` in `~/.hermes/config.yaml` (switchable per session
  > via `/personality`).
  > The

## v2p-003 — `simple`  (provenance : `claude_written`)
**Question.** Je veux une mémoire qui se construit une idée de qui je suis au fil des conversations, pas juste un stockage clé-valeur. Quelle option prendre et comment l'activer ?

- Cible `hermes-agent:user-guide/features/honcho.md` — extrait indicatif (vérifier que la cible répond) :

  > # Honcho Memory
  > [Honcho](https://github.com/plastic-labs/honcho) is an AI-native memory backend that adds dialectic reasoning and deep user modeling on top of Hermes's built-in memory system. Instead of simple key-value storage, Honcho maintains a running model of who the user is — their preferences, communication style, goals, and patterns — by reasoning about conversations after they happen.
  > :::info Honcho is a Memory Provider Plugin
  > Honcho is integrated into the [Memory Providers](./memory-providers.md) system. All features below are available through the unified memory provider interface.
  > :::
  > ## What Honcho Adds
  > | Capability | Built
- Distracteur `hermes-agent:developer-guide/memory-provider-plugin.md` — extrait (ne doit PAS mieux répondre) :

  > :::tip Minimal vs Full Schema
  > Every field in `get_config_schema()` is prompted during `hermes memory setup`. Providers with many options should keep the schema minimal — only include fields the user **must** configure (API key, required credentials). Document optional settings in a config file reference (e.g. `$HERMES_HOME/myprovider.json`) rather than prompting for them all during setup. This keeps the setup wizard fast while still supporting advanced configuration. See the Supermemory provider for an example — it only prompts for the API key; all other options live in `supermemory.json`.
  > :::
  > ## Save Config
  > ```python
  > def save_config(self

## v2p-004 — `simple`  (provenance : `claude_written`)
**Question.** Comment ne plus avoir mes clés API en clair dans un .env, et les faire récupérer depuis mon gestionnaire de mots de passe au lancement de l'agent ?

- Cible `hermes-agent:user-guide/secrets/onepassword.md` — extrait indicatif (vérifier que la cible répond) :

  > ## Authentication
  > `op` supports two non-interactive-friendly modes; Hermes works with either:
  > - **Service accounts** (recommended for servers/CI): create a service account in 1Password, grant it read access to the relevant vault, and export its token as `OP_SERVICE_ACCOUNT_TOKEN` in `~/.hermes/.env`. The token is the credential — treat it like any other bearer token.
  > - **Desktop / interactive sessions** (laptops): run `op signin` (or enable CLI integration in the 1Password app). Hermes passes your `OP_SESSION_*` variables through to the `op` child process. The 1Password cache key includes those session variables, so signing into a differe
- Distracteur `hermes-agent:reference/environment-variables.md` — extrait (ne doit PAS mieux répondre) :

  > | Variable | Description |
  > |----------|-------------|
  > | `HERMES_SESSION_ID` | **Exported automatically into every tool subprocess** Hermes spawns (`terminal`, `execute_code`, persistent shell, Docker/Singularity backends, delegated subagent runs). Set by the agent to the current session ID; user scripts called from tools can read it to correlate their output, telemetry, or side effects with the originating Hermes session. **You should not set this manually** — overriding it from a parent shell only takes effect outside an agent run, and is overwritten the moment the agent starts a session. |
  > | `AI_AGENT` | **Set to `hermes-agent` by the CLI

## v2p-005 — `simple`  (provenance : `claude_written`)
**Question.** Je veux parler à l'agent depuis une messagerie décentralisée qui ne donne aucun identifiant permanent aux utilisateurs. C'est possible, et comment je configure le bot ?

- Cible `hermes-agent:user-guide/messaging/simplex.md` — extrait indicatif (vérifier que la cible répond) :

  > ```bash
  > # Linux / macOS binary
  > curl -L https://github.com/simplex-chat/simplex-chat/releases/latest/download/simplex-chat-ubuntu-22_04-x86_64 -o simplex-chat
  > chmod +x simplex-chat
  > ```
  > The SimpleX Chat project does not publish a prebuilt Docker image for the chat client; to run it under Docker, build from source from the [simplex-chat repository](https://github.com/simplex-chat/simplex-chat).
  > ## Start the daemon
  > ```bash
  > simplex-chat -p 5225
  > ```
  > The daemon listens on WebSocket at `ws://127.0.0.1:5225` by default.
  > ## Configure Hermes
  > ### Via setup wizard
  > ```bash
  > hermes gateway setup
  > ```
  > Select **SimpleX Chat** and follow the prompts.
- Distracteur `hermes-agent:user-guide/messaging/matrix.md` — extrait (ne doit PAS mieux répondre) :

  > - users share context growth and token costs
  > - one person's long tool-heavy task can bloat everyone else's context
  > - one person's in-flight run can interrupt another person's follow-up in the same room
  > ### Mention and Threading Configuration
  > You can configure mention and auto-threading behavior via environment variables or `config.yaml`:
  > ```yaml
  > matrix:
  >   require_mention: true           # Require @mention in rooms (default: true)
  >   allowed_users:                  # Matrix users allowed to trigger agent turns
  >     - "@alice:matrix.org"
  >   allowed_rooms:                  # Matrix rooms allowed to trigger agent turns
  >     - "!abc123:matrix.org

## v2p-006 — `simple`  (provenance : `claude_written`)
**Question.** Comment je limite les outils que l'agent a le droit d'utiliser, par exemple en couper certains sur Telegram mais pas en ligne de commande, ou seulement le temps d'une session ?

- Cible `hermes-agent:reference/toolsets-reference.md` — extrait indicatif (vérifier que la cible répond) :

  > ## Configuring Toolsets
  > ### Per-session (CLI)
  > ```bash
  > hermes chat --toolsets web,file,terminal
  > hermes chat --toolsets debugging        # composite — expands to file + terminal + web
  > hermes chat --toolsets all              # everything
  > ```
  > ### Per-platform (config.yaml)
  > ```yaml
  > toolsets:
  >   - hermes-cli          # default for CLI
  >   # - hermes-telegram   # override for Telegram gateway
  > ```
  > ### Interactive management
  > ```bash
  > hermes tools                            # curses UI to enable/disable per platform
  > ```
  > Or in-session:
  > ```
  > /tools list
  > /tools disable browser
  > /tools enable homeassistant
  > ```
  > ## Core Toolsets
  > | Toolset | Tools | Pur
- Distracteur `hermes-agent:user-guide/features/tool-gateway.md` — extrait (ne doit PAS mieux répondre) :

  > | | Tool | What you get |
  > |---|---|---|
  > | 🔍 | **Web search & extract** | Agent-grade web search and full-page extraction via Firecrawl. No rate limits to worry about — the gateway handles scaling. |
  > | 🎨 | **Image generation** | Nine models under one endpoint: **FLUX 2 Klein 9B**, **FLUX 2 Pro**, **Z-Image Turbo**, **Nano Banana Pro** (Gemini 3 Pro Image), **GPT Image 1.5**, **GPT Image 2**, **Ideogram V3**, **Recraft V4 Pro**, **Qwen Image**. Pick per-generation with a flag, or let Hermes default to FLUX 2 Klein. |
  > | 🔊 | **Text-to-speech** | OpenAI TTS voices wired into the `text_to_speech` tool. Drop voice notes into Telegram, generate aud

## v2p-007 — `simple`  (provenance : `claude_written`)
**Question.** Je veux un bot qui fouille l'actu sur mes sujets chaque matin et m'envoie un résumé de quelques lignes sur Telegram. Comment je le monte de A à Z ?

- Cible `hermes-agent:guides/daily-briefing-bot.md` — extrait indicatif (vérifier que la cible répond) :

  > You'll see output like:
  > ```
  > ID          | Name              | Schedule    | Next Run           | Deliver
  > ------------|-------------------|-------------|--------------------|--------
  > a1b2c3d4    | Morning Briefing  | 0 8 * * *   | 2026-03-09 08:00   | telegram
  > e5f6g7h8    | Evening Recap     | 0 18 * * *  | 2026-03-08 18:00   | telegram
  > ```
  > ### Remove a Job
  > In chat:
  > ```
  > /cron remove a1b2c3d4
  > ```
  > Or ask conversationally:
  > ```
  > Remove my morning briefing cron job.
  > ```
  > Hermes will use `cronjob(action="list")` to find it and `cronjob(action="remove")` to delete it.
  > ### Check Gateway Status
  > Make sure the scheduler is actually running:
  > ```ba
- Distracteur `hermes-agent:guides/automation-blueprints.md` — extrait (ne doit PAS mieux répondre) :

  > ### Delivery Targets
  > | Target | Flag | Notes |
  > |--------|------|-------|
  > | Same chat | `--deliver origin` | Default — delivers to where the job was created |
  > | Local file | `--deliver local` | Saves output, no notification |
  > | Telegram | `--deliver telegram` | Home channel, or `telegram:CHAT_ID` for specific |
  > | Discord | `--deliver discord` | Home channel, or `discord:CHANNEL_ID` |
  > | Slack | `--deliver slack` | Home channel |
  > | SMS | `--deliver sms:+15551234567` | Direct to phone number |
  > | Specific thread | `--deliver telegram:-100123:456` | Telegram forum topic |
  > ### Webhook Template Variables
  > | Variable | Description |
  > |----------|--

## v2p-008 — `simple`  (provenance : `claude_written`)
**Question.** Vous avez des exemples d'automatisations tout prêts à copier, certaines qui tournent à heure fixe et d'autres qui partent quand quelque chose se passe ?

- Cible `hermes-agent:guides/automation-blueprints.md` — extrait indicatif (vérifier que la cible répond) :

  > ```bash
  > hermes cron create "0 8 * * *" \
  >   "Scout these AI agent repositories for notable activity in the last 24 hours:
  > Repos to check:
  > - anthropics/claude-code
  > - openai/codex
  > - All-Hands-AI/OpenHands
  > - Aider-AI/aider
  > For each repo:
  > 1. gh pr list --repo <repo> --state all --json number,title,author,createdAt,mergedAt --limit 15
  > 2. gh issue list --repo <repo> --state open --json number,title,labels,createdAt --limit 10
  > Focus on:
  > - New features being developed
  > - Architectural changes
  > - Integration patterns we could learn from
  > - Security fixes that might affect us too
  > Skip routine dependency bumps and CI fixes. If nothing notable, respond
- Distracteur `hermes-agent:guides/daily-briefing-bot.md` — extrait (ne doit PAS mieux répondre) :

  > # Tutorial: Build a Daily Briefing Bot
  > In this tutorial, you'll build a personal briefing bot that wakes up every morning, researches topics you care about, summarizes the findings, and delivers a concise briefing straight to your Telegram or Discord.
  > By the end, you'll have a fully automated workflow combining **web search**, **cron scheduling**, **delegation**, and **messaging delivery** — no code required.
  > :::tip
  > This recipe hits web search, summarization, and optional TTS — all bundled in a Portal subscription. The fastest setup is `hermes setup --portal`. See [Nous Portal](../integrations/nous-portal.md).
  > :::
  > ## What We're Building

## v2p-009 — `paraphrase`  (provenance : `claude_written`)
**Question.** J'aimerais discuter avec l'agent à l'oral, sans toucher le clavier : je parle, il me répond à voix haute et on enchaîne comme une vraie conversation. Comment j'active ça ?

- Cible `hermes-agent:user-guide/features/voice-mode.md` — extrait indicatif (vérifier que la cible répond) :

  > # Voice Mode
  > Hermes Agent supports full voice interaction across CLI and messaging platforms. Talk to the agent using your microphone, hear spoken replies, and have live voice conversations in Discord voice channels.
  > If you want a practical setup walkthrough with recommended configurations and real usage patterns, see [Use Voice Mode with Hermes](../../guides/use-voice-mode-with-hermes.md).
  > For hands-free session start — saying "hey hermes" (or any phrase) to open a fresh voice session on the CLI, TUI, or desktop app — see [Wake Word](./wake-word.md).
  > ## Prerequisites
  > Before using voice features, make sure you have:
  > 1. **Hermes Agent
- Distracteur `hermes-agent:user-guide/features/tts.md` — extrait (ne doit PAS mieux répondre) :

  > See `agent/tts_provider.py` for the full ABC including docstrings.
  > ## Voice Message Transcription (STT)
  > Voice messages sent on Telegram, Discord, WhatsApp, Slack, or Signal are automatically transcribed and injected as text into the conversation. The agent sees the transcript as normal text.
  > | Provider | Quality | Cost | API Key |
  > |----------|---------|------|---------| 
  > | **Local Whisper** (default) | Good | Free | None needed |
  > | **Groq Whisper API** | Good–Best | Free tier | `GROQ_API_KEY` |
  > | **OpenAI Whisper API** | Good–Best | Paid | `VOICE_TOOLS_OPENAI_KEY` or `OPENAI_API_KEY` |
  > :::info Zero Config
  > Local transcription works out o

## v2p-010 — `paraphrase`  (provenance : `claude_written`)
**Question.** Comment je fais pour que l'agent relise tout seul les propositions de modif sur mon dépôt GitHub et y laisse ses remarques ?

- Cible `hermes-agent:guides/github-pr-review-agent.md` — extrait indicatif (vérifier que la cible répond) :

  > :::tip Want real-time reviews instead?
  > If you have a public endpoint available, check out [Automated GitHub PR Comments with Webhooks](./webhook-github-pr-review.md) — GitHub pushes events to Hermes instantly when PRs are opened or updated.
  > :::
  > ---
  > ## Prerequisites
  > - **Hermes Agent installed** — see the [Installation guide](../getting-started/installation.md)
  > - **Gateway running** for cron jobs:
  >   ```bash
  >   hermes gateway install   # Install as a service
  >   # or
  >   hermes gateway           # Run in foreground
  >   ```
  > - **GitHub CLI (`gh`) installed and authenticated**:
  >   ```bash
  >   # Install
  >   brew install gh        # macOS
  >   sudo apt install
- Distracteur `hermes-agent:guides/webhook-github-pr-review.md` — extrait (ne doit PAS mieux répondre) :

  > This guide walks you through connecting Hermes Agent to GitHub so it automatically fetches a pull request's diff, analyzes the code changes, and posts a comment — triggered by a webhook event with no manual prompting.
  > When a PR is opened or updated, GitHub sends a webhook POST to your Hermes instance. Hermes runs the agent with a prompt that instructs it to retrieve the diff via the `gh` CLI, and the response is posted back to the PR thread.
  > :::tip Want a simpler setup without a public endpoint?
  > If you don't have a public URL or just want to get started quickly, check out [Build a GitHub PR Review Agent](./github-pr-review-agent.md) — use

## v2p-011 — `paraphrase`  (provenance : `claude_written`)
**Question.** L'agent a tout cassé au milieu de la session. Comment je reviens au moment où tout marchait encore ?

- Cible `hermes-agent:user-guide/checkpoints-and-rollback.md` — extrait indicatif (vérifier que la cible répond) :

  > ```mermaid
  > flowchart LR
  >   user["User command\n(hermes, gateway)"]
  >   agent["AIAgent\n(run_agent.py)"]
  >   tools["File & terminal tools"]
  >   cpMgr["CheckpointManager"]
  >   store["Shared shadow store\n~/.hermes/checkpoints/store/"]
  >   user --> agent
  >   agent -->|"tool call"| tools
  >   tools -->|"before mutate\nensure_checkpoint()"| cpMgr
  >   cpMgr -->|"git add/commit-tree/update-ref"| store
  >   cpMgr -->|"OK / skipped"| tools
  >   tools -->|"apply changes"| agent
  > ```
  > ## Configuration
  > Configure in `~/.hermes/config.yaml`:
  > ```yaml
  > checkpoints:
  >   enabled: false              # master switch (default: false — opt-in)
  >   max_snapshots: 20           # max checkpo
- Distracteur `hermes-agent:developer-guide/state-db-recovery.md` — extrait (ne doit PAS mieux répondre) :

  > ```bash
  > hermes gateway stop
  > HERMES_HOME="$HOME/.hermes" hermes sessions recover --source "$HOME/.hermes/state.db" --inspect-only
  > # if recoverable:
  > HERMES_HOME="$HOME/.hermes" hermes sessions recover --source "$HOME/.hermes/state.db" --output "$HOME/recovered-state.db"
  > ```
  > or restore the newest snapshot from `state-snapshots/`.
  > ## Explicit repair
  > Stop every process that can open the profile database before repairing it.
  > Keep them stopped for the complete repair and verification window.
  > ```bash
  > hermes gateway stop
  > HERMES_HOME="$HOME/.hermes" hermes sessions repair --check-only
  > HERMES_HOME="$HOME/.hermes" hermes sessions repair
  > ```
  > `sessi

## v2p-012 — `paraphrase`  (provenance : `claude_written`)
**Question.** Je veux utiliser les modèles proposés par Amazon sur mon compte AWS en me connectant avec mes identifiants AWS, sans clé API. Comment je configure ça ?

- Cible `hermes-agent:guides/aws-bedrock.md` — extrait indicatif (vérifier que la cible répond) :

  > # → Select your region and model
  > # Start chatting
  > hermes chat
  > ```
  > ## Configuration
  > After running `hermes model`, your `~/.hermes/config.yaml` will contain:
  > ```yaml
  > model:
  >   default: us.anthropic.claude-sonnet-4-6
  >   provider: bedrock
  >   base_url: https://bedrock-runtime.us-east-2.amazonaws.com
  > bedrock:
  >   region: us-east-2
  > ```
  > ### Region
  > Set the AWS region in any of these ways (highest priority first):
  > 1. `bedrock.region` in `config.yaml`
  > 2. `AWS_REGION` environment variable
  > 3. `AWS_DEFAULT_REGION` environment variable
  > 4. Default: `us-east-1`
  > ### Guardrails
  > To apply [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/lates
- Distracteur `hermes-agent:guides/google-vertex.md` — extrait (ne doit PAS mieux répondre) :

  > `/model` switches among already-configured providers and models; it does not collect new credentials. Configure Vertex with `hermes model` first.
  > ## Reasoning / Thinking
  > Vertex exposes Gemini's thinking budget through the OpenAI-compatible surface. Hermes maps its reasoning-effort setting onto `extra_body.google.thinking_config` automatically, so `reasoning_effort` works the same way it does on other Gemini surfaces.
  > ## Diagnostics
  > ```bash
  > hermes doctor
  > ```
  > The doctor reports whether Vertex credentials can be resolved (service-account path or ADC) and whether the provider is configured.
  > ## Troubleshooting
  > ### "Vertex AI credentials c

## v2p-013 — `paraphrase`  (provenance : `claude_written`)
**Question.** Comment j'apprends à l'agent une méthode de travail une seule fois, pour qu'il la ressorte de lui-même quand la situation s'y prête ?

- Cible `hermes-agent:user-guide/features/skills.md` — extrait indicatif (vérifier que la cible répond) :

  > #### 5. ClawHub (`clawhub`)
  > A third-party skills marketplace integrated as a community source.
  > - Site: [clawhub.ai](https://clawhub.ai/)
  > - Hermes source id: `clawhub`
  > #### 6. LobeHub (`lobehub`)
  > Hermes can search and convert agent entries from LobeHub's public catalog into installable Hermes skills.
  > - Site: [LobeHub](https://lobehub.com/)
  > - Public agents index: [chat-agents.lobehub.com](https://chat-agents.lobehub.com/)
  > - Backing repo: [lobehub/lobe-chat-agents](https://github.com/lobehub/lobe-chat-agents)
  > - Hermes source id: `lobehub`
  > #### 7. browse.sh (`browse-sh`)
  > Hermes integrates with [browse.sh](https://browse.sh), Browserbase'
- Distracteur `hermes-agent:developer-guide/adding-tools.md` — extrait (ne doit PAS mieux répondre) :

  > The registry handles async bridging transparently — you never call `asyncio.run()` yourself.
  > ## Handlers That Need task_id
  > Tools that manage per-session state receive `task_id` via `**kwargs`:
  > ```python
  > def _handle_weather(args, **kw):
  >     task_id = kw.get("task_id")
  >     return weather_tool(args.get("location", ""), task_id=task_id)
  > registry.register(
  >     name="weather",
  >     ...
  >     handler=_handle_weather,
  > )
  > ```
  > ## Agent-Loop Intercepted Tools
  > Some tools (`todo`, `memory`, `session_search`, `delegate_task`) need access to per-session agent state. These are intercepted by the agent loop (`agent/tool_executor.py`, called from `agent/co

## v2p-015 — `paraphrase`  (provenance : `claude_written`)
**Question.** Comment je demande à l'agent de faire une tâche tout seul à intervalle régulier, par exemple tous les lundis à 9 h, sans rien relancer moi-même ?

- Cible `hermes-agent:guides/automate-with-cron.md` — extrait indicatif (vérifier que la cible répond) :

  > For the full feature reference, see [Scheduled Tasks (Cron)](../user-guide/features/cron.md).
  > :::info Key Concept
  > Cron jobs run in fresh agent sessions with no memory of your current chat. Prompts must be **completely self-contained** — include everything the agent needs to know.
  > :::
  > :::tip Don't need the LLM? You have two zero-token options.
  > - **Recurring watchdog** where the script already produces the exact message (memory alerts, disk alerts, heartbeats): use [script-only cron jobs](./cron-script-only.md). Same scheduler, no LLM. You can ask Hermes to set one up for you in chat — the `cronjob` tool knows when to pick `no_agent=True` a
- Distracteur `hermes-agent:developer-guide/cron-internals.md` — extrait (ne doit PAS mieux répondre) :

  > ### `last_status` literals
  > `last_status` is a closed set written only by `cron.jobs.mark_job_run`. Every
  > renderer (`hermes cron list`/`doctor`, the `cronjob` tool, the web dashboard
  > badge, the Desktop routine inspector) maps each literal explicitly — a consumer
  > must never test `== "ok"` for "the user got their result":
  > | Literal | Meaning | Detail field |
  > |---------|---------|--------------|
  > | `ok` | Agent run succeeded and (if targeted) delivery was confirmed | — |
  > | `error` | Agent run failed | `last_error` |
  > | `delivery_failed` | Agent run succeeded, but the output never reached its target | `last_delivery_error` (`last_error` is `null

## v2p-016 — `paraphrase`  (provenance : `claude_written`)
**Question.** Comment j'oblige l'agent à faire passer toutes ses connexions vers l'extérieur par un point de contrôle que je gère, pour décider où il a le droit d'aller ?

- Cible `hermes-agent:user-guide/egress/iron-proxy.md` — extrait indicatif (vérifier que la cible répond) :

  > We still pre-create `~/.hermes/proxy/audit.log` at `0o600` with `O_NOFOLLOW` because:
  > 1. It reserves the path for the future version bump: when the pinned version moves to one that supports `log.audit_path`, per-request records will start flowing there without operator-side reconfiguration. **Until then the file stays at 0 bytes — do not point monitoring, alerting, or forensics tooling at it yet.** Use `iron-proxy.log` for everything today.
  > 2. The 0o600-from-first-byte guarantee defends against the upstream-fix-day where v0.40+ creates the file under its default umask if it doesn't already exist.
  > Until that version bump lands, treat `iron
- Distracteur `hermes-agent:developer-guide/egress-internals.md` — extrait (ne doit PAS mieux répondre) :

  > ## See also
  > - User-facing setup + troubleshooting: [Egress proxy](https://hermes-agent.nousresearch.com/docs/user-guide/egress/iron-proxy)
  > - Docker backend internals: [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
  > - Bitwarden Secrets Manager integration: [`hermes secrets bitwarden`](https://hermes-agent.nousresearch.com/docs/user-guide/secrets/bitwarden)
  > - CLI command reference: [`hermes egress`](https://hermes-agent.nousresearch.com/docs/reference/cli-commands#hermes-egress)
  > - Sandbox-injected environment variables: [Egress proxy (sandbox-injected)](https://hermes-agent.nousresearch.com/docs/reference/environment-v

## v2p-017 — `no_answer`  (provenance : `claude_written`)
**Question.** Combien de langues la synthèse vocale de l'agent sait-elle parler au total, tous moteurs confondus ?

- Cible : *(aucune — no_answer)*. Distracteur (piège) : `hermes-agent:user-guide/features/tts.md`
- **Preuve d'absence.** Recherche corpus entier : comptes PAR moteur présents (edge 74, piper 44, Mistral STT 13, voice-mode 20) mais AUCUN total 'tous moteurs confondus', et non dérivable (ensembles qui se recoupent, STT != TTS). Fait absent.
- Extrait du distracteur (ne doit PAS répondre) :

  > ## Text-to-Speech
  > Convert text to speech with eleven providers:
  > | Provider | Quality | Cost | API Key |
  > |----------|---------|------|---------|
  > | **Edge TTS** (default) | Good | Free | None needed |
  > | **ElevenLabs** | Excellent | Paid | `ELEVENLABS_API_KEY` |
  > | **OpenAI TTS** | Good | Paid | `VOICE_TOOLS_OPENAI_KEY` |
  > | **MiniMax TTS** | Excellent | Paid | `MINIMAX_API_KEY` or `MINIMAX_CN_API_KEY` |
  > | **Mistral (Voxtral TTS)** | Excellent | Paid | `MISTRAL_API_KEY` |
  > | **Google Gemini TTS** | Excellent | Free tier | `GEMINI_API_KEY` |
  > | **xAI TTS** | Excellent | Paid | `XAI_API_KEY` |
  > | **DeepInfra TTS** | Good | Paid | `DEEPINFRA_API_KEY

## v2p-018 — `no_answer`  (provenance : `chatgpt_draft_claude_verbatim`)
**Question.** Quand je colle un GIF animé dans le terminal, l'agent analyse toutes les images de l'animation ou seulement la première ?

- Cible : *(aucune — no_answer)*. Distracteur (piège) : `hermes-agent:user-guide/features/vision.md`
- **Preuve d'absence.** Recherche corpus entier (first frame / frame-by-frame / each-per-frame / animated gif|image / sampled frames / video) : rien ne décrit quelles images d'un GIF ANIMÉ en entrée la vision analyse. GIF listé comme format accepté, mais traitement de l'animation non documenté et non dérivable. Fait absent.
- Extrait du distracteur (ne doit PAS répondre) :

  > ## Why Terminals Can't Paste Images
  > This is a common source of confusion, so here's the technical explanation:
  > Terminals are **text-based** interfaces. When you press Ctrl+V (or Cmd+V), the terminal emulator:
  > 1. Reads the clipboard for **text content**
  > 2. Wraps it in [bracketed paste](https://en.wikipedia.org/wiki/Bracketed-paste) escape sequences
  > 3. Sends it to the application through the terminal's text stream
  > If the clipboard contains only an image (no text), the terminal has nothing to send. There is no standard terminal escape sequence for binary image data. The terminal simply does nothing.
  > This is why Hermes uses a separate clip

## v2p-019 — `close_distractor`  (provenance : `claude_written`)
**Question.** J'ai une clé d'accès précise à mettre en lieu sûr pour que l'agent la récupère quand il en a besoin. Je n'ai pas besoin d'alterner entre plusieurs clés. Comment je fais ?

- Cible `hermes-agent:user-guide/features/credential-vault.md` — extrait indicatif (vérifier que la cible répond) :

  > There is nothing to set up.
  > ## What it looks like
  > **CLI / TUI**
  > ```
  > 🔐 Save login for github.com
  >    The agent reached a sign-in page with no saved login for this site.
  >    Type the email / username you sign in with (shown), then Enter.
  >    ...
  >    Now the password (hidden). It is encrypted on this machine, bound to
  >    https://github.com, and filled into the page without the model ever seeing it.
  > ```
  > **Desktop** — a "Save your github.com login?" card with an identifier field and
  > a masked password field. *Save & sign in* stores it and continues; *Don't save*
  > tells the agent to stop asking for this turn.
  > From then on the agent lists your save
- Distracteur `hermes-agent:user-guide/features/credential-pools.md` — extrait (ne doit PAS mieux répondre) :

  > ## Delegation & Subagent Sharing
  > When the agent spawns subagents via `delegate_task`, the parent's credential pool is automatically shared with children:
  > - **Same provider** — the child receives the parent's full pool, enabling key rotation on rate limits
  > - **Different provider** — the child loads that provider's own pool (if configured)
  > - **No pool configured** — the child falls back to the inherited single API key
  > This means subagents benefit from the same rate-limit resilience as the parent, with no extra configuration needed. Per-task credential leasing ensures children don't conflict with each other when rotating keys concurrently.

## v2p-020 — `close_distractor`  (provenance : `claude_written`)
**Question.** Comment je donne à l'agent des fichiers de consignes qu'il relit tout seul à chaque session, sans avoir à les mentionner dans chaque message ?

- Cible `hermes-agent:user-guide/features/context-files.md` — extrait indicatif (vérifier que la cible répond) :

  > :::info Priority system
  > Only **one** project context type is loaded per session (first match wins): `.hermes.md` → `AGENTS.override.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`. **SOUL.md** is always loaded independently as the agent identity (slot #1).
  > If an `AGENTS.override.md` exists next to an `AGENTS.md`, the override is loaded **instead of** the committed file — keep a personal (usually gitignored) `AGENTS.override.md` when you want different instructions than the ones checked into the repo, without editing the tracked `AGENTS.md`.
  > :::
  > ## AGENTS.md
  > `AGENTS.md` is the primary project context file. It tells the agent how your pro
- Distracteur `hermes-agent:user-guide/features/context-references.md` — extrait (ne doit PAS mieux répondre) :

  > ### Binary File Detection
  > Binary files are detected via MIME type and null-byte scanning. Known text extensions (`.py`, `.md`, `.json`, `.yaml`, `.toml`, `.js`, `.ts`, etc.) bypass MIME-based detection. Binary files are rejected with a warning.
  > ## Platform Availability
  > Context references are primarily a **CLI feature**. They work in the interactive CLI where `@` triggers tab completion and references are expanded before the message is sent to the agent.
  > In **messaging platforms** (Telegram, Discord, etc.), the `@` syntax is not expanded by the gateway — messages are passed through as-is. The agent itself can still reference files via th

## v2p-021 — `close_distractor`  (provenance : `claude_written`)
**Question.** Je veux que l'agent exécute ses scripts Python dans un environnement isolé, sans risque pour ma machine. Il n'a pas besoin de voir l'écran ni de cliquer dans des fenêtres, juste de lancer du code. Comment je configure ça ?

- Cible `hermes-agent:user-guide/features/code-execution.md` — extrait indicatif (vérifier que la cible répond) :

  > # Code Execution (Programmatic Tool Calling)
  > The `execute_code` tool lets the agent write Python scripts that call Hermes tools programmatically, collapsing multi-step workflows into a single LLM turn. The script runs in a child process on the agent host, communicating with Hermes over a Unix domain socket RPC.
  > ## How It Works
  > 1. The agent writes a Python script using `from hermes_tools import ...`
  > 2. Hermes generates a `hermes_tools.py` stub module with RPC functions
  > 3. Hermes opens a Unix domain socket and starts an RPC listener thread
  > 4. The script runs in a child process — tool calls travel over the socket back to Hermes
  > 5. Only the
- Distracteur `hermes-agent:user-guide/features/computer-use.md` — extrait (ne doit PAS mieux répondre) :

  > These are **platform deep dives, not duplicates of the Hermes skill** —
  > when an agent reports "on Windows, my click landed on the wrong
  > element," it reads `WINDOWS.md` for the UIA / UWP context that
  > explains why and what to do differently.
  > `cua-driver skills status` shows what's installed and which agent
  > harnesses it's linked into. Today the autodetect list covers Claude
  > Code, Codex, OpenCode, OpenClaw, and Antigravity; **Hermes
  > autodetection is planned as a follow-up in `trycua/cua`** — until
  > then, run `cua-driver skills install` once and point your harness at
  > the resulting `~/.cua-driver/skills/cua-driver` directory (or symlink
  > it into y

## v2p-022 — `close_distractor`  (provenance : `claude_written`)
**Question.** Je veux utiliser Gemini avec une simple clé générée sur le site de Google, sans créer de projet cloud ni de compte de service. Comment je configure ça ?

- Cible `hermes-agent:guides/google-gemini.md` — extrait indicatif (vérifier que la cible répond) :

  > # Google Gemini
  > Hermes Agent supports Google Gemini as a native provider using the **Google AI Studio / Gemini API** — not the OpenAI-compatible endpoint. This lets Hermes translate its internal OpenAI-shaped message and tool loop into Gemini's native `generateContent` API while preserving tool calling, streaming, multimodal inputs, and Gemini-specific response metadata.
  > ## Prerequisites
  > - **Google AI Studio API key** — create one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
  > - **Billing-enabled Google Cloud project** — recommended for agent use. Gemini's free tier is too small for long-running agent sessions becaus
- Distracteur `hermes-agent:guides/google-vertex.md` — extrait (ne doit PAS mieux répondre) :

  > ## Available Models
  > Vertex requires the `google/` vendor prefix on model IDs. The `hermes model` picker offers:
  > | Model | ID |
  > |-------|----|
  > | Gemini 3.8 Flash | `google/gemini-3.8-flash` |
  > | Gemini 3.7 Flash | `google/gemini-3.7-flash` |
  > | Gemini 3.1 Pro Preview | `google/gemini-3.1-pro-preview` |
  > | Gemini 3 Pro Preview | `google/gemini-3-pro-preview` |
  > | Gemini 3 Flash Preview | `google/gemini-3-flash-preview` |
  > | Gemini 3.1 Flash Lite Preview | `google/gemini-3.1-flash-lite-preview` |
  > | Gemini 2.5 Pro | `google/gemini-2.5-pro` |
  > | Gemini 2.5 Flash | `google/gemini-2.5-flash` |
  > :::note `global` region for Gemini 3.x
  > The Gemini 3.x pre

## v2p-023 — `close_distractor`  (provenance : `claude_written`)
**Question.** J'ai installé Ollama sur ma machine : comment je le branche à l'agent, avec l'adresse du serveur et le modèle à charger ?

- Cible `hermes-agent:guides/local-ollama-setup.md` — extrait indicatif (vérifier que la cible répond) :

  > ## What This Guide Solves
  > You'll set up Hermes Agent running entirely on your own hardware, using [Ollama](https://ollama.com) as the model backend. No API keys, no subscriptions, no data leaving your machine. Once configured, Hermes works exactly like it does with OpenRouter or Anthropic — terminal commands, file editing, web browsing, delegation — but the model runs locally.
  > By the end, you'll have:
  > - Ollama serving one or more open-weight models
  > - Hermes connected to Ollama as a custom endpoint
  > - A working local agent that can edit files, run commands, and browse the web
  > - Optional: a Telegram/Discord bot powered entirely by your own
- Distracteur `hermes-agent:user-guide/local-models.md` — extrait (ne doit PAS mieux répondre) :

  > If a llama-server is already running on your machine, Hermes detects it
  > and uses it instead of starting its own. Point a custom endpoint at any
  > OpenAI-compatible server for full manual control — the managed runtime is
  > a default, not a requirement. You can enter the server root (for example
  > `http://127.0.0.1:8080`) or the full `/v1` URL: the endpoint test tries
  > both and saves the variant that actually served `/models`, so chat
  > requests go to the same prefix the model list came from. For manual setups (Ollama, MLX, custom
  > builds, headless CLI machines), see
  > [Run Hermes Locally with Ollama](../guides/local-ollama-setup.md) and
  > [Run Local LLMs

## v2p-024 — `close_distractor`  (provenance : `claude_written`)
**Question.** En pleine conversation avec l'agent, quelles commandes je peux taper directement dans le chat, celles qui commencent par une barre oblique, pour changer de modèle ou vider l'historique ?

- Cible `hermes-agent:reference/slash-commands.md` — extrait indicatif (vérifier que la cible répond) :

  > ### Custom model aliases
  > Define your own short names for models you use often, then reach them with `/model <alias>` in a running session, `hermes chat --model <alias>` at startup, or any messaging platform. Aliases work identically in these paths, on session-only (default) and `--global` switches.
  > Two config formats are supported:
  > **Full form** — pin an exact model, provider, and optionally a base URL. Put this in `~/.hermes/config.yaml`:
  > ```yaml
  > model_aliases:
  >   fav:
  >     model: claude-sonnet-4.6
  >     provider: anthropic
  >   grok:
  >     model: grok-4
  >     provider: x-ai
  >   ollama-qwen:
  >     model: qwen3-coder:30b
  >     provider: custom
  >     base_
- Distracteur `hermes-agent:reference/cli-commands.md` — extrait (ne doit PAS mieux répondre) :

  > Examples:
  > ```bash
  > hermes
  > hermes chat -q "Summarize the latest PRs"          # seeds an interactive session
  > hermes chat --oneshot -q "Summarize the latest PRs"  # answer and exit
  > hermes chat --provider openrouter --model anthropic/claude-sonnet-4.6
  > hermes chat --toolsets web,terminal,skills
  > hermes chat --quiet -q "Return only JSON"
  > hermes chat -q "Inspect this repository" --format stream-json
  > hermes chat --worktree -q "Review this repo and open a PR"
  > hermes chat --ignore-user-config --ignore-rules -q "Repro without my personal setup"
  > hermes chat --safe-mode -q "Is this bug mine or Hermes'?"
  > ```
  > ### `--format stream-json` — structured JSONL

## v2p-025 — `close_distractor`  (provenance : `claude_written`)
**Question.** J'ai des applis qui appellent déjà l'API d'OpenAI. Comment je les fais parler à l'agent à la place, juste en changeant l'URL de base ?

- Cible `hermes-agent:user-guide/features/api-server.md` — extrait indicatif (vérifier que la cible répond) :

  > ## Compatible Frontends
  > Any frontend that supports the OpenAI API format works. Tested/documented integrations:
  > | Frontend | Stars | Connection |
  > |----------|-------|------------|
  > | [Open WebUI](../messaging/open-webui.md) | 126k | Full guide available |
  > | LobeChat | 73k | Custom provider endpoint |
  > | LibreChat | 34k | Custom endpoint in librechat.yaml |
  > | AnythingLLM | 56k | Generic OpenAI provider |
  > | NextChat | 87k | BASE_URL env var |
  > | ChatBox | 39k | API Host setting |
  > | Jan | 26k | Remote model config |
  > | HF Chat-UI | 8k | OPENAI_BASE_URL |
  > | big-AGI | 7k | Custom endpoint |
  > | OpenAI Python SDK | — | `OpenAI(base_url="http://localh
- Distracteur `hermes-agent:user-guide/features/acp.md` — extrait (ne doit PAS mieux répondre) :

  > To connect:
  > 1. Open the ACP Client panel from the Activity Bar.
  > 2. Select **Hermes Agent** from the built-in agent list.
  > 3. Connect and start chatting.
  > If you want to define Hermes manually, add it through VS Code settings under `acp.agents`:
  > ```json
  > {
  >   "acp.agents": {
  >     "Hermes Agent": {
  >       "command": "hermes",
  >       "args": ["acp"]
  >     }
  >   }
  > }
  > ```
  > ### Zed
  > Configure Hermes as a custom agent server in Zed settings:
  > 1. Open the Agent Panel.
  > 2. Add a custom agent server with the following configuration:
  > ```json
  > {
  >   "agent_servers": {
  >     "hermes-agent": {
  >       "type": "custom",
  >       "command": "hermes",
  >       "args": ["acp"]

## v2p-026 — `close_distractor`  (provenance : `claude_written`)
**Question.** Dans mon propre code, comment je lance un sous-agent, je suis son état, je l'arrête et je récupère son résultat par programmation ?

- Cible `hermes-agent:developer-guide/subagent-lifecycle-api.md` — extrait indicatif (vérifier que la cible répond) :

  > # Public Subagent Lifecycle API
  > Plugins can launch and supervise fresh Hermes child sessions without importing
  > `tools.delegate_tool`, gateway internals, TUI state, or `AIAgent` fields.
  > The service resolves its parent from the current agent turn, so it works in
  > CLI, gateway, non-interactive, and kanban-worker sessions. Launching outside an
  > active agent turn fails closed with `No active Hermes parent session`.
  > ```python
  > from agent.subagent_lifecycle import SubagentLaunchRequest
  > def launch_review(ctx):
  >     # Call from a plugin tool or hook while an agent turn is active.
  >     service = ctx.subagent_lifecycle
  >     handle = service.launch(Subage
- Distracteur `hermes-agent:user-guide/features/delegation.md` — extrait (ne doit PAS mieux répondre) :

  > One exception: when the parent has a resolved workspace directory, every subagent's system prompt embeds that workspace's **project context files** (`.hermes.md` > AGENTS.md chain > CLAUDE.md > `.cursorrules` — the same discovery, priority, and size caps as the main agent's system prompt; SOUL.md is excluded). Subagents working in a repo operate under the repo's own conventions without having to rediscover them.
  > This means the parent agent must pass **everything** the subagent needs in the call:
  > ```python
  > # BAD - subagent has no idea what "the error" is
  > delegate_task(goal="Fix the error")
  > # GOOD - subagent has all context it needs
  > delega

## v2p-027 — `simple`  (provenance : `chatgpt_draft_claude_verbatim`)
**Question.** Une page récupérée sur le Web apparaît coupée : quelles parties du texte sont conservées dans le résultat, comment repérer cette coupure, et comment consulter le passage du milieu ou augmenter la quantité de texte renvoyée ?

- Cible `hermes-agent:user-guide/features/web-search.md` — extrait indicatif (vérifier que la cible répond) :

  > Get a key at [app.tavily.com](https://app.tavily.com/home). See [Tavily keyless](https://docs.tavily.com/documentation/keyless).
  > ---
  > ### Perplexity
  > [Perplexity's Search API](https://docs.perplexity.ai/docs/search/quickstart) returns ranked, date-stamped results from Perplexity's own index (`web_search`). For `web_extract` it uses the same query-relevant *snippets* route as the official `pplx` CLI: you get the passages of each page that matter, with elisions marked `…`, rather than a verbatim full-page dump — pick Firecrawl / Exa / Parallel as `web.extract_backend` when you need the whole page. Keyed only; there is no anonymous tier.
  > ```
- Distracteur `hermes-agent:reference/tools-reference.md` — extrait (ne doit PAS mieux répondre) :

  > To give an element a durable handle of your own, mark it up:
  > ```html
  > <div data-tour="composer">…</div>
  > ```
  > Handles are applied at the **primitive**, not the call site, so one edit names every instance. The ones that already exist:
  > | Handle | What it names |
  > |---|---|
  > | `overlay-nav` | the left nav of any route overlay (settings, cron, profiles, agents) |
  > | `nav-<id>` | one row in that nav — `nav-models`, `nav-appearance`, … |
  > | `field-<schemaKey>` | one settings row, by its config key — `field-model`, `field-provider`, … |
  > | `page-tabs` | the filter tabs on any `PageSearchShell` page (artifacts, skills, …) |
  > | `artifact-card` | an artifa

## v2p-028 — `simple`  (provenance : `chatgpt_draft_claude_rewritten`)
**Question.** Je veux prévoir des modèles de secours pour mes conversations et pour les tâches d'analyse d'images ou de compression. Où configurer les secours du modèle principal, que doit contenir chaque entrée, et cette liste couvre-t-elle aussi les tâches auxiliaires ?

- Cible `hermes-agent:user-guide/features/fallback-providers.md` — extrait indicatif (vérifier que la cible répond) :

  > ---
  > ## Context Compression Fallback
  > Context compression uses the `auxiliary.compression` config block to control which model and provider handles summarization:
  > ```yaml
  > auxiliary:
  >   compression:
  >     provider: "auto"                              # auto | openrouter | nous | main
  >     model: "google/gemini-3-flash-preview"
  > ```
  > :::info Legacy migration
  > Older configs with `compression.summary_model` / `compression.summary_provider` / `compression.summary_base_url` are automatically migrated to `auxiliary.compression.*` on first load (config version 17).
  > :::
  > If no provider is available for compression, Hermes drops middle conversation turns
- Distracteur `hermes-agent:user-guide/features/credential-pools.md` — extrait (ne doit PAS mieux répondre) :

  > :::warning Key rotation resets the prompt cache
  > Provider-side prompt caches (Anthropic, OpenAI, OpenRouter) are scoped to the account/API key that made the request. When the pool rotates to a different key mid-session, the new key has no cached prefix for your conversation — the next request re-reads the full history at undiscounted input price, and rotating back later is another full re-read unless the earlier key's cache TTL is still alive. Rotation keeps your session running, which is the point, but on long conversations each rotation costs one full-price pass over the context.
  > :::
  > :::tip
  > Credential pools are mainly for API-key provider

## v2p-029 — `chunk_boundary`  (provenance : `chatgpt_draft_claude_verbatim`)
**Question.** Pour gérer une conversation avec l'API HTTP d'Hermes, quel endpoint exige de renvoyer tout l'historique à chaque requête, et quel endpoint permet de récupérer par identifiant une réponse déjà stockée côté serveur ?

- Cible `hermes-agent:user-guide/features/api-server.md` — extrait indicatif (vérifier que la cible répond) :

  > Add to `~/.hermes/.env`:
  > ```bash
  > API_SERVER_ENABLED=true
  > API_SERVER_KEY=change-me-local-dev
  > # Optional: only if a browser must call Hermes directly
  > # API_SERVER_CORS_ORIGINS=http://localhost:3000
  > ```
  > ### 2. Start the gateway
  > ```bash
  > hermes gateway
  > ```
  > You'll see:
  > ```
  > [API Server] API server listening on http://127.0.0.1:8642
  > ```
  > ### 3. Connect a frontend
  > Point any OpenAI-compatible client at `http://localhost:8642/v1`:
  > ```bash
  > # Test with curl
  > curl http://localhost:8642/v1/chat/completions \
  >   -H "Authorization: Bearer change-me-local-dev" \
  >   -H "Content-Type: application/json" \
  >   -d '{"model": "hermes-agent", "messages": [{"role"
- **Preuve de frontière (chunks disjoints, tokenizer BGE-M3 384/64)** :
  - fait A — endpoint stateless : chunk 1 (chars 1160–2312) — « …Stateless — the full conversation is included in each request via the `messages` array.

*… »
  - fait B — réponse stockée récupérable par id : chunk 8 (chars 7706–8980) — « …Retrieve a previously stored response by ID.

### DELETE /v1/responses/\{id\}

Delete a st… »
  - → aucun chunk unique ne contient les deux faits (vérifié).
- Distracteur `hermes-agent:user-guide/features/acp.md` — extrait (ne doit PAS mieux répondre) :

  > ```json
  > {
  >   "agent_servers": {
  >     "hermes-agent": {
  >       "type": "custom",
  >       "command": "hermes",
  >       "args": ["acp"]
  >     }
  >   }
  > }
  > ```
  > 3. Start a new Hermes external-agent thread.
  > Prerequisites:
  > - Configure Hermes provider credentials first with `hermes model`, or set them in `~/.hermes/.env` / `~/.hermes/config.yaml`.
  > ### JetBrains
  > Use an ACP-compatible plugin and point it at `hermes acp` or `hermes-acp`.
  > ### Buzz Desktop
  > [Buzz](https://github.com/block/buzz) ships Hermes Agent as a preset runtime.
  > With Hermes installed the normal way, Buzz discovers it automatically —
  > open **Settings → Runtimes** and Hermes appears under you

## v2p-030 — `chunk_boundary`  (provenance : `chatgpt_draft_claude_rewritten`)
**Question.** Je veux réduire la taille de state.db : quel nettoyage automatique des anciennes conversations terminées est activé par défaut, quand intervient-il et après quel délai ? Et si je veux toutes les garder sans rien supprimer, quelle commande utiliser à la place ?

- Cible `hermes-agent:user-guide/sessions.md` — extrait indicatif (vérifier que la cible répond) :

  > Repair is deliberately **not automatic**: if the chat has since built up a
  > second history, choosing which thread it continues is your call. The stranded
  > conversation stays readable via `/resume` and session search either way —
  > routing is the only thing the repair changes. Back up first
  > (`cp ~/.hermes/state.db ~/.hermes/state.db.bak`).
  > ### Repair State Crossed Between Profiles
  > Every profile owns one `state.db`, and every gateway session key names the
  > profile that owns the conversation (`agent:main:…` for the default profile,
  > `agent:<name>:…` for a named one). Older releases could leave the two
  > disagreeing — a named profile's rows written i
- **Preuve de frontière (chunks disjoints, tokenizer BGE-M3 384/64)** :
  - fait A — commande non destructive : chunk 2 (chars 2615–3910) — « …sessions optimize` merges FTS5 index segments and
VACUUMs the database without touching an… »
  - fait B — purge auto + rétention : chunk 42 (chars 46815–48100) — « …auto_prune` is `true`, ended sessions inactive for `sessions.retention_days` (default 90)… »
  - → aucun chunk unique ne contient les deux faits (vérifié).
- Distracteur `hermes-agent:developer-guide/state-db-recovery.md` — extrait (ne doit PAS mieux répondre) :

  > `sessions repair` creates a SQLite backup by default and performs structural
  > work through the repository's guarded snapshot-and-promotion path. Do not copy
  > `state.db`, `state.db-wal`, and `state.db-shm` independently with `cp`; those
  > files are one live SQLite image.
  > After repair, verify the health probe, stale marker, trigger set, and canonical
  > row counts before restarting the gateway:
  > ```bash
  > HERMES_HOME="$HOME/.hermes" hermes sessions repair --check-only
  > sqlite3 "$HOME/.hermes/state.db" \
  >   "SELECT key, value FROM state_meta WHERE key = 'fts_stale';"
  > sqlite3 "$HOME/.hermes/state.db" \
  >   "SELECT type, name FROM sqlite_master WHERE name I

## v2p-031 — `simple`  (provenance : `chatgpt_draft_claude_rewritten`)
**Question.** Sur une route webhook, quel effet a deliver_only, et que se passe-t-il au démarrage si je configure aussi un cron_job sur cette même route ?

- Cible `hermes-agent:user-guide/messaging/webhooks.md` — extrait indicatif (vérifier que la cible répond) :

  > ### Via environment variables
  > Add to `~/.hermes/.env`:
  > ```bash
  > WEBHOOK_ENABLED=true
  > WEBHOOK_PORT=8644        # default
  > WEBHOOK_SECRET=your-global-secret
  > ```
  > ### Verify the server
  > Once the gateway is running:
  > ```bash
  > curl http://localhost:8644/health
  > ```
  > Expected response:
  > ```json
  > {"status": "ok", "platform": "webhook"}
  > ```
  > ---
  > ## Configuring Routes {#configuring-routes}
  > Routes define how different webhook sources are handled. Each route is a named entry under `platforms.webhook.extra.routes` in your `config.yaml`. Adapter settings (`port`, `host`, `secret`, `routes`) may also be written directly under `platforms.webhook:` — both s
- Distracteur `hermes-agent:user-guide/features/cron.md` — extrait (ne doit PAS mieux répondre) :

  > ## What cron can do now
  > Cron jobs can:
  > - schedule one-shot or recurring tasks
  > - pause, resume, edit, trigger, and remove jobs
  > - attach zero, one, or multiple skills to a job
  > - deliver results back to the origin chat, local files, or configured platform targets
  > - run in fresh agent sessions with the normal static tool list
  > - run in **no-agent mode** — a script on a schedule, its stdout delivered verbatim, zero LLM involvement (see the [no-agent mode](#no-agent-mode-script-only-jobs) section below)
  > - fire on **external events** — a webhook route with `cron_job` set fires the job the moment something happens (a PR gets feedback, a service po

## v2p-032 — `chunk_boundary`  (provenance : `chatgpt_draft_claude_verbatim`)
**Question.** J'ai compilé mon propre cua-driver : comment demander à Hermes d'utiliser ce binaire, et que fera Hermes s'il détecte ensuite une incompatibilité de version ? Qui devra mettre le binaire à jour ?

- Cible `hermes-agent:user-guide/features/computer-use.md` — extrait indicatif (vérifier que la cible répond) :

  > # macOS/Linux:  which cua-driver
  > ```
  > ### Option B — point Hermes straight at the built binary (fastest loop)
  > Skip the install ceremony entirely: `cargo build` and set
  > `HERMES_CUA_DRIVER_CMD` to the resulting binary. Best for rapid
  > edit/build/test.
  > ```bash
  > cargo build -p cua-driver            # add --release for a release build; run from libs/cua-driver/rust
  > ```
  > ```
  > # Windows (.env)
  > HERMES_CUA_DRIVER_CMD=C:\path\to\cua\libs\cua-driver\rust\target\debug\cua-driver.exe
  > # macOS / Linux (.env)
  > HERMES_CUA_DRIVER_CMD=/path/to/cua/libs/cua-driver/rust/target/debug/cua-driver
  > ```
  > ### Confirm Hermes is using your build
  > - `hermes computer-use sta
- **Preuve de frontière (chunks disjoints, tokenizer BGE-M3 384/64)** :
  - fait A — pointer vers son binaire : chunk 19 (chars 20945–22295) — « …HERMES_CUA_DRIVER_CMD=/path/to/your/cua-driver
```

Swap the backend entirely (for testing… »
  - fait B — reste sous contrôle, pas d'auto-réparation : chunk 2 (chars 2102–3554) — « …reports the incompatibility and leaves it
unchanged.

If you install Cua Driver first, `cu… »
  - → aucun chunk unique ne contient les deux faits (vérifié).
- Distracteur `hermes-agent:user-guide/features/code-execution.md` — extrait (ne doit PAS mieux répondre) :

  > ### `HERMES_*` variables in the child
  > The child process receives only a small, fixed set of operational `HERMES_*`
  > variables by exact name:
  > - `HERMES_HOME`
  > - `HERMES_PROFILE`
  > - `HERMES_CONFIG`
  > - `HERMES_ENV`
  > (plus `HERMES_RPC_DIR` / `HERMES_RPC_SOCKET` / `TZ` / `HOME`, which Hermes
  > injects explicitly so the RPC channel works).
  > :::note Behavior change
  > Earlier versions passed **any** variable whose name began with `HERMES_`
  > through to the child. That broad prefix was removed for security hardening: it
  > could leak `HERMES_*`-named configuration that doesn't match a secret substring
  > (for example `HERMES_BASE_URL`, `HERMES_KANBAN_DB`, or a `H

## v2p-033 — `simple`  (provenance : `chatgpt_draft_claude_verbatim`)
**Question.** Je veux connecter Hermes à un serveur MCP HTTP qui exige un certificat client, avec le certificat et sa clé privée dans deux fichiers séparés et une clé protégée par mot de passe. Où placer ces paramètres dans la configuration, et sous quelle forme fournir les fichiers et le mot de passe ?

- Cible `hermes-agent:reference/mcp-config-reference.md` — extrait indicatif (vérifier que la cible répond) :

  > ### TLS client certificate (mTLS)
  > For HTTP/SSE servers that require a client certificate, set `client_cert` (and optionally `client_key`):
  > ```yaml
  > mcp_servers:
  >   # Combined cert + key in a single PEM file
  >   internal_api:
  >     url: "https://mcp.internal.example.com/mcp"
  >     client_cert: "~/secrets/mcp-client.pem"
  >   # Separate cert and key files
  >   partner_api:
  >     url: "https://mcp.partner.example.com/mcp"
  >     client_cert: "~/secrets/client.crt"
  >     client_key: "~/secrets/client.key"
  >   # Encrypted key with a passphrase (3-element list form)
  >   bank_api:
  >     url: "https://mcp.bank.example.com/mcp"
  >     client_cert: ["~/secrets/client.crt", "~
- Distracteur `hermes-agent:user-guide/features/tool-gateway.md` — extrait (ne doit PAS mieux répondre) :

  > ## Get started
  > There are three ways in — pick whichever fits where you are:
  > ```bash
  > hermes setup --portal     # Fresh install: Nous OAuth + set Nous as provider + turn on the Tool Gateway in one go
  > ```
  > ```bash
  > hermes model              # Switch your inference provider to Nous Portal — Hermes then offers to turn on the gateway for all tools
  > ```
  > ```bash
  > hermes tools              # Enable the gateway per-tool — pick "Nous Subscription" for any tool you want
  > ```
  > `hermes setup --portal` and `hermes model` are the all-at-once paths: log in once, optionally flip every tool to the gateway. `hermes tools` is the à la carte path — turn on just t
