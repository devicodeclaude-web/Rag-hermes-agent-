# Paquet de revue humaine — dataset-v1 (100 questions)
Généré par `scripts/build_review_package.py`. Règles : lire chaque extrait, ne consulter aucun score BGE-M3/reranker, ne pas valider une question au seul motif que le document contient son titre. Reporte tes décisions dans `dataset-v1-full-100.csv`. Un cas `no_answer` est correct si AUCUN document ne répond : vérifie-le sur l'extrait du distracteur.

---

## v1-001 · simple
**Question :** What does the Hermes documentation section 'ACP Internals' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/acp-internals.md` — **ACP Internals**

  > # ACP Internals The ACP adapter wraps Hermes' synchronous `AIAgent` in an async JSON-RPC stdio server. Key implementation files: - `acp_adapter/entry.py` - `acp_adapter/server.py` - `acp_adapter/session.py` - `acp_adapter/events.py` - `acp_adapter/permissions.py` - `acp_adapter/tools.py` - `acp_adapter/auth.py` ## Boot flow ```text hermes acp / hermes-acp / python -m acp_adapter -> acp_adapter.entry.main() -> parse --version / --check / --setup before server startup -> load ~/.hermes/.env -> configure stderr logging -> construct HermesACPAgent -> acp.run_agent(agent, use_unstable_protocol=True) ``` Stdout is reserved for ACP JSON-RPC transport. Human-readable logs go to stderr. ## Major […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-002 · simple
**Question :** What does the Hermes documentation section 'Adding a Platform Adapter' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/adding-platform-adapters.md` — **(sans titre)**

  > # Adding a Platform Adapter This guide covers adding a new messaging platform to the Hermes gateway. A platform adapter connects Hermes to an external messaging service (Telegram, Discord, WeCom, etc.) so users can interact with the agent through that service. :::tip There are two ways to add a platform: - **Plugin** (recommended for community/third-party): Drop a plugin directory into `~/.hermes/plugins/` — zero core code changes needed. See [Plugin Path](#plugin-path-recommended) below. - **Built-in**: Modify 20+ files across code, config, and docs. Use the [Built-in Checklist](#step-by-step-checklist-built-in-path) below. ::: ## Architecture Overview ``` User ↔ Messaging Platform ↔ […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

---

## v1-003 · simple
**Question :** What does the Hermes documentation section 'Adding Providers' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/adding-providers.md` — **Adding Providers**

  > # Adding Providers Hermes can already talk to any OpenAI-compatible endpoint through the custom provider path. Do not add a built-in provider unless you want first-class UX for that service: - provider-specific auth or token refresh - a curated model catalog - setup / `hermes model` menu entries - provider aliases for `provider:model` syntax - a non-OpenAI API shape that needs an adapter If the provider is just "another OpenAI-compatible base URL and API key", a named custom provider may be enough. ## The mental model A built-in provider has to line up across a few layers: 1. `hermes_cli/auth.py` decides how credentials are found. 2. `hermes_cli/runtime_provider.py` turns that into runtime […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

---

## v1-004 · simple
**Question :** What does the Hermes documentation section 'Adding Tools' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/adding-tools.md` — **Adding Tools**

  > # Adding Tools Before writing a tool, ask yourself: **should this be a [skill](creating-skills.md) instead?** :::warning Built-in Core Tools Only This page is for adding a **built-in Hermes tool** to the repository itself. If you want a personal, project-local, or otherwise custom tool without modifying Hermes core, use the plugin route instead: - [Plugins](../user-guide/features/plugins.md) - [Build a Hermes Plugin](./plugins/index.md) Default to plugins for most custom tool creation. Only follow this page when you explicitly want to ship a new built-in tool in `tools/` and `toolsets.py`. ::: Make it a **Skill** when the capability can be expressed as instructions + shell commands + […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

---

## v1-005 · simple
**Question :** What does the Hermes documentation section 'Agent Loop Internals' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/agent-loop.md` — **Agent Loop Internals**

  > # Agent Loop Internals The core orchestration engine is the `AIAgent` class. `run_agent.py` is now a thin facade: the loop itself lives in `agent/conversation_loop.py`, each turn phase in `agent/turn_*.py` (iteration prep, API call, API error, overflow, truncation, recovery), constructor wiring in `agent/agent_init.py`, and everything from prompt assembly to tool dispatch to provider failover in focused `agent/*.py` modules mixed into `AIAgent`. ## Core Responsibilities `AIAgent` is responsible for: - Assembling the effective system prompt and tool schemas via `prompt_builder.py` - Selecting the correct provider/API mode (chat_completions, codex_responses, anthropic_messages) - Making […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-006 · simple
**Question :** What does the Hermes documentation section 'Architecture' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/bundled/creative/creative-architecture-diagram.md` — **Architecture Diagram — Dark-themed SVG architecture/cloud/infra diagrams as HTML**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Architecture Diagram Dark-themed SVG architecture/cloud/infra diagrams as HTML. ## Skill metadata | | | |---|---| | Source | Bundled (installed by default) | | Path | `skills/creative\architecture-diagram` | | Version | `1.0.0` | | Author | Cocoon AI (hello@cocoon-ai.com), ported by Hermes Agent | | License | MIT | | Platforms | linux, macos, windows | | Tags | `architecture`, `diagrams`, `SVG`, `HTML`, `visualization`, `infrastructure`, `cloud` | | Related skills | [`concept-diagrams`](../../optional/creative/creative-concept-diagrams.md), […]

---

## v1-007 · simple
**Question :** What does the Hermes documentation section 'Billing lifecycle: client-side state, errors, and recovery' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/billing-lifecycle.md` — **Billing Lifecycle (TUI)**

  > # Billing lifecycle: client-side state, errors, and recovery This is the map from every `billing.*`/`subscription.*` state shape the gateway serves (from NAS) to what the terminal actually renders, and from every typed refusal/error code to its exact user-facing copy and recovery action. The guarantee: no NAS billing state and no typed refusal falls through to a generic toast — every case below is an explicit branch in `ui-tui/src/app/slash/commands/topup.ts`, `ui-tui/src/components/billingOverlay.tsx`, or `ui-tui/src/components/subscriptionOverlay.tsx`. An **unknown** code still degrades gracefully: it hits the `default` branch (a generic-but-real message pulled from the server payload, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-monitoring.md` — **Gateway Monitoring**

  > # Gateway Monitoring Service health monitoring plus structured operational diagnostics for the Hermes gateway daemon, exported over OTLP/HTTP to an operator-configured endpoint (OpenTelemetry Collector, DataDog, or any OTLP receiver). This plane is content-free by construction. It exports gateway and cron lifecycle state, platform connector health, and content-free warning/error diagnostics. It never exports prompts, messages, tool arguments or results, job names, destinations, schedules, raw errors, session history, usage analytics, audit logs, or detailed execution traces. Run/model/tool trajectory capture is a separate plane served by Hermes's native NeMo Relay SDK integration and […]

---

## v1-008 · simple
**Question :** What does the Hermes documentation section 'Building a Browser Provider Plugin' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/browser-provider-plugin.md` — **Browser Provider Plugins**

  > # Building a Browser Provider Plugin Browser provider plugins register a **cloud browser backend** that services cloud-mode `browser_*` tool calls (navigate, click, screenshot, …). Built-in providers — Browserbase, Browser Use, and Firecrawl — all ship as plugins under `plugins/browser/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Browser backends are one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Web Search Provider Plugins](./web-search-provider-plugin.md) (which this ABC deliberately mirrors), [Image Generation](./image-gen-provider-plugin.md), [Video […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/programmatic-integration.md` — **Programmatic Integration**

  > # Programmatic Integration Hermes ships three protocols for driving the agent from external programs — IDE plugins, custom UIs, CI pipelines, embedded sub-agents. Pick the one that matches your transport and consumer. | Protocol | Transport | Best for | Defined by | |----------|-----------|----------|------------| | **ACP** | JSON-RPC over stdio | IDE clients (VS Code, Zed, JetBrains) that already speak the [Agent Client Protocol](https://github.com/zed-industries/agent-client-protocol) | `acp_adapter/` | | **TUI gateway** | JSON-RPC over stdio (or WebSocket) | Custom hosts that want fine-grained control of sessions, slash commands, approvals, and streaming events | `tui_gateway/server.py` […]

---

## v1-009 · simple
**Question :** What does the Hermes documentation section 'Browser CDP Supervisor' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/browser-supervisor.md` — **Browser CDP Supervisor**

  > # Browser CDP Supervisor The CDP supervisor closes two long-standing gaps in Hermes' browser tooling: 1. **Native JS dialogs** (`alert`/`confirm`/`prompt`/`beforeunload`) block the page's JS thread. Without supervision, the agent has no way to know a dialog is open — subsequent tool calls hang or throw opaque errors. 2. **Cross-origin iframes (OOPIFs)** are invisible to top-level `Runtime.evaluate`. The agent can see iframe nodes in the DOM snapshot but can't click, type, or eval inside them without a CDP session attached to the child target. The supervisor solves both by holding a persistent WebSocket to the backend's CDP endpoint per browser task, surfacing pending dialogs and frame […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/browser.md` — **Browser Automation**

  > # Browser Automation Hermes Agent includes a full browser automation toolset with multiple backend options: - **Browser Use cloud mode** via [Browser Use](https://browser-use.com) for managed Chromium with stealth, residential proxies, CAPTCHA solving, and reusable browser profiles - **Browserbase cloud mode** via [Browserbase](https://browserbase.com) as an alternative cloud browser provider with anti-bot tooling - **Browser Use mode** via the [Browser Use CLI 3.0](https://github.com/browser-use/browser-use), the default browser driver for local Chrome and Browser Use cloud browsers - **Firecrawl cloud mode** via [Firecrawl](https://firecrawl.dev) for cloud browsers with built-in scraping […]

---

## v1-010 · simple
**Question :** What does the Hermes documentation section 'Chronos managed-cron — agent ↔ NAS wire contract' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/chronos-managed-cron-contract.md` — **Chronos Managed-Cron Contract**

  > # Chronos managed-cron — agent ↔ NAS wire contract **Status:** authoritative wire spec for the Chronos cron provider. **Audience:** the NAS-side implementer of the `agent-cron` endpoints (`nous-account-service`) and anyone debugging the managed-cron path. Chronos lets a hosted Hermes gateway **scale to zero** while idle and still fire cron jobs. Instead of an in-process 60-second ticker, the agent asks NAS to arm exactly **one external one-shot per job at that job's real next-fire time**. NAS calls the agent back at fire time over an authenticated webhook; the agent runs the job and re-arms the next one-shot. Between fires the agent process can be fully stopped — it wakes only on a genuine […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/cron-internals.md` — **Cron Internals**

  > # Cron Internals The cron subsystem provides scheduled task execution — from simple one-shot delays to recurring cron-expression jobs with skill injection and cross-platform delivery. ## Key Files | File | Purpose | |------|---------| | `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` | | `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking | | `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler | | `gateway/run.py` | Gateway integration — cron ticking in the long-running loop | | `hermes_cli/cron.py` | CLI `hermes cron` subcommands | ## Scheduling Model Four schedule formats are supported: | Format | Example | […]

---

## v1-011 · simple
**Question :** What does the Hermes documentation section 'CLI Internals' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/cli-internals.md` — **CLI Internals**

  > # CLI Internals Companion to `hermes_cli/AGENTS.md` (the rules) — this page holds the longer explanations. ## Update pipeline The stage-by-stage contract (`plan → snapshot → apply → restart-per-kind → verify → report`) and the field failure each stage guards are documented in `hermes_cli/AGENTS.md`; user-facing behaviour (receipts, `--plan`, snapshot modes) is in [Updating](../getting-started/updating.md). The systemd blunt-restart fallback waits for the unit's `TimeoutStopUSec` plus `TimeoutStartUSec`, with 15 seconds of client-side slack. It reads the target unit in the same manager scope as the restart; both the initial attempt and retry use this budget, including the catch-up restart […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-012 · simple
**Question :** What does the Hermes documentation section 'Codebase Ownership Map' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/optional/software-development/software-development-code-wiki.md` — **Code Wiki — Generate wiki docs + Mermaid diagrams for any codebase**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Code Wiki Generate wiki docs + Mermaid diagrams for any codebase. ## Skill metadata | | | |---|---| | Source | Optional — install with `hermes skills install official/software-development/code-wiki` | | Path | `optional-skills/software-development\code-wiki` | | Version | `0.1.0` | | Author | Teknium (teknium1), Hermes Agent | | License | MIT | | Platforms | linux, macos, windows | | Tags | `Documentation`, `Mermaid`, `Architecture`, `Diagrams`, `Wiki`, `Code-Analysis` | | Related skills | […]

---

## v1-013 · simple
**Question :** What does the Hermes documentation section 'Background completion backlogs' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/completion-backlog-delivery.md` — **Background completion backlogs**

  > # Background completion backlogs Interactive surfaces coalesce consecutive background-process completions that are already ready for one conversation into a single notification turn. This does not add a delay or promise to combine jobs that finish at different times. Failures and successful outputs remain in the batch; one completion keeps its original text. Process identity remains available until dispatch. Explicit `process_manage` wait/log/kill consumption can therefore suppress a CLI completion even after it has left the process registry and entered the input queue. An entirely consumed batch starts no turn. Watching output and async-delegation results remain separate notifications, in […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

---

## v1-014 · simple
**Question :** What does the Hermes documentation section 'Context Compression and Caching' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/context-compression-and-caching.md` — **(sans titre)**

  > # Context Compression and Caching Hermes Agent uses a dual compression system and Anthropic prompt caching to manage context window usage efficiently across long conversations. Source files: `agent/context_engine.py` (ABC), `agent/context_compressor.py` (default engine), `agent/prompt_caching.py`, `gateway/run_turn.py` (session hygiene), `agent/compression_facade.py` (search for `_compress_context`) ## Bedrock context window cache Bedrock context resolution in `agent/model_metadata.py` uses this precedence: - **Explicit overrides win.** Configured context lengths take priority over cache, probes, and the static table. - **Provider-confirmed limits persist.** A successful probe or a limit […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-015 · simple
**Question :** What does the Hermes documentation section 'Building a Context Engine Plugin' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/context-engine-plugin.md` — **Context Engine Plugins**

  > # Building a Context Engine Plugin Context engine plugins replace the built-in `ContextCompressor` with an alternative strategy for managing conversation context. For example, a Lossless Context Management (LCM) engine that builds a knowledge DAG instead of lossy summarization. ## How it works The agent's context management is built on the `ContextEngine` ABC (`agent/context_engine.py`). The built-in `ContextCompressor` is the default implementation. Plugin engines must implement the same interface. Only **one** context engine can be active at a time. Selection is config-driven: ```yaml # config.yaml context: engine: "compressor" # default built-in engine: "lcm" # activates a plugin engine […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/model-provider-plugin.md` — **Model Provider Plugins**

  > # Building a Model Provider Plugin Model provider plugins declare an inference backend — an OpenAI-compatible endpoint, an Anthropic Messages server, a Codex-style Responses API, or a Bedrock-native surface — that Hermes can route `AIAgent` calls through. Every built-in provider (OpenRouter, Anthropic, GMI, DeepSeek, Nvidia, …) ships as one of these plugins. Third parties can add their own by dropping a directory under `$HERMES_HOME/plugins/model-providers/` with zero changes to the repo. :::tip Model provider plugins are the third kind of **provider plugin**. The others are [Memory Provider Plugins](./memory-provider-plugin.md) (cross-session knowledge) and [Context Engine […]

---

## v1-016 · simple
**Question :** What does the Hermes documentation section 'Contributing' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/contributing.md` — **Contributing**

  > # Contributing Thank you for contributing to Hermes Agent! This guide covers setting up your dev environment, understanding the codebase, and getting your PR merged. ## Contribution Priorities We value contributions in this order: 1. **Bug fixes** — crashes, incorrect behavior, data loss 2. **Cross-platform compatibility** — macOS, different Linux distros, WSL2 3. **Security hardening** — shell injection, prompt injection, path traversal 4. **Performance and robustness** — retry logic, error handling, graceful degradation 5. **New skills** — broadly useful ones (see [Creating Skills](creating-skills.md)) 6. **New tools** — rarely needed; most capabilities should be skills 7. […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

---

## v1-017 · simple
**Question :** What does the Hermes documentation section 'Creating Skills' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/creating-skills.md` — **Creating Skills**

  > # Creating Skills Skills are the preferred way to add new capabilities to Hermes Agent. They're easier to create than tools, require no code changes to the agent, and can be shared with the community. ## Should it be a Skill or a Tool? Make it a **Skill** when: - The capability can be expressed as instructions + shell commands + existing tools - It wraps an external CLI or API that the agent can call via `terminal` or `web_extract` - It doesn't need custom Python integration or API key management baked into the agent - Examples: arXiv search, git workflows, Docker management, PDF processing, email via CLI tools Make it a **Tool** when: - It requires end-to-end integration with API keys, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/contributing.md` — **Contributing**

  > # Contributing Thank you for contributing to Hermes Agent! This guide covers setting up your dev environment, understanding the codebase, and getting your PR merged. ## Contribution Priorities We value contributions in this order: 1. **Bug fixes** — crashes, incorrect behavior, data loss 2. **Cross-platform compatibility** — macOS, different Linux distros, WSL2 3. **Security hardening** — shell injection, prompt injection, path traversal 4. **Performance and robustness** — retry logic, error handling, graceful degradation 5. **New skills** — broadly useful ones (see [Creating Skills](creating-skills.md)) 6. **New tools** — rarely needed; most capabilities should be skills 7. […]

---

## v1-018 · simple
**Question :** What does the Hermes documentation section 'Cron Internals' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/cron-internals.md` — **Cron Internals**

  > # Cron Internals The cron subsystem provides scheduled task execution — from simple one-shot delays to recurring cron-expression jobs with skill injection and cross-platform delivery. ## Key Files | File | Purpose | |------|---------| | `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` | | `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking | | `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler | | `gateway/run.py` | Gateway integration — cron ticking in the long-running loop | | `hermes_cli/cron.py` | CLI `hermes cron` subcommands | ## Scheduling Model Four schedule formats are supported: | Format | Example | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

---

## v1-019 · simple
**Question :** What does the Hermes documentation section 'Desktop Plugin SDK' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/desktop-plugin-sdk.md` — **Desktop Plugin SDK (@hermes/plugin-sdk)**

  > # Desktop Plugin SDK The native [Hermes Desktop](../user-guide/desktop.md) app is contribution-driven: every surface in the window — panes, routes, sidebar nav, status-bar items, palette entries, keybinds, themes — registers into one central registry. Core registers its surfaces exactly the way a plugin does, so the plugin story is the real one, not a bolted-on afterthought. A **desktop plugin** is a single ESM file that default-exports a `HermesPlugin`. It imports one module — `@hermes/plugin-sdk` — and gets everything: the app's live state, the gateway JSON-RPC door, a scoped REST/socket backend namespace, React Query, and the app's own UI kit so plugin UI looks native by default. No repo […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/extending-the-dashboard.md` — **Extending the Dashboard**

  > # Extending the Dashboard The Hermes web dashboard (`hermes dashboard`) is built to be reskinned and extended without forking the codebase. Three layers are exposed: 1. **Themes** — YAML files that repaint the dashboard's palette, typography, layout, and per-component chrome. Drop a file in `~/.hermes/dashboard-themes/`; it appears in the theme switcher. 2. **UI plugins** — a directory with `manifest.json` + a JavaScript bundle that registers a tab, replaces a built-in page, augments one via page-scoped slots, or injects components into named shell slots. 3. **Backend plugins** — a Python file inside that plugin directory that exposes a FastAPI `router`; routes are mounted under […]

---

## v1-020 · simple
**Question :** What does the Hermes documentation section 'Egress proxy internals' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/egress-internals.md` — **Egress proxy internals**

  > # Egress proxy internals This page covers the architecture of the egress credential-injection firewall (`hermes egress` / iron-proxy) from a contributor / plugin author's perspective. End-user setup + usage docs live at [Egress proxy](../user-guide/egress/iron-proxy.md). The threat model and high-level design are summarised on the user page; this page is about *how* it's wired, where the security-relevant code lives, and what invariants you have to preserve if you touch it. ## Module layout ```text agent/proxy_sources/iron_proxy.py Core: binary install, CA gen, config build, subprocess lifecycle, mappings I/O, PID/nonce defense. Pure-function surface where possible. hermes_cli/proxy_cli.py […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/egress/iron-proxy.md` — **(sans titre)**

  > # Egress credential-injection proxy (iron-proxy) When Hermes runs your agent inside a Docker terminal sandbox, that sandbox normally holds your real upstream API keys (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, etc.). A prompt-injected agent in that sandbox can `cat ~/.config/openrouter/auth.json` or `printenv | grep -i key` and exfiltrate them. The egress proxy fixes this: the sandbox holds opaque **proxy tokens**, never the real keys. All outbound traffic from the sandbox routes through a local [iron-proxy](https://github.com/ironsh/iron-proxy) daemon (Apache-2.0, Go) on the host, which terminates TLS and swaps the proxy token for the real credential before forwarding the request upstream. […]

---

## v1-021 · simple
**Question :** What does the Hermes documentation section 'Extending the CLI' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/extending-the-cli.md` — **Extending the CLI**

  > # Extending the CLI Hermes exposes protected extension hooks on `HermesCLI` so wrapper CLIs can add widgets, keybindings, and layout customizations without overriding the `run()` method or the TUI construction in `hermes_cli/cli_tui_mixin.py` (where these hooks are defined; `HermesCLI` in `cli.py` mixes it in). This keeps your extension decoupled from internal changes. ## Extension points There are five extension seams available: | Hook | Purpose | Override when... | |------|---------|------------------| | `_get_extra_tui_widgets()` | Inject widgets into the layout | You need a persistent UI element (panel, status line, mini-player) | | `_register_extra_tui_keybindings(kb, *, input_area)` | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

---

## v1-022 · simple
**Question :** What does the Hermes documentation section 'Gateway Internals' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-023 · simple
**Question :** What does the Hermes documentation section 'Gateway Monitoring' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/gateway-monitoring.md` — **Gateway Monitoring**

  > # Gateway Monitoring Service health monitoring plus structured operational diagnostics for the Hermes gateway daemon, exported over OTLP/HTTP to an operator-configured endpoint (OpenTelemetry Collector, DataDog, or any OTLP receiver). This plane is content-free by construction. It exports gateway and cron lifecycle state, platform connector health, and content-free warning/error diagnostics. It never exports prompts, messages, tool arguments or results, job names, destinations, schedules, raw errors, session history, usage analytics, audit logs, or detailed execution traces. Run/model/tool trajectory capture is a separate plane served by Hermes's native NeMo Relay SDK integration and […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/pipe-script-output.md` — **Pipe Script Output to Messaging Platforms**

  > # Pipe Script Output to Messaging Platforms `hermes send` is a small, scriptable CLI that pushes a message to any messaging platform Hermes is already configured for. Think of it as a cross-platform `curl` for notifications — you don't need a running gateway, you don't need an LLM, and you don't need to re-paste bot tokens into each of your scripts. Use it for: - System monitoring (memory, disk, GPU temp, long-running job finished) - CI/CD notifications (deploy done, test failure) - Cron scripts that need to ping you with results - Quick one-shot messages from a terminal - Piping any tool's output anywhere (`make | hermes send --to slack:#builds`) The command reuses the same credentials and […]

---

## v1-024 · simple
**Question :** What does the Hermes documentation section 'Session Lifecycle' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/gateway-session-lifecycle.md` — **Gateway Session Lifecycle**

  > # Session Lifecycle > **Audience:** Gateway developers and maintainers > **Source files:** `gateway/session.py` (~1200 lines + `session_*.py` siblings), `gateway/run.py` (~5500 lines facade + `run_*.py` phases), `gateway/config.py` > **Last updated:** 2026-06-16 ## Overview A **session** represents a continuous conversation between the agent and one or more users on a messaging platform. The session lifecycle governs when conversations persist, when they reset, how they survive gateway restarts, and how messages queue during concurrent operations. The session system lives primarily in two modules: - `gateway/session.py` — Data model (`SessionSource`, `SessionEntry`, `SessionContext`), key […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/observer-hooks.md` — **Observer Hooks**

  > # Hermes Observer Hooks Hermes observer hooks are the read-only telemetry contract for plugins that need to reconstruct agent execution without changing runtime behavior. This contract supports trace, metrics, audit, replay, and export integrations such as Langfuse, OpenTelemetry-style collectors, and NeMo Relay. Observer hooks are intentionally backend-neutral. They expose stable lifecycle events, correlation IDs, sanitized payloads, timing, status, and error fields. They do not replace Hermes' planner, model providers, memory, tool registry, approval UX, CLI, gateway behavior, or execution semantics. Behavior-changing request or execution wrappers are outside this observer contract. […]

---

## v1-025 · simple
**Question :** What does the Hermes documentation section 'Building an Image Generation Provider Plugin' explain?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/image-gen-provider-plugin.md` — **Image Generation Provider Plugins**

  > # Building an Image Generation Provider Plugin Image-gen provider plugins register a backend that services every `image_generate` tool call — DALL·E, gpt-image, Grok, Flux, Imagen, Stable Diffusion, fal, Replicate, a local ComfyUI rig, anything. Built-in providers (OpenAI, OpenAI-Codex, xAI, FAL, Krea, DeepInfra, OpenRouter, Meta Model API) all ship as plugins. You can add a new one, or override a bundled one, by dropping a directory into `plugins/image_gen/<name>/`. :::tip Image-gen is one of several **backend plugins** Hermes supports. The others (with more specialized ABCs) are [Memory Provider Plugins](./memory-provider-plugin.md), [Context Engine Plugins](./context-engine-plugin.md), […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/video-gen-provider-plugin.md` — **Video Generation Provider Plugins**

  > # Building a Video Generation Provider Plugin Video-gen provider plugins register a backend that services every `video_generate` tool call. Built-in providers (xAI, FAL, OpenRouter, DeepInfra) ship as plugins. Add a new one, or override a bundled one, by dropping a directory into `plugins/video_gen/<name>/`. :::tip Video-gen mirrors [Image Generation Provider Plugins](./image-gen-provider-plugin.md) almost line-for-line — if you've built an image-gen backend, you already know the shape. The main differences: a `capabilities()` method advertising modalities/aspect-ratios/durations, and a routing convention (pass `image_url` to use image-to-video, omit it to use text-to-video — the provider […]

---

## v1-026 · paraphrase
**Question :** Summarize the operational guidance in 'Building a Memory Provider Plugin' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/memory-provider-plugin.md` — **Memory Provider Plugins**

  > # Building a Memory Provider Plugin Memory provider plugins give Hermes Agent persistent, cross-session knowledge beyond the built-in MEMORY.md and USER.md. This guide covers how to build one. :::tip Memory providers are one of two **provider plugin** types. The other is [Context Engine Plugins](./context-engine-plugin.md), which replace the built-in context compressor. Both follow the same pattern: single-select, config-driven, managed via `hermes plugins`. ::: ## Installation Layouts Hermes discovers memory providers from four sources, in this precedence order: | Source | Location | Notes | |---|---|---| | Bundled | `plugins/memory/<name>/` | Ships with Hermes. Closed to new providers — […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/model-provider-plugin.md` — **Model Provider Plugins**

  > # Building a Model Provider Plugin Model provider plugins declare an inference backend — an OpenAI-compatible endpoint, an Anthropic Messages server, a Codex-style Responses API, or a Bedrock-native surface — that Hermes can route `AIAgent` calls through. Every built-in provider (OpenRouter, Anthropic, GMI, DeepSeek, Nvidia, …) ships as one of these plugins. Third parties can add their own by dropping a directory under `$HERMES_HOME/plugins/model-providers/` with zero changes to the repo. :::tip Model provider plugins are the third kind of **provider plugin**. The others are [Memory Provider Plugins](./memory-provider-plugin.md) (cross-session knowledge) and [Context Engine […]

---

## v1-027 · paraphrase
**Question :** Summarize the operational guidance in 'Micro-compaction' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/micro-compaction.md` — **Micro-compaction**

  > # Micro-compaction **A way to amortize the cost of compression.** Long conversations eventually outgrow the model's context window, and something has to be thrown away or summarized. Hermes has always done this in one batch: when the transcript crosses a threshold, the session stops, a large chunk of the middle is summarized in a single call, and the conversation resumes. That works, but the whole bill comes due at once — one visible pause, one big summarization request, at whatever moment you happened to cross the line. Micro-compaction pays the same bill in instalments. After each completed turn, Hermes folds the single oldest un-absorbed exchange into a running summary. The work is the […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/memory-provider-plugin.md` — **Memory Provider Plugins**

  > # Building a Memory Provider Plugin Memory provider plugins give Hermes Agent persistent, cross-session knowledge beyond the built-in MEMORY.md and USER.md. This guide covers how to build one. :::tip Memory providers are one of two **provider plugin** types. The other is [Context Engine Plugins](./context-engine-plugin.md), which replace the built-in context compressor. Both follow the same pattern: single-select, config-driven, managed via `hermes plugins`. ::: ## Installation Layouts Hermes discovers memory providers from four sources, in this precedence order: | Source | Location | Notes | |---|---|---| | Bundled | `plugins/memory/<name>/` | Ships with Hermes. Closed to new providers — […]

---

## v1-028 · paraphrase
**Question :** Summarize the operational guidance in 'Hermes Middleware' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/middleware.md` — **Middleware**

  > # Hermes Middleware Hermes middleware is the behavior-changing companion to observer hooks. Observer hooks report what happened. Middleware can change what happens by rewriting a request before execution or by wrapping the execution callback itself. This contract is intentionally backend-neutral. A plugin can use it for local policy, request shaping, tracing, adaptive routing, cache control, sandbox selection, or handoff to runtimes such as NeMo Relay without changing Hermes' planner, model provider adapters, tool registry, memory, or CLI UX. With middleware enabled, plugins can: - Rewrite LLM provider request kwargs before Hermes calls the provider. - Rewrite tool arguments before […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/relay-shared-metrics.md` — **Relay Shared Metrics**

  > # NeMo Relay Shared Metrics Hermes includes NeMo Relay as a normal runtime dependency on platforms for which Relay publishes a native wheel. The shared-metrics integration is built into Hermes and does not require a Hermes observability plugin. Hermes remains importable without Relay on other native targets. Those targets use an explicit reduced-capability no-op host: Hermes execution remains available, while Relay scopes, middleware, plugins, and subscribers are unavailable. The `hermes-agent[nemo-relay]` extra remains as a no-op compatibility alias for existing installation commands. > [!WARNING] > This removes the Hermes `observability/nemo_relay` plugin. Existing users > must remove […]

---

## v1-029 · paraphrase
**Question :** Summarize the operational guidance in 'Building a Model Provider Plugin' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/model-provider-plugin.md` — **Model Provider Plugins**

  > # Building a Model Provider Plugin Model provider plugins declare an inference backend — an OpenAI-compatible endpoint, an Anthropic Messages server, a Codex-style Responses API, or a Bedrock-native surface — that Hermes can route `AIAgent` calls through. Every built-in provider (OpenRouter, Anthropic, GMI, DeepSeek, Nvidia, …) ships as one of these plugins. Third parties can add their own by dropping a directory under `$HERMES_HOME/plugins/model-providers/` with zero changes to the repo. :::tip Model provider plugins are the third kind of **provider plugin**. The others are [Memory Provider Plugins](./memory-provider-plugin.md) (cross-session knowledge) and [Context Engine […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/browser-provider-plugin.md` — **Browser Provider Plugins**

  > # Building a Browser Provider Plugin Browser provider plugins register a **cloud browser backend** that services cloud-mode `browser_*` tool calls (navigate, click, screenshot, …). Built-in providers — Browserbase, Browser Use, and Firecrawl — all ship as plugins under `plugins/browser/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Browser backends are one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Web Search Provider Plugins](./web-search-provider-plugin.md) (which this ABC deliberately mirrors), [Image Generation](./image-gen-provider-plugin.md), [Video […]

---

## v1-030 · paraphrase
**Question :** Summarize the operational guidance in 'Multiplexing Gateway' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/multiplexing-gateway.md` — **Multiplexing Gateway Internals**

  > # Multiplexing Gateway One gateway process can serve every profile in the install. The mode is on by default (`gateway.multiplex_profiles`, default `true`), and everything it changes reverts the moment the flag is off. An *unset* flag is settled at boot by `hermes_cli/gateway_multiplex_mode.py::resolve_multiplex_mode`, which runs the `hermes gateway migrate` preflight and keeps the gateway standalone when a secondary still runs its own gateway, a blocker exists, or the host cannot be migrated (see "The mode flag"). This document is the design rationale referenced from `agent/secret_scope.py` ("Workstream A"): what is isolated per profile, the mechanism that isolates it, and what […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/multi-profile-gateways.md` — **(sans titre)**

  > # Running Many Gateways at Once Operate multiple [profiles](./profiles.md) — each with its own bot tokens, sessions, and memory — as managed services on a single machine. This page covers the operational concerns: starting them all together, viewing logs across profiles, preventing the host from sleeping, and recovering from common launchd/systemd quirks. If you only run one Hermes agent, you don't need this page — see [Profiles](./profiles.md) for the basics. And if your instances live on *different* machines that one desktop app should reach simultaneously, see [Connecting Desktop to Many Hermes Instances](./multi-connection-desktop.md). ## When to use this You want this setup when you […]

---

## v1-031 · paraphrase
**Question :** Summarize the operational guidance in 'Hermes Observer Hooks' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/observer-hooks.md` — **Observer Hooks**

  > # Hermes Observer Hooks Hermes observer hooks are the read-only telemetry contract for plugins that need to reconstruct agent execution without changing runtime behavior. This contract supports trace, metrics, audit, replay, and export integrations such as Langfuse, OpenTelemetry-style collectors, and NeMo Relay. Observer hooks are intentionally backend-neutral. They expose stable lifecycle events, correlation IDs, sanitized payloads, timing, status, and error fields. They do not replace Hermes' planner, model providers, memory, tool registry, approval UX, CLI, gateway behavior, or execution semantics. Behavior-changing request or execution wrappers are outside this observer contract. […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/middleware.md` — **Middleware**

  > # Hermes Middleware Hermes middleware is the behavior-changing companion to observer hooks. Observer hooks report what happened. Middleware can change what happens by rewriting a request before execution or by wrapping the execution callback itself. This contract is intentionally backend-neutral. A plugin can use it for local policy, request shaping, tracing, adaptive routing, cache control, sandbox selection, or handoff to runtimes such as NeMo Relay without changing Hermes' planner, model provider adapters, tool registry, memory, or CLI UX. With middleware enabled, plugins can: - Rewrite LLM provider request kwargs before Hermes calls the provider. - Rewrite tool arguments before […]

---

## v1-032 · paraphrase
**Question :** Summarize the operational guidance in 'Onboarding recommendations' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/onboarding-recommendations.md` — **Onboarding recommendations**

  > # Onboarding recommendations Guided onboarding suggests outcomes from the user's app preferences and observed capabilities. It does not grant access or implement a second connection lifecycle. The feature remains inside the existing `HERMES_GUEST_ONBOARDING` flow. ## What takes priority The existing `machineSetupLeads()` decision still leads with machine setup for a newly set-up machine or a recognized RTX/DGX Spark, with other tasks behind **Something else**. The fresh-machine signal is the existing age heuristic, not proof of the OS installation date. A Spark with unknown age gets a hardware-specific callout, not a claim that its OS is new. Otherwise the guide favors relevant app-backed […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/use-mcp-with-hermes.md` — **Use MCP with Hermes**

  > # Use MCP with Hermes This guide shows how to actually use MCP with Hermes Agent in day-to-day workflows. If the feature page explains what MCP is, this guide is about how to get value from it quickly and safely. ## When should you use MCP? Use MCP when: - a tool already exists in MCP form and you do not want to build a native Hermes tool - you want Hermes to operate against a local or remote system through a clean RPC layer - you want fine-grained per-server exposure control - you want to connect Hermes to internal APIs, databases, or company systems without modifying Hermes core Do not use MCP when: - a built-in Hermes tool already solves the job well - the server exposes a huge dangerous […]

---

## v1-033 · paraphrase
**Question :** Summarize the operational guidance in 'Plugin LLM Access' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/plugin-llm-access.md` — **Plugin LLM Access**

  > # Plugin LLM Access `ctx.llm` is the supported way for a plugin to make an LLM call. Chat completion, structured extraction, sync, async, with or without images — same surface, same trust gate, same host-owned credentials. Plugins reach for this when they need to do something that involves the model but isn't part of the agent's conversation. A hook that rewrites a tool error into something a non-engineer can read. A gateway adapter that translates an inbound message before queuing it. A slash command that summarises a long paste. A scheduled job that scores yesterday's activity and writes one line to a status board. A pre-filter that decides whether a message is worth waking the agent up […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/plugins.md` — **Plugins**

  > # Plugins Hermes has a plugin system for adding custom tools, hooks, and integrations without modifying core code. If you want to create a custom tool for yourself, your team, or one project, this is usually the right path. The developer guide's [Adding Tools](../../developer-guide/adding-tools.md) page is for built-in Hermes core tools that live in `tools/` and `toolsets.py`. **→ [Build a Hermes Plugin](../../developer-guide/plugins/index.md)** — step-by-step guide with a complete working example. ## Quick overview Drop a directory into `~/.hermes/plugins/` with a `plugin.yaml` and Python code: ``` ~/.hermes/plugins/my-plugin/ ├── plugin.yaml # manifest ├── __init__.py # register() — wires […]

---

## v1-034 · paraphrase
**Question :** Summarize the operational guidance in 'Build a Hermes Plugin' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/plugins/index.md` — **Build a Hermes Plugin**

  > # Build a Hermes Plugin This guide walks through building a complete Hermes plugin from scratch. By the end you'll have a working plugin with multiple tools, lifecycle hooks, shipped data files, and a bundled skill — everything the plugin system supports. :::info Not sure which guide you need? Hermes has several distinct pluggable interfaces — some use Python `register_*` APIs, others are config-driven or drop-in directories. Use this map first: | If you want to add… | Read | |---|---| | Custom tools, hooks, slash commands, skills, or CLI subcommands | **This guide** (the general plugin surface) | | A **native desktop app** extension (panes, pages, status bar, palette, themes) | [Desktop […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/web-search-provider-plugin.md` — **Web Search Provider Plugins**

  > # Building a Web Search Provider Plugin Web-search provider plugins register a backend that services `web_search`, `web_extract`, and (optionally) deep-crawl tool calls. Built-in providers — Firecrawl, SearXNG, Tavily, Perplexity, Exa, Parallel, Keenable, Brave Search (free tier), xAI, and DDGS — all ship as plugins under `plugins/web/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Web search is one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Image Generation Provider Plugins](./image-gen-provider-plugin.md), [Video Generation Provider Plugins](./video-gen-provider-plugin.md), [Memory Provider […]

---

## v1-035 · paraphrase
**Question :** Summarize the operational guidance in 'Programmatic Integration' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/programmatic-integration.md` — **Programmatic Integration**

  > # Programmatic Integration Hermes ships three protocols for driving the agent from external programs — IDE plugins, custom UIs, CI pipelines, embedded sub-agents. Pick the one that matches your transport and consumer. | Protocol | Transport | Best for | Defined by | |----------|-----------|----------|------------| | **ACP** | JSON-RPC over stdio | IDE clients (VS Code, Zed, JetBrains) that already speak the [Agent Client Protocol](https://github.com/zed-industries/agent-client-protocol) | `acp_adapter/` | | **TUI gateway** | JSON-RPC over stdio (or WebSocket) | Custom hosts that want fine-grained control of sessions, slash commands, approvals, and streaming events | `tui_gateway/server.py` […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:integrations/index.md` — **Integrations**

  > # Integrations Hermes Agent connects to external systems for AI inference, tool servers, IDE workflows, programmatic access, and more. These integrations extend what Hermes can do and where it can run. :::tip Start here If you only have time to set up one integration, set up [Nous Portal](./nous-portal.md) — a single OAuth login covers 300+ models plus the four Tool Gateway tools (web search, image generation, TTS, and browser automation). ::: ## AI Providers & Routing Hermes supports multiple AI inference providers out of the box. Use `hermes model` to configure interactively, or set them in `config.yaml`. - **[AI Providers](./providers.md)** — OpenRouter, Anthropic, OpenAI, Google, and […]

---

## v1-036 · paraphrase
**Question :** Summarize the operational guidance in 'Prompt Assembly' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/prompt-assembly.md` — **Prompt Assembly**

  > # Prompt Assembly Hermes deliberately separates: - **cached system prompt state** - **ephemeral API-call-time additions** This is one of the most important design choices in the project because it affects: - token usage - prompt caching effectiveness - session continuity - memory correctness Primary files: - `run_agent.py` - `agent/prompt_builder.py` - `tools/memory_tool.py` ## Cached system prompt layers The cached system prompt is assembled as three ordered tiers (see `agent/system_prompt.py`): 1. **stable** — identity (`SOUL.md` or fallback), tool/model guidance, coding operating brief 2. **context** — caller-supplied `system_message`, project context files (`.hermes.md` / `AGENTS.md` / […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-037 · paraphrase
**Question :** Summarize the operational guidance in 'Provider Runtime Resolution' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/provider-runtime.md` — **Provider Runtime Resolution**

  > # Provider Runtime Resolution Hermes has a shared provider runtime resolver used across: - CLI - gateway - cron jobs - ACP - auxiliary model calls Primary implementation: - `hermes_cli/runtime_provider.py` — credential resolution, custom-endpoint runtime resolution - `hermes_cli/auth.py` — provider registry, `resolve_provider()` - `hermes_cli/model_switch.py` — shared `/model` switch pipeline (CLI + gateway) - `agent/auxiliary_client.py` — auxiliary model routing - `providers/` — ABC + registry entry points (`ProviderProfile`, `register_provider`, `get_provider_profile`, `list_providers`) - `plugins/model-providers/<name>/` — per-provider plugins (bundled) that declare `api_mode`, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-038 · paraphrase
**Question :** Summarize the operational guidance in 'Relay ↔ Connector Contract (v1, EXPERIMENTAL)' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/relay-connector-contract.md` — **Relay ↔ Connector Contract**

  > # Relay ↔ Connector Contract (v1, EXPERIMENTAL) > **Status:** EXPERIMENTAL. This contract MAY CHANGE without a deprecation > cycle until at least two real Class-1 platforms (Discord + Telegram) have > validated it. Evolution during the experimental phase is **additive-only**, > gated by `contract_version`. A breaking change updates both repos in lockstep. This document is the formal interface between the **Hermes gateway** (Python, `gateway/relay/`) and the **connector** (Node/TypeScript, `NousResearch/gateway-gateway`). The connector implementer's first action is to read this file. The gateway runs a generic `RelayAdapter` that dials **out** to the connector, receives a […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/relay.md` — **Hermes Relay**

  > # Hermes Relay (Connector) :::warning Experimental Relay is **experimental**. The wire contract, auth scheme, and configuration may change without a deprecation cycle while the system is being validated. ::: Hermes Relay is not a chat platform itself — it is a **connector system** that lets your gateway front one or more real messaging platforms (Discord, Telegram, Slack, WhatsApp, …) **without holding any platform credentials**. A separate service, the *connector*, owns the platform bot tokens and sockets. Your gateway dials **out** to the connector over a single authenticated WebSocket, receives a capability descriptor at handshake, and then exchanges normalized message events (inbound) […]

---

## v1-039 · paraphrase
**Question :** Summarize the operational guidance in 'NeMo Relay Shared Metrics' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/relay-shared-metrics.md` — **Relay Shared Metrics**

  > # NeMo Relay Shared Metrics Hermes includes NeMo Relay as a normal runtime dependency on platforms for which Relay publishes a native wheel. The shared-metrics integration is built into Hermes and does not require a Hermes observability plugin. Hermes remains importable without Relay on other native targets. Those targets use an explicit reduced-capability no-op host: Hermes execution remains available, while Relay scopes, middleware, plugins, and subscribers are unavailable. The `hermes-agent[nemo-relay]` extra remains as a no-op compatibility alias for existing installation commands. > [!WARNING] > This removes the Hermes `observability/nemo_relay` plugin. Existing users > must remove […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/observer-hooks.md` — **Observer Hooks**

  > # Hermes Observer Hooks Hermes observer hooks are the read-only telemetry contract for plugins that need to reconstruct agent execution without changing runtime behavior. This contract supports trace, metrics, audit, replay, and export integrations such as Langfuse, OpenTelemetry-style collectors, and NeMo Relay. Observer hooks are intentionally backend-neutral. They expose stable lifecycle events, correlation IDs, sanitized payloads, timing, status, and error fields. They do not replace Hermes' planner, model providers, memory, tool registry, approval UX, CLI, gateway behavior, or execution semantics. Behavior-changing request or execution wrappers are outside this observer contract. […]

---

## v1-040 · paraphrase
**Question :** Summarize the operational guidance in 'Building a Secret Source Plugin' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/secret-source-plugin.md` — **Secret Source Plugins**

  > # Building a Secret Source Plugin Secret sources resolve provider credentials from an external secret manager (a vault, a password manager, an OS keystore, a custom script) into environment variables at process startup — after `~/.hermes/.env` loads, before Hermes reads credentials. Bitwarden, 1Password, and a generic command-helper source ship in-tree; **every other backend is a plugin**. This guide covers building one. :::tip The bundled set is deliberately closed, same policy as [memory providers](./memory-provider-plugin.md): PRs adding new vault backends under `agent/secret_sources/` are closed with a pointer to this guide. Publish your backend as a standalone plugin repo and share it […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/secrets/index.md` — **(sans titre)**

  > # Secrets Hermes can pull API keys from external secret managers at process startup instead of storing them in `~/.hermes/.env`. The bootstrap token for the secret manager lives in `.env`; every other provider key (OpenAI, Anthropic, OpenRouter, etc.) can stay in the manager and rotate centrally. Supported: - [Bitwarden Secrets Manager](./bitwarden) — `bws` CLI, lazy-installed, free tier works. - [1Password](./onepassword) — `op://` references via the official `op` CLI; service-account or desktop session auth. - [Command helper](./command) — any CLI vault (`keepassxc-cli`, `secret-tool`, `pass`, custom scripts) via a user-configured helper that prints `KEY=VALUE` lines. ## Multiple sources […]

---

## v1-041 · paraphrase
**Question :** Summarize the operational guidance in 'Session Storage' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/session-storage.md` — **(sans titre)**

  > # Session Storage Hermes Agent uses a SQLite database (`~/.hermes/state.db`) to persist session metadata, full message history, and model configuration across CLI and gateway sessions. This replaces the earlier per-session JSONL file approach. Source files: `hermes_state.py` (facade) plus the `hermes_state_*.py` siblings (schema, fts, search, compression, portability, gateway, ...) ## Hermes home and profile isolation `get_hermes_home()` is the authoritative filesystem resolver for state and configuration. It uses a context-local override first, then the `HERMES_HOME` environment variable, and finally the platform default (`~/.hermes` on macOS and Linux; `%LOCALAPPDATA%/hermes` on Windows). […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v1-042 · paraphrase
**Question :** Summarize the operational guidance in 'State database and FTS recovery' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/state-db-recovery.md` — **State DB Recovery**

  > # State database and FTS recovery `state.db` stores two different data classes: - `sessions` and `messages` are the canonical transcript. - `messages_fts*` tables and their sync triggers are derived search indexes. The derived indexes may be detached temporarily. They must not turn a live message write or search into an unbounded full-transcript rebuild. ## Live behavior when FTS is corrupt If an FTS write or search reports the corruption error class, `SessionDB`: 1. records the durable `fts_stale` marker; 2. removes the FTS sync triggers in the same transaction; 3. retries canonical writes without the derived-index sinks; and 4. serves searches from canonical rows through the `LIKE` […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/session-storage.md` — **(sans titre)**

  > # Session Storage Hermes Agent uses a SQLite database (`~/.hermes/state.db`) to persist session metadata, full message history, and model configuration across CLI and gateway sessions. This replaces the earlier per-session JSONL file approach. Source files: `hermes_state.py` (facade) plus the `hermes_state_*.py` siblings (schema, fts, search, compression, portability, gateway, ...) ## Hermes home and profile isolation `get_hermes_home()` is the authoritative filesystem resolver for state and configuration. It uses a context-local override first, then the `HERMES_HOME` environment variable, and finally the platform default (`~/.hermes` on macOS and Linux; `%LOCALAPPDATA%/hermes` on Windows). […]

---

## v1-043 · paraphrase
**Question :** Summarize the operational guidance in 'Streaming TTS' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/streaming-tts.md` — **Streaming TTS Internals**

  > # Streaming TTS Hermes can stream TTS audio as it arrives from the provider, instead of waiting for the full audio before playing. This is used by voice mode (CLI/TUI live conversation), the dashboard speak-stream WebSocket, and — via the gateway `StreamingTTSConsumer` — any platform adapter that opts into streaming audio. Voice replies start speaking after the first clause instead of after full generation + synthesis. ## Architecture The streaming pipeline has four parts: 1. **Producer** — the LLM emits text deltas as it generates a response 2. **Sentence chunker** — `tools.tts_streaming.SentenceChunker` accumulates deltas, strips `<think>` blocks (even split across deltas), and flushes […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/tts.md` — **Voice & TTS**

  > # Voice & TTS Hermes Agent supports both text-to-speech output and voice message transcription across all messaging platforms. :::tip Nous Subscribers If you have a paid [Nous Portal](https://portal.nousresearch.com) subscription, OpenAI TTS is available through the **[Tool Gateway](tool-gateway.md)** without a separate OpenAI API key. New installs can run `hermes setup --portal` to log in and turn on every gateway tool at once; existing installs can pick **Nous Subscription** for just TTS via `hermes model` or `hermes tools`. ::: ## Text-to-Speech Convert text to speech with eleven providers: | Provider | Quality | Cost | API Key | |----------|---------|------|---------| | **Edge TTS** […]

---

## v1-044 · paraphrase
**Question :** Summarize the operational guidance in 'Public Subagent Lifecycle API' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/subagent-lifecycle-api.md` — **Public Subagent Lifecycle API**

  > # Public Subagent Lifecycle API Plugins can launch and supervise fresh Hermes child sessions without importing `tools.delegate_tool`, gateway internals, TUI state, or `AIAgent` fields. The service resolves its parent from the current agent turn, so it works in CLI, gateway, non-interactive, and kanban-worker sessions. Launching outside an active agent turn fails closed with `No active Hermes parent session`. ```python from agent.subagent_lifecycle import SubagentLaunchRequest def launch_review(ctx): # Call from a plugin tool or hook while an agent turn is active. service = ctx.subagent_lifecycle handle = service.launch(SubagentLaunchRequest( goal="Review this change for regressions.", […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/bundled/software-development/software-development-simplify-code.md` — **Simplify Code — Parallel 4-agent cleanup of recent code changes**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Simplify Code Parallel 4-agent cleanup of recent code changes. ## Skill metadata | | | |---|---| | Source | Bundled (installed by default) | | Path | `skills/software-development\simplify-code` | | Version | `1.1.0` | | Author | Hermes Agent (inspired by Claude Code /simplify) | | License | MIT | | Platforms | linux, macos, windows | | Tags | `code-review`, `cleanup`, `refactor`, `delegation`, `subagent`, `parallel`, `simplify` | | Related skills | [`requesting-code-review`](./software-development-requesting-code-review.md), […]

---

## v1-045 · paraphrase
**Question :** Summarize the operational guidance in 'Terminal Environment Provider Plugins' in different words.

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/terminal-environment-plugin.md` — **(sans titre)**

  > # Terminal Environment Provider Plugins Hermes runs shell commands through a pluggable set of **terminal backends**. The built-in backends (local, Docker, Singularity, Modal, Daytona, Vercel Sandbox, SSH) live in the core repo under `tools/environments/`. Third-party sandbox vendors integrate as **plugins** instead — a standalone plugin repo installed under `~/.hermes/plugins/`, registering a backend the user selects exactly like a built-in one via `terminal.backend` in `config.yaml`. This page mirrors the [Browser Provider Plugins](./browser-provider-plugin.md) guide — same registration flow, same scope semantics. ## What a provider controls A registered backend automatically participates […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/plugins.md` — **Plugins**

  > # Plugins Hermes has a plugin system for adding custom tools, hooks, and integrations without modifying core code. If you want to create a custom tool for yourself, your team, or one project, this is usually the right path. The developer guide's [Adding Tools](../../developer-guide/adding-tools.md) page is for built-in Hermes core tools that live in `tools/` and `toolsets.py`. **→ [Build a Hermes Plugin](../../developer-guide/plugins/index.md)** — step-by-step guide with a complete working example. ## Quick overview Drop a directory into `~/.hermes/plugins/` with a `plugin.yaml` and Python code: ``` ~/.hermes/plugins/my-plugin/ ├── plugin.yaml # manifest ├── __init__.py # register() — wires […]

---

## v1-046 · close_distractor
**Question :** Which documented details belong specifically to 'Tools Runtime', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/tools-runtime.md` — **Tools Runtime**

  > # Tools Runtime Hermes tools are self-registering functions grouped into toolsets and executed through a central registry/dispatch system. Primary files: - `tools/registry.py` - `model_tools.py` - `toolsets.py` - `tools/terminal_tool.py` - `tools/environments/*` ## Tool registration model Each tool module calls `registry.register(...)` at import time. `model_tools.py` is responsible for importing/discovering tool modules and building the schema list used by the model. ### How `registry.register()` works Every tool file in `tools/` calls `registry.register()` at module level to declare itself. The function signature is: ```python registry.register( name="terminal", # Unique tool name (used […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/codex-app-server-runtime.md` — **Codex App-Server Runtime (optional)**

  > # Codex App-Server Runtime Hermes can optionally hand `openai/*` and `openai-codex/*` turns to the [Codex CLI app-server](https://github.com/openai/codex) instead of running its own tool loop. When enabled, terminal commands, file edits, sandboxing, and MCP tool calls all execute inside Codex's runtime — Hermes becomes the shell around it (sessions DB, slash commands, gateway, memory and skill review). This is **opt-in only**. Default Hermes behavior is unchanged unless you flip the flag. Hermes never auto-routes you onto this runtime. :::tip Not using OpenAI Codex? `hermes setup --portal` configures a non-Codex backend with Claude/Gemini/etc. in one step. See [Nous […]

---

## v1-047 · close_distractor
**Question :** Which documented details belong specifically to 'Trajectory Format', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/trajectory-format.md` — **(sans titre)**

  > # Trajectory Format Hermes Agent saves conversation trajectories in ShareGPT-compatible JSONL format for use as training data, debugging artifacts, and reinforcement learning datasets. Source files: `agent/trajectory.py`, `agent/session_persistence.py` (search for `_save_trajectory`), `batch_runner.py` ## File Naming Convention Trajectories are written to files in the current working directory: | File | When | |------|------| | `trajectory_samples.jsonl` | Conversations that completed successfully (`completed=True`) | | `failed_trajectories.jsonl` | Conversations that failed or were interrupted (`completed=False`) | The batch runner (`batch_runner.py`) writes to a custom output file per […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/batch-processing.md` — **Batch Processing**

  > # Batch Processing Batch processing lets you run the Hermes agent across hundreds or thousands of prompts in parallel, generating structured trajectory data. This is primarily used for **training data generation** — producing ShareGPT-format trajectories with tool usage statistics that can be used for fine-tuning or evaluation. ## Overview The batch runner (`batch_runner.py`) processes a JSONL dataset of prompts, running each through a full agent session with tool access. Each prompt gets its own isolated environment. The output is structured trajectory data with full conversation history, tool call statistics, and reasoning coverage metrics. ## Quick Start ```bash # Basic batch run python […]

---

## v1-048 · close_distractor
**Question :** Which documented details belong specifically to 'Building a Video Generation Provider Plugin', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/video-gen-provider-plugin.md` — **Video Generation Provider Plugins**

  > # Building a Video Generation Provider Plugin Video-gen provider plugins register a backend that services every `video_generate` tool call. Built-in providers (xAI, FAL, OpenRouter, DeepInfra) ship as plugins. Add a new one, or override a bundled one, by dropping a directory into `plugins/video_gen/<name>/`. :::tip Video-gen mirrors [Image Generation Provider Plugins](./image-gen-provider-plugin.md) almost line-for-line — if you've built an image-gen backend, you already know the shape. The main differences: a `capabilities()` method advertising modalities/aspect-ratios/durations, and a routing convention (pass `image_url` to use image-to-video, omit it to use text-to-video — the provider […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/browser-provider-plugin.md` — **Browser Provider Plugins**

  > # Building a Browser Provider Plugin Browser provider plugins register a **cloud browser backend** that services cloud-mode `browser_*` tool calls (navigate, click, screenshot, …). Built-in providers — Browserbase, Browser Use, and Firecrawl — all ship as plugins under `plugins/browser/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Browser backends are one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Web Search Provider Plugins](./web-search-provider-plugin.md) (which this ABC deliberately mirrors), [Image Generation](./image-gen-provider-plugin.md), [Video […]

---

## v1-049 · close_distractor
**Question :** Which documented details belong specifically to 'Building a Web Search Provider Plugin', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/web-search-provider-plugin.md` — **Web Search Provider Plugins**

  > # Building a Web Search Provider Plugin Web-search provider plugins register a backend that services `web_search`, `web_extract`, and (optionally) deep-crawl tool calls. Built-in providers — Firecrawl, SearXNG, Tavily, Perplexity, Exa, Parallel, Keenable, Brave Search (free tier), xAI, and DDGS — all ship as plugins under `plugins/web/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Web search is one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Image Generation Provider Plugins](./image-gen-provider-plugin.md), [Video Generation Provider Plugins](./video-gen-provider-plugin.md), [Memory Provider […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/browser-provider-plugin.md` — **Browser Provider Plugins**

  > # Building a Browser Provider Plugin Browser provider plugins register a **cloud browser backend** that services cloud-mode `browser_*` tool calls (navigate, click, screenshot, …). Built-in providers — Browserbase, Browser Use, and Firecrawl — all ship as plugins under `plugins/browser/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Browser backends are one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Web Search Provider Plugins](./web-search-provider-plugin.md) (which this ABC deliberately mirrors), [Image Generation](./image-gen-provider-plugin.md), [Video […]

---

## v1-050 · close_distractor
**Question :** Which documented details belong specifically to 'TUI & Desktop from Worktrees', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/worktree-ui-dev.md` — **TUI & Desktop from Worktrees**

  > # TUI & Desktop from Worktrees The Python core runs fine from any [git worktree](../user-guide/git-worktrees.md) — `cd` in and `hermes` just works. The two TypeScript surfaces do not: `ui-tui/` and `apps/desktop/` each need a populated `node_modules`, and a fresh `npm ci` per worktree is slow and duplicates gigabytes across every branch you have checked out. `htui` and `hgui` are two shell helpers that close that gap. Each launches its surface **from the current worktree** while borrowing `node_modules` from one canonical checkout — so a throwaway branch costs a symlink, not an install. They're developer conveniences, not shipped commands. Drop them in `~/.zshrc`; adapt paths to taste. ## […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/git-worktrees.md` — **Git Worktrees**

  > # Git Worktrees Hermes Agent is often used on large, long‑lived repositories. When you want to: - Run **multiple agents in parallel** on the same project, or - Keep experimental refactors isolated from your main branch, Git **worktrees** are the safest way to give each agent its own checkout without duplicating the entire repository. This page shows how to combine worktrees with Hermes so each session has a clean, isolated working directory. ## Why Use Worktrees with Hermes? Hermes treats the **current working directory** as the project root: - CLI: the directory where you run `hermes` or `hermes chat` - Messaging gateways: the directory set by `terminal.cwd` in `~/.hermes/config.yaml` If […]

---

## v1-051 · close_distractor
**Question :** Which documented details belong specifically to 'Installation', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/installation.md` — **Installation**

  > # Installation Get Hermes Agent up and running in under two minutes! :::tip Platform Support For the full platform support matrix (which OSes, distribution methods, and platform-gated features are supported), see **[Platform Support](./platform-support.md)**. ::: ## Quick Install ### With the Hermes Desktop installer on macOS or Windows (recommended) To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it. :::note The macOS installer is **Apple Silicon only**. macOS on x86 (Intel) processors is [not a supported platform](./platform-support.md#unsupported). ::: ### Without Hermes […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/platform-support.md` — **Platform Support**

  > # Platform Support Hermes Agent maintains support for many platforms and distribution methods, but we can't support every possible install method. --- ## Tier 1 We strive to never break installations and updates for these. Issues & regressions in Tier 1 are our first priority and take precedence over other platforms. | OS / Architecture | Installation methods | Notes | | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | […]

---

## v1-052 · close_distractor
**Question :** Which documented details belong specifically to 'Learning Path', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/learning-path.md` — **'Learning Path'**

  > # Learning Path Hermes Agent can do a lot — CLI assistant, Telegram/Discord bot, task automation, RL training, and more. This page helps you figure out where to start and what to read based on your experience level and what you're trying to accomplish. :::tip Start Here If you haven't installed Hermes Agent yet, begin with the [Installation guide](./installation.md) and then run through the [Quickstart](./quickstart.md). Everything below assumes you have a working installation. ::: :::tip First-time provider setup First-time users almost always want `hermes setup --portal` — one OAuth covers a model plus the four Tool Gateway tools (search/image/TTS/browser). See [Nous […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/optional/mlops/mlops-training-trl-fine-tuning.md` — **Trl Fine Tuning — TRL: SFT, DPO, GRPO, RLOO reward modeling for LLM RLHF**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Trl Fine Tuning TRL: SFT, DPO, GRPO, RLOO reward modeling for LLM RLHF. ## Skill metadata | | | |---|---| | Source | Optional — install with `hermes skills install official/mlops/trl-fine-tuning` | | Path | `optional-skills/mlops\training\trl-fine-tuning` | | Version | `1.0.1` | | Author | Orchestra Research | | License | MIT | | Dependencies | `trl`, `transformers`, `datasets`, `peft`, `accelerate`, `torch` | | Platforms | linux, macos, windows | | Tags | `Post-Training`, `TRL`, `Reinforcement Learning`, `Fine-Tuning`, `SFT`, `DPO`, `GRPO`, […]

---

## v1-053 · close_distractor
**Question :** Which documented details belong specifically to 'Nix & NixOS Setup', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/nix-setup.md` — **Nix & NixOS Setup**

  > # Nix & NixOS Setup :::warning Tier 2 platform Nix and NixOS are [Tier 2 platforms](./platform-support.md#tier-2). The flake and NixOS module documented here are maintained on a best-effort basis only. Commits to `main` may break these packages at any point in time. For a supported setup, use one of the standard [installation](./installation.md) paths - either Docker or an FHS environment. ::: Hermes Agent ships a Nix flake, a NixOS module, and a Home Manager module. | Level | Who it's for | What you get | |-------|-------------|--------------| | **`nix run` / `nix profile install`** | Any Nix user (macOS, Linux) | Pre-built binary with all deps — then use the standard CLI workflow | | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/installation.md` — **Installation**

  > # Installation Get Hermes Agent up and running in under two minutes! :::tip Platform Support For the full platform support matrix (which OSes, distribution methods, and platform-gated features are supported), see **[Platform Support](./platform-support.md)**. ::: ## Quick Install ### With the Hermes Desktop installer on macOS or Windows (recommended) To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it. :::note The macOS installer is **Apple Silicon only**. macOS on x86 (Intel) processors is [not a supported platform](./platform-support.md#unsupported). ::: ### Without Hermes […]

---

## v1-054 · close_distractor
**Question :** Which documented details belong specifically to 'Platform Support', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/platform-support.md` — **Platform Support**

  > # Platform Support Hermes Agent maintains support for many platforms and distribution methods, but we can't support every possible install method. --- ## Tier 1 We strive to never break installations and updates for these. Issues & regressions in Tier 1 are our first priority and take precedence over other platforms. | OS / Architecture | Installation methods | Notes | | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/installation.md` — **Installation**

  > # Installation Get Hermes Agent up and running in under two minutes! :::tip Platform Support For the full platform support matrix (which OSes, distribution methods, and platform-gated features are supported), see **[Platform Support](./platform-support.md)**. ::: ## Quick Install ### With the Hermes Desktop installer on macOS or Windows (recommended) To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it. :::note The macOS installer is **Apple Silicon only**. macOS on x86 (Intel) processors is [not a supported platform](./platform-support.md#unsupported). ::: ### Without Hermes […]

---

## v1-055 · close_distractor
**Question :** Which documented details belong specifically to 'Hermes Agent Quickstart', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/quickstart.md` — **Hermes Agent Quickstart**

  > # Hermes Agent Quickstart This guide gets you from zero to a working Hermes setup that survives real use. Install, choose a provider, verify a working chat, and know exactly what to do when something breaks. ## Prefer to watch? **Onchain AI Garage** put together a Masterclass walkthrough of installation, setup, and basic commands — a good companion to this page if you'd rather follow along on video. For more, see the full [Hermes Agent Tutorials & Use Cases](https://www.youtube.com/playlist?list=PLmpUb_PWAkDxewld5ZYyKifuHxgIbiq2d) playlist. <div style={{position: 'relative', paddingBottom: '56.25%', height: 0, overflow: 'hidden', maxWidth: '100%', marginBottom: '1.5rem'}}> <iframe […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/learning-path.md` — **'Learning Path'**

  > # Learning Path Hermes Agent can do a lot — CLI assistant, Telegram/Discord bot, task automation, RL training, and more. This page helps you figure out where to start and what to read based on your experience level and what you're trying to accomplish. :::tip Start Here If you haven't installed Hermes Agent yet, begin with the [Installation guide](./installation.md) and then run through the [Quickstart](./quickstart.md). Everything below assumes you have a working installation. ::: :::tip First-time provider setup First-time users almost always want `hermes setup --portal` — one OAuth covers a model plus the four Tool Gateway tools (search/image/TTS/browser). See [Nous […]

---

## v1-056 · close_distractor
**Question :** Which documented details belong specifically to 'Hermes on Android with Termux', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/termux.md` — **Android / Termux**

  > # Hermes on Android with Termux :::warning Tier 2 platform Termux (Android) is a [Tier 2 platform](./platform-support.md#tier-2). The installer script and documentation here are maintained on a best-effort basis only. Commits to `main` may break these packages at any point in time. ::: Hermes Agent can run directly on an Android phone through [Termux](https://termux.dev/). It gives you a working local CLI on the phone, plus the core extras that are currently known to install cleanly on Android. ## What is supported in the tested path? The tested Termux bundle installs: - the Hermes CLI - cron support - PTY/background terminal support - Telegram gateway support (manual / best-effort […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/platform-support.md` — **Platform Support**

  > # Platform Support Hermes Agent maintains support for many platforms and distribution methods, but we can't support every possible install method. --- ## Tier 1 We strive to never break installations and updates for these. Issues & regressions in Tier 1 are our first priority and take precedence over other platforms. | OS / Architecture | Installation methods | Notes | | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | […]

---

## v1-057 · close_distractor
**Question :** Which documented details belong specifically to 'Updating & Uninstalling', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/updating.md` — **Updating & Uninstalling**

  > # Updating & Uninstalling ## Updating Update to the latest version with a single command: ```bash hermes update ``` This pulls the latest code from `main`, updates dependencies, and prompts you to configure any new options that were added since your last update. :::tip `hermes update` automatically detects new configuration options and prompts you to add them. If you skipped that prompt, you can manually run `hermes config check` to see missing options, then `hermes config migrate` to interactively add them. ::: ### Passive update notices Pinned or noninteractive installations can disable passive CLI version and banner update checks: ```bash hermes config set updates.check false ``` This […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/plugin-catalog.md` — **Plugin Catalog**

  > # Plugin Catalog The plugin catalog is a curated, human-reviewed directory of Hermes plugins you can install by name with a single command: ```bash hermes plugins install <name> ``` Browse it visually at **[/docs/plugins](/plugins)** — entries are shelved by category (Memory, Desktop, Platforms, Web & Browser, Tools, Voice, Automation, Models), with search, tier filters (Official / Community), capability chips, and copyable install commands for every entry. The catalog complements — it does not replace — the existing [plugin system](plugins.md). Anything you can install from the catalog is a normal plugin under the hood; the catalog just adds discovery and a review layer on top. ## What's […]

---

## v1-058 · close_distractor
**Question :** Which documented details belong specifically to 'Give Your Agent Its Own Email Address', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/agent-email-address.md` — **Give Your Agent Its Own Email Address**

  > # Give Your Agent Its Own Email Address A dedicated email address turns your agent into something you (and services) can email: newsletters it summarises, receipts it files, booking confirmations it tracks, and outbound mail it sends on your behalf. This guide sets that up with the bundled [Himalaya email skill](../user-guide/skills/bundled/email/email-himalaya.md), which drives the `himalaya` CLI over IMAP/SMTP from the agent's terminal tools. :::info Two different email features This is **not** the same as the [Email gateway adapter](../user-guide/messaging/email.md), which lets people chat with Hermes *by* emailing it (send a mail, get a reply in-thread). This guide is about the agent […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/optional/productivity/productivity-shop.md` — **Shop — Shop catalog search, checkout, order tracking, returns**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Shop Shop catalog search, checkout, order tracking, returns. ## Skill metadata | | | |---|---| | Source | Optional — install with `hermes skills install official/productivity/shop` | | Path | `optional-skills/productivity\shop` | | Version | `1.0.1` | | Author | Joe Rinaldi Johnson (joerj123), Hermes Agent | | License | MIT | | Platforms | linux, macos, windows | | Tags | `Shopping`, `E-commerce`, `Shop`, `Products`, `Orders`, `Returns`, `Checkout`, `Reorder` | | Related skills | [`shopify`](./productivity-shopify.md), […]

---

## v1-059 · close_distractor
**Question :** Which documented details belong specifically to 'Automate Anything with Cron', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/automate-with-cron.md` — **Automate Anything with Cron**

  > # Automate Anything with Cron The [daily briefing bot tutorial](./daily-briefing-bot.md) covers the basics. This guide goes further — five real-world automation patterns you can adapt for your own workflows. For the full feature reference, see [Scheduled Tasks (Cron)](../user-guide/features/cron.md). :::info Key Concept Cron jobs run in fresh agent sessions with no memory of your current chat. Prompts must be **completely self-contained** — include everything the agent needs to know. ::: :::tip Don't need the LLM? You have two zero-token options. - **Recurring watchdog** where the script already produces the exact message (memory alerts, disk alerts, heartbeats): use [script-only cron […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/agent-email-address.md` — **Give Your Agent Its Own Email Address**

  > # Give Your Agent Its Own Email Address A dedicated email address turns your agent into something you (and services) can email: newsletters it summarises, receipts it files, booking confirmations it tracks, and outbound mail it sends on your behalf. This guide sets that up with the bundled [Himalaya email skill](../user-guide/skills/bundled/email/email-himalaya.md), which drives the `himalaya` CLI over IMAP/SMTP from the agent's terminal tools. :::info Two different email features This is **not** the same as the [Email gateway adapter](../user-guide/messaging/email.md), which lets people chat with Hermes *by* emailing it (send a mail, get a reply in-thread). This guide is about the agent […]

---

## v1-060 · close_distractor
**Question :** Which documented details belong specifically to 'Automation Blueprints', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/automation-blueprints.md` — **Automation Blueprints**

  > # Automation Blueprints Copy-paste blueprints for common automation patterns. Each blueprint uses Hermes's built-in [cron scheduler](../user-guide/features/cron.md) for time-based triggers and [webhook platform](../user-guide/messaging/webhooks.md) for event-driven triggers. Every blueprint works with **any model** — not locked to a single provider. For parameterized blueprints with forms instead of cron syntax, see the [Automation Blueprints Catalog](../reference/automation-blueprints-catalog.mdx). :::tip Three Trigger Types | Trigger | How | Tool | |---------|-----|------| | **Schedule** | Runs on a cadence (hourly, nightly, weekly) | `cronjob` tool or `/cron` slash command | | **GitHub […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:reference/automation-blueprints-catalog.mdx` — **Automation Blueprints Catalog**

  > import AutomationBlueprintsCatalog from '@site/src/components/AutomationBlueprintsCatalog'; # Automation Blueprints Automation Blueprints are ready-to-run automations. Pick one, fill in a couple of fields, and Hermes schedules it as a cron job — no cron syntax required. Every blueprint works from **every surface**: - **Dashboard / desktop app** — open the Cron page, switch to the **Blueprints** tab, fill the form, and click *Schedule it*. - **CLI, TUI, and messengers** — type `/blueprint <name>` (e.g. `/blueprint morning-brief`) and Hermes asks you for what it needs, one question at a time, then schedules it. The name match is forgiving — a prefix or near-spelling resolves. Power users can […]

---

## v1-061 · close_distractor
**Question :** Which documented details belong specifically to 'AWS Bedrock', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/aws-bedrock.md` — **AWS Bedrock**

  > # AWS Bedrock Hermes Agent supports Amazon Bedrock as a native provider. This gives you full access to the Bedrock ecosystem: IAM authentication, Guardrails, cross-region inference profiles, and all foundation models. Hermes routes each model family through the API that serves it best: | Model family | API route | Why | |---|---|---| | Anthropic Claude | Anthropic SDK (`AnthropicBedrock`) | Prompt caching, thinking budgets, adaptive thinking — features not exposed via Converse | | OpenAI GPT-5.5 / GPT-5.6 (Sol, Terra, Luna) | Bedrock Mantle **OpenAI Responses** endpoint (`bedrock-mantle.<region>.api.aws/openai/v1`) | These models are Mantle-only — their model cards list […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/google-vertex.md` — **Google Vertex AI**

  > # Google Vertex AI Hermes Agent supports **Gemini models on Google Cloud Vertex AI** through Vertex's OpenAI-compatible endpoint. Unlike the [Google AI Studio provider](./google-gemini.md) (which uses a static API key against `generativelanguage.googleapis.com`), Vertex gives you **enterprise-grade rate limits and GCP billing/credits**, and is the right choice when you want Gemini usage to draw on your Google Cloud account rather than an AI Studio key. :::info Vertex authenticates with OAuth2, not an API key Vertex has **no static API key** for the standard endpoint. Every request needs a short-lived **OAuth2 access token** (≈1 hour TTL) minted from either a service-account JSON or […]

---

## v1-062 · close_distractor
**Question :** Which documented details belong specifically to 'Microsoft Foundry', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/azure-foundry.md` — **Microsoft Foundry**

  > # Microsoft Foundry Hermes Agent's `azure-foundry` provider supports Microsoft Foundry (formerly Azure AI Foundry) and Azure OpenAI. A single Foundry resource can host models with two different wire formats: - **OpenAI-style** — `POST /v1/chat/completions` on endpoints like `https://<resource>.openai.azure.com/openai/v1`. Used for GPT-4.x, GPT-5.x, Llama, Mistral, and most open-weight models. - **Anthropic-style** — `POST /v1/messages` on endpoints like `https://<resource>.services.ai.azure.com/anthropic`. Used when Microsoft Foundry serves Claude models via the Anthropic Messages API format. The setup wizard probes your endpoint and auto-detects which transport it uses, which deployments […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:reference/environment-variables.md` — **Environment Variables**

  > # Environment Variables Reference Hermes reads environment variables from the process environment and, for user-managed secrets, from `~/.hermes/.env`. Keep API keys, bot tokens, OAuth secrets, and other credentials in `.env`; prefer `config.yaml` for non-secret behaviour settings when a config key exists. Some variables below are process-only overrides or internal bridge variables and should not be committed to `.env` just because they are documented here. ## LLM Providers | Variable | Description | |----------|-------------| | `OPENROUTER_API_KEY` | OpenRouter API key (recommended for flexibility) | | `OPENROUTER_BASE_URL` | Override the OpenRouter-compatible base URL | | […]

---

## v1-063 · close_distractor
**Question :** Which documented details belong specifically to 'Script-Only Cron Jobs', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/cron-script-only.md` — **Script-Only Cron Jobs (No LLM)**

  > # Script-Only Cron Jobs Sometimes you already know exactly what message you want to send. You don't need an agent to reason about it — you just need a script to run on a timer, and its output (if any) to land in Telegram / Discord / Slack / Signal. Hermes calls this **no-agent mode**. It's the cron system minus the LLM. <!-- ascii-guard-ignore --> ``` ┌──────────────────┐ ┌──────────────────┐ │ scheduler tick │ every │ run script │ │ (every N minutes)│ ──────▶ │ (bash or python) │ └──────────────────┘ └──────────────────┘ │ │ stdout ▼ ┌──────────────────┐ │ delivery router │ │ (telegram/disc…) │ └──────────────────┘ ``` <!-- ascii-guard-ignore-end --> - **No LLM call.** Zero tokens, zero […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/cron-troubleshooting.md` — **Cron Troubleshooting**

  > # Cron Troubleshooting When a cron job isn't behaving as expected, work through these checks in order. Most issues fall into one of four categories: timing, delivery, permissions, or skill loading. --- ## Jobs Not Firing ### Check 1: Verify the job exists and is active ```bash hermes cron list ``` Look for the job and confirm its state is `[active]` (not `[paused]` or `[completed]`). If it shows `[completed]`, the repeat count may be exhausted — edit the job to reset it. ### Check 2: Confirm the schedule is correct A misformatted schedule silently defaults to one-shot or is rejected entirely. Test your expression: | Your expression | Should evaluate to | […]

---

## v1-064 · close_distractor
**Question :** Which documented details belong specifically to 'Cron Troubleshooting', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/cron-troubleshooting.md` — **Cron Troubleshooting**

  > # Cron Troubleshooting When a cron job isn't behaving as expected, work through these checks in order. Most issues fall into one of four categories: timing, delivery, permissions, or skill loading. --- ## Jobs Not Firing ### Check 1: Verify the job exists and is active ```bash hermes cron list ``` Look for the job and confirm its state is `[active]` (not `[paused]` or `[completed]`). If it shows `[completed]`, the repeat count may be exhausted — edit the job to reset it. ### Check 2: Confirm the schedule is correct A misformatted schedule silently defaults to one-shot or is rejected entirely. Test your expression: | Your expression | Should evaluate to | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/run-hermes-with-nous-portal.md` — **Run Hermes Agent with Nous Portal**

  > # Run Hermes Agent with Nous Portal This guide walks you through running Hermes Agent on a [Nous Portal](https://portal.nousresearch.com) subscription end to end — from signing up to verifying that every tool routes correctly. If you just want the overview of what the Portal is and what's in the subscription, see the [Nous Portal integration page](../integrations/nous-portal.md). This page is the task script. ## Prerequisites - Hermes Agent installed ([Quickstart](../getting-started/quickstart.md)) - A web browser on the machine you're setting up (or SSH port forwarding — see [OAuth over SSH](./oauth-over-ssh.md)) - About 5 minutes You do **not** need: an OpenAI key, an Anthropic key, a […]

---

## v1-065 · close_distractor
**Question :** Which documented details belong specifically to 'Tutorial: Build a Daily Briefing Bot', rather than to a nearby Hermes topic?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/daily-briefing-bot.md` — **Tutorial: Daily Briefing Bot**

  > # Tutorial: Build a Daily Briefing Bot In this tutorial, you'll build a personal briefing bot that wakes up every morning, researches topics you care about, summarizes the findings, and delivers a concise briefing straight to your Telegram or Discord. By the end, you'll have a fully automated workflow combining **web search**, **cron scheduling**, **delegation**, and **messaging delivery** — no code required. :::tip This recipe hits web search, summarization, and optional TTS — all bundled in a Portal subscription. The fastest setup is `hermes setup --portal`. See [Nous Portal](../integrations/nous-portal.md). ::: ## What We're Building Here's the flow: 1. **8:00 AM** — The cron scheduler […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/github-pr-review-agent.md` — **Tutorial: GitHub PR Review Agent**

  > # Tutorial: Build a GitHub PR Review Agent **The problem:** Your team opens PRs faster than you can review them. PRs sit for days waiting for eyeballs. Junior devs merge bugs because nobody had time to check. You spend your mornings catching up on diffs instead of building. **The solution:** An AI agent that watches your repos around the clock, reviews every new PR for bugs, security issues, and code quality, and sends you a summary — so you only spend time on PRs that actually need human judgment. **What you'll build:** ``` ┌───────────────────────────────────────────────────────────────────┐ │ │ │ Cron Timer ──▶ Hermes Agent ──▶ GitHub API ──▶ Review │ │ (every 2h) + gh CLI (PR diffs) […]

---

## v1-066 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Delegation & Parallel Work'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/delegation-patterns.md` — **Delegation & Parallel Work**

  > # Delegation & Parallel Work Hermes can spawn isolated child agents to work on tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window. For the full feature reference, see [Subagent Delegation](../user-guide/features/delegation.md). --- ## When to Delegate **Good candidates for delegation:** - Reasoning-heavy subtasks (debugging, code review, research synthesis) - Tasks that would flood your context with intermediate data - Parallel independent workstreams (research A and B simultaneously) - Fresh-context tasks where you want the agent to approach without bias **Use […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

---

## v1-067 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Desktop Native Sign-In (RFC 8252)'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/desktop-native-signin.md` — **Desktop Native Sign-In (RFC 8252)**

  > # Desktop Native Sign-In (RFC 8252) When the Hermes Desktop app connects to a **gated gateway** (a hosted or self-hosted dashboard that sits behind an OAuth provider), it can sign in two ways: 1. **Native sign-in (RFC 8252)** — the app opens your **real system browser**, you approve in the browser you already trust, and the app receives tokens it stores as owner-only files in its user-data directory (optionally encrypted with your OS keychain — Settings → Gateway). **No embedded webview, no browser session cookies.** This is the default whenever the gateway supports it. 2. **Embedded sign-in (legacy fallback)** — the app opens a small in-app browser window and captures the gateway's session […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/manage-hermes-cloud-with-mcp.md` — **Manage Hermes Cloud with MCP**

  > # Manage Hermes Cloud with MCP [Hermes Cloud](https://portal.nousresearch.com/cloud) runs hosted Hermes Agent instances for you. Normally you manage them from the `/agents` page in the [Nous Portal](../integrations/nous-portal.md). This guide connects your **local** Hermes Agent to the Portal's MCP server so you can manage those cloud instances by just asking — "list my cloud agents", "restart the stopped one", "what's it costing me" — without leaving your terminal. It's a standard [MCP](../user-guide/features/mcp.md) server hosted by Nous Research, gated by the same OAuth login you already use for the Portal. Once connected, Hermes gets two tools it can call on your behalf. ## What you can […]

---

## v1-068 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Tutorial: Build a GitHub PR Review Agent'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/github-pr-review-agent.md` — **Tutorial: GitHub PR Review Agent**

  > # Tutorial: Build a GitHub PR Review Agent **The problem:** Your team opens PRs faster than you can review them. PRs sit for days waiting for eyeballs. Junior devs merge bugs because nobody had time to check. You spend your mornings catching up on diffs instead of building. **The solution:** An AI agent that watches your repos around the clock, reviews every new PR for bugs, security issues, and code quality, and sends you a summary — so you only spend time on PRs that actually need human judgment. **What you'll build:** ``` ┌───────────────────────────────────────────────────────────────────┐ │ │ │ Cron Timer ──▶ Hermes Agent ──▶ GitHub API ──▶ Review │ │ (every 2h) + gh CLI (PR diffs) […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/kanban-worker-lanes.md` — **(sans titre)**

  > # Kanban worker lanes A **worker lane** is a class of process that the kanban dispatcher can route tasks to. Each lane has an identity (the assignee string), a spawn mechanism, and a contract for what it must do with the task once spawned. This page is the contract. It exists for two audiences: - **Operators** picking which lanes to wire into a board (which profiles to create, which assignees to use). - **Plugin / integration authors** wanting to add a new lane shape (a CLI worker that wraps Codex / Claude Code / OpenCode, a containerised review worker, a non-Hermes service that pulls tasks via the API). If you're writing the worker code itself — the agent that runs *inside* a lane — the […]

---

## v1-069 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Google Gemini'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/google-gemini.md` — **Google Gemini**

  > # Google Gemini Hermes Agent supports Google Gemini as a native provider using the **Google AI Studio / Gemini API** — not the OpenAI-compatible endpoint. This lets Hermes translate its internal OpenAI-shaped message and tool loop into Gemini's native `generateContent` API while preserving tool calling, streaming, multimodal inputs, and Gemini-specific response metadata. ## Prerequisites - **Google AI Studio API key** — create one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) - **Billing-enabled Google Cloud project** — recommended for agent use. Gemini's free tier is too small for long-running agent sessions because Hermes may make several model calls per user turn. - […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/google-vertex.md` — **Google Vertex AI**

  > # Google Vertex AI Hermes Agent supports **Gemini models on Google Cloud Vertex AI** through Vertex's OpenAI-compatible endpoint. Unlike the [Google AI Studio provider](./google-gemini.md) (which uses a static API key against `generativelanguage.googleapis.com`), Vertex gives you **enterprise-grade rate limits and GCP billing/credits**, and is the right choice when you want Gemini usage to draw on your Google Cloud account rather than an AI Studio key. :::info Vertex authenticates with OAuth2, not an API key Vertex has **no static API key** for the standard endpoint. Every request needs a short-lived **OAuth2 access token** (≈1 hour TTL) minted from either a service-account JSON or […]

---

## v1-070 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Google Vertex AI'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/google-vertex.md` — **Google Vertex AI**

  > # Google Vertex AI Hermes Agent supports **Gemini models on Google Cloud Vertex AI** through Vertex's OpenAI-compatible endpoint. Unlike the [Google AI Studio provider](./google-gemini.md) (which uses a static API key against `generativelanguage.googleapis.com`), Vertex gives you **enterprise-grade rate limits and GCP billing/credits**, and is the right choice when you want Gemini usage to draw on your Google Cloud account rather than an AI Studio key. :::info Vertex authenticates with OAuth2, not an API key Vertex has **no static API key** for the standard endpoint. Every request needs a short-lived **OAuth2 access token** (≈1 hour TTL) minted from either a service-account JSON or […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/google-gemini.md` — **Google Gemini**

  > # Google Gemini Hermes Agent supports Google Gemini as a native provider using the **Google AI Studio / Gemini API** — not the OpenAI-compatible endpoint. This lets Hermes translate its internal OpenAI-shaped message and tool loop into Gemini's native `generateContent` API while preserving tool calling, streaming, multimodal inputs, and Gemini-specific response metadata. ## Prerequisites - **Google AI Studio API key** — create one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) - **Billing-enabled Google Cloud project** — recommended for agent use. Gemini's free tier is too small for long-running agent sessions because Hermes may make several model calls per user turn. - […]

---

## v1-071 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Run Local LLMs on Mac'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/local-llm-on-mac.md` — **Run Local LLMs on Mac**

  > # Run Local LLMs on Mac :::tip Desktop users: there's a one-click path On the Hermes desktop app, **Settings → Providers → Local Models** installs and manages a local llama.cpp server for you — model downloads, memory fitting, and context sizing included. See [Local Models](../user-guide/local-models.md). This guide is for manual setup: MLX, custom builds, or servers you want to run yourself. ::: This guide walks you through running a local LLM server on macOS with an OpenAI-compatible API. You get full privacy, zero API costs, and surprisingly good performance on Apple Silicon. We cover two backends: | Backend | Install | Best at | Format | |---------|---------|---------|--------| | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/local-models.md` — **Local Models**

  > # Local Models Hermes can run open models entirely on your own machine. It downloads and manages the inference engine (llama.cpp), picks the right build of each model for your hardware, and handles memory so you never configure context sizes, GPU layers, or quantization. You pick a model; Hermes does the rest. Nothing leaves your computer: no account, no API key, and no network access after a model is downloaded. ## Getting started 1. Open **Settings → Providers → Local Models** (or choose **Run models locally** during onboarding). 2. Click **Install runtime**. Hermes downloads the official llama.cpp build for your hardware (a few hundred MB), verifies it, and keeps it updated. 3. Pick a […]

---

## v1-072 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Run Hermes Locally with Ollama — Zero API Cost'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/local-ollama-setup.md` — **Run Hermes Locally with Ollama — Zero API Cost**

  > # Run Hermes Locally with Ollama — Zero API Cost :::tip Desktop users: there's a one-click path On the Hermes desktop app, **Settings → Providers → Local Models** installs and manages a local llama.cpp server for you — model downloads, memory fitting, and context sizing included. See [Local Models](../user-guide/local-models.md). This guide is for manual setup: Ollama specifically, CLI-first workflows, or servers you want to run yourself. ::: ## The Problem Cloud LLM APIs charge per token. A heavy coding session can cost $5–20. For personal projects, learning, or privacy-sensitive work, that adds up — and you're sending every conversation to a third party. ## What This Guide Solves You'll […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:integrations/providers.md` — **LLM and Model Providers**

  > # LLM and Model Providers This page covers setting up inference providers for Hermes Agent — from cloud APIs like OpenRouter and Anthropic, to self-hosted endpoints like Ollama and vLLM, to advanced routing and fallback configurations. You need at least one provider configured to use Hermes. ## Inference Providers You need at least one way to connect to an LLM. Use `hermes model` to switch providers and models interactively, or configure directly: | Provider | Setup | |----------|-------| | **Nous Portal** | `hermes model` (OAuth, subscription-based) | | **OpenAI Codex** | `hermes model` → **ChatGPT or Codex Subscription** (ChatGPT OAuth, uses Codex models) | | **GitHub Copilot** | `hermes […]

---

## v1-073 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Manage Hermes Cloud with MCP'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/manage-hermes-cloud-with-mcp.md` — **Manage Hermes Cloud with MCP**

  > # Manage Hermes Cloud with MCP [Hermes Cloud](https://portal.nousresearch.com/cloud) runs hosted Hermes Agent instances for you. Normally you manage them from the `/agents` page in the [Nous Portal](../integrations/nous-portal.md). This guide connects your **local** Hermes Agent to the Portal's MCP server so you can manage those cloud instances by just asking — "list my cloud agents", "restart the stopped one", "what's it costing me" — without leaving your terminal. It's a standard [MCP](../user-guide/features/mcp.md) server hosted by Nous Research, gated by the same OAuth login you already use for the Portal. Once connected, Hermes gets two tools it can call on your behalf. ## What you can […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/multi-connection-desktop.md` — **(sans titre)**

  > # Connecting Desktop to Many Hermes Instances Register every Hermes backend you own — the local runtime, remote gateways on your LAN or VPS, SSH hosts, and Hermes Cloud instances — in one desktop app, and use the agents on all of them side by side. Connections are persistent: each registered gateway dials its own backends and WebSockets on demand, and background agents keep streaming while you look at another gateway. This is the desktop-side complement to [Running Many Gateways at Once](./multi-profile-gateways.md): that page is about hosting several gateways on one machine; this one is about one desktop app talking to several machines. ## Where to find it Everything lives on the unified […]

---

## v1-074 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Register a Microsoft Graph Application'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/microsoft-graph-app-registration.md` — **Register a Microsoft Graph Application**

  > # Register a Microsoft Graph Application The Teams meeting pipeline reads meeting transcripts, recordings, and related artifacts from Microsoft Graph using **app-only** (daemon) authentication — no user sign-in, no interactive consent per meeting. That requires an Azure AD application registration with admin-consented application permissions. This guide walks through: 1. Creating the app registration 2. Creating a client secret 3. Granting the Graph API permissions the pipeline needs 4. Admin-consenting those permissions 5. (Optional) Scoping the app to specific users with an Application Access Policy You need **tenant admin rights** (or an admin to grant consent on your behalf) to finish […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/msgraph-webhook.md` — **Microsoft Graph Webhook Listener**

  > # Microsoft Graph Webhook Listener The `msgraph_webhook` gateway platform is an inbound event listener. It's how Hermes receives **change notifications** from Microsoft Graph — "a Teams meeting ended," "a new message landed in this chat," "this calendar event was updated." Different from the `teams` platform (which is a chat bot users type to) — this one is M365 telling Hermes something happened, not a person. Right now the primary consumer is the Teams meeting summary pipeline: Graph notifies when a meeting produces a transcript, the pipeline fetches it, and Hermes posts a summary back into Teams. Other Graph resources (`/chats/.../messages`, `/users/.../events`) use the same listener — […]

---

## v1-075 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Migrate from OpenClaw'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/migrate-from-openclaw.md` — **Migrate from OpenClaw**

  > # Migrate from OpenClaw `hermes claw migrate` imports your OpenClaw (or legacy Clawdbot/Moldbot) setup into Hermes. This guide covers exactly what gets migrated, the config key mappings, and what to verify after migration. :::note Coming from **Claude Code** or **OpenAI Codex CLI** instead? Use [`hermes import-agent`](../user-guide/import-from-other-agents.md). ::: :::tip If your OpenClaw setup was multi-provider, `hermes setup --portal` collapses it to one OAuth — 300+ models plus the Tool Gateway in a single login. See [Nous Portal](../integrations/nous-portal.md). ::: ## Quick start ```bash # Preview then migrate (always shows a preview first, then asks to confirm) hermes claw migrate # […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/optional/migration/migration-openclaw-migration.md` — **Openclaw Migration — Import an OpenClaw setup (memories, skills) into Hermes**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Openclaw Migration Import an OpenClaw setup (memories, skills) into Hermes. ## Skill metadata | | | |---|---| | Source | Optional — install with `hermes skills install official/migration/openclaw-migration` | | Path | `optional-skills/migration\openclaw-migration` | | Version | `1.0.0` | | Author | Hermes Agent (Nous Research) | | License | MIT | | Platforms | linux, macos, windows | | Tags | `Migration`, `OpenClaw`, `Hermes`, `Memory`, `Persona`, `Import` | | Related skills | […]

---

## v1-076 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'MiniMax OAuth'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/minimax-oauth.md` — **MiniMax OAuth**

  > # MiniMax OAuth Hermes Agent supports **MiniMax** through a browser-based OAuth login flow, using the same credentials as the [MiniMax portal](https://www.minimax.io). No API key or credit card is required — log in once and Hermes automatically refreshes your session. The transport reuses the `anthropic_messages` adapter (MiniMax exposes an Anthropic Messages-compatible endpoint at `/anthropic`), so all existing tool-calling, streaming, and context features work without any adapter changes. ## Overview | Item | Value | |------|-------| | Provider ID | `minimax-oauth` | | Display name | MiniMax (OAuth) | | Auth type | Browser OAuth (PKCE redirect flow) | | Transport | Anthropic […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:integrations/providers.md` — **LLM and Model Providers**

  > # LLM and Model Providers This page covers setting up inference providers for Hermes Agent — from cloud APIs like OpenRouter and Anthropic, to self-hosted endpoints like Ollama and vLLM, to advanced routing and fallback configurations. You need at least one provider configured to use Hermes. ## Inference Providers You need at least one way to connect to an LLM. Use `hermes model` to switch providers and models interactively, or configure directly: | Provider | Setup | |----------|-------| | **Nous Portal** | `hermes model` (OAuth, subscription-based) | | **OpenAI Codex** | `hermes model` → **ChatGPT or Codex Subscription** (ChatGPT OAuth, uses Codex models) | | **GitHub Copilot** | `hermes […]

---

## v1-077 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'OAuth over SSH / Remote Hosts'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/oauth-over-ssh.md` — **OAuth over SSH / Remote Hosts**

  > # OAuth over SSH / Remote Hosts Some Hermes providers — **Spotify** and **remote MCP servers** (Linear, Sentry, Atlassian, Asana, Figma, …) — use a *loopback redirect* OAuth flow. The auth server redirects your browser to `http://127.0.0.1:<port>/callback` so a tiny HTTP listener started by Hermes can grab the authorization code. This works perfectly when Hermes and your browser are on the same machine. It breaks the moment they aren't: your laptop's browser tries to reach `127.0.0.1` on **your laptop**, but the listener is bound to `127.0.0.1` on **the remote server**. The fix is a one-line SSH local-forward. For MCP servers on an interactive terminal, you can often paste the redirect URL […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/xai-grok-oauth.md` — **xAI Grok OAuth (SuperGrok / X Premium+)**

  > # xAI Grok OAuth (SuperGrok / X Premium+) Hermes Agent supports xAI Grok through a browser-based OAuth device-code login flow against [accounts.x.ai](https://accounts.x.ai), using either a **SuperGrok subscription** ([grok.com](https://x.ai/grok)) or an **X Premium+ subscription** (linked X account). No `XAI_API_KEY` is required — log in once and Hermes automatically refreshes your session in the background. When you sign in with an X account that has Premium+, xAI automatically links the subscription status to your xAI session, so the OAuth flow works the same as it does for direct SuperGrok subscribers. The transport reuses the `codex_responses` adapter (xAI exposes a Responses-style […]

---

## v1-078 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Operate the Teams Meeting Pipeline'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/operate-teams-meeting-pipeline.md` — **Operate the Teams Meeting Pipeline**

  > # Operate the Teams Meeting Pipeline Use this guide after you have already enabled the feature from [Teams Meetings](../user-guide/messaging/teams-meetings.md). This page covers: - operator CLI flows - routine subscription maintenance - failure triage - go-live checks - rollout worksheet ## Core Operator Commands ### Validate the config snapshot ```bash hermes teams-pipeline validate ``` Use this first after any config change. ### Inspect token health ```bash hermes teams-pipeline token-health hermes teams-pipeline token-health --force-refresh ``` Use `--force-refresh` when you suspect stale auth state. ### Inspect subscriptions ```bash hermes teams-pipeline subscriptions ``` ### Renew […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/teams-meetings.md` — **Teams Meetings**

  > # Microsoft Teams Meetings Use the Teams meeting pipeline when you want Hermes to ingest Microsoft Graph meeting events, fetch transcripts first, fall back to recordings plus STT when needed, and deliver a structured summary to downstream sinks. Prerequisites: see [Microsoft Teams](./teams.md) for the underlying bot/credential setup. > Run `hermes gateway setup` and pick **Teams Meetings** for a guided walk-through. This page focuses on setup and enablement: - Graph credentials - webhook listener configuration - Teams delivery modes - pipeline config shape For day-2 operations, go-live checks, and the operator worksheet, use the dedicated guide: [Operate the Teams Meeting […]

---

## v1-079 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Pipe Script Output to Messaging Platforms'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/pipe-script-output.md` — **Pipe Script Output to Messaging Platforms**

  > # Pipe Script Output to Messaging Platforms `hermes send` is a small, scriptable CLI that pushes a message to any messaging platform Hermes is already configured for. Think of it as a cross-platform `curl` for notifications — you don't need a running gateway, you don't need an LLM, and you don't need to re-paste bot tokens into each of your scripts. Use it for: - System monitoring (memory, disk, GPU temp, long-running job finished) - CI/CD notifications (deploy done, test failure) - Cron scripts that need to ping you with results - Quick one-shot messages from a terminal - Piping any tool's output anywhere (`make | hermes send --to slack:#builds`) The command reuses the same credentials and […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/simplex.md` — **(sans titre)**

  > # SimpleX Chat [SimpleX Chat](https://simplex.chat/) is a private, decentralised messaging platform where users own their contacts and groups. Unlike other platforms, SimpleX assigns no persistent user IDs — every contact is identified by an opaque internal ID generated at connection time, which makes it one of the most private messengers available. > Run `hermes gateway setup` and pick **SimpleX** for a guided walk-through. ## Prerequisites - The **simplex-chat** CLI installed and running as a daemon - Python package **websockets** (`pip install websockets`) ## Install simplex-chat Download the latest release from the [simplex-chat GitHub […]

---

## v1-080 · chunk_boundary
**Question :** Which Hermes section connects the introduction and later implementation details for 'Using Hermes as a Python Library'?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/python-library.md` — **Using Hermes as a Python Library**

  > # Using Hermes as a Python Library Hermes isn't just a CLI tool. You can import `AIAgent` directly and use it programmatically in your own Python scripts, web applications, or automation pipelines. This guide shows you how. --- ## Installation Clone Hermes and create its supported editable development environment: ```bash git clone https://github.com/NousResearch/hermes-agent.git cd hermes-agent uv sync ``` Run your application with `uv run python your_app.py` from that checkout. Hermes does not publish a supported wheel or source distribution for `requirements.txt` installs. :::tip The same environment variables used by the CLI are required when using Hermes as a library. At minimum, set […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/optional/mlops/mlops-flash-attention.md` — **Flash Attention — Speed up long-sequence transformer training and inference**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Flash Attention Speed up long-sequence transformer training and inference. ## Skill metadata | | | |---|---| | Source | Optional — install with `hermes skills install official/mlops/flash-attention` | | Path | `optional-skills/mlops\flash-attention` | | Version | `1.0.1` | | Author | Orchestra Research | | License | MIT | | Dependencies | `flash-attn`, `torch`, `transformers` | | Platforms | linux, macos | | Tags | `Optimization`, `Flash Attention`, `Attention Optimization`, `Memory Efficiency`, `Speed Optimization`, `Long Context`, `PyTorch`, […]

---

## v1-081 · no_answer
**Question :** What lunar calibration constant does 'Run Hermes Agent with Nous Portal' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:integrations/nous-portal.md` — **Nous Portal**

  > # Nous Portal [Nous Portal](https://portal.nousresearch.com) is Nous Research's unified subscription gateway and **the recommended way to run Hermes Agent**. One OAuth login replaces the juggling act of separate accounts, API keys, and billing relationships across every model lab, search API, image generator, and browser provider you'd otherwise need to wire up by hand. If you only have time to set up one thing, set up this. The fastest path: ```bash hermes setup --portal ``` That single command runs the Portal OAuth, lets you pick a Nous model, sets Nous as your inference provider in `config.yaml`, and turns on the Tool Gateway. You're ready to `hermes chat` immediately after. Don't have a […]

---

## v1-082 · no_answer
**Question :** What lunar calibration constant does 'Run Nemotron 3 Ultra free in Hermes Agent' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:integrations/providers.md` — **LLM and Model Providers**

  > # LLM and Model Providers This page covers setting up inference providers for Hermes Agent — from cloud APIs like OpenRouter and Anthropic, to self-hosted endpoints like Ollama and vLLM, to advanced routing and fallback configurations. You need at least one provider configured to use Hermes. ## Inference Providers You need at least one way to connect to an LLM. Use `hermes model` to switch providers and models interactively, or configure directly: | Provider | Setup | |----------|-------| | **Nous Portal** | `hermes model` (OAuth, subscription-based) | | **OpenAI Codex** | `hermes model` → **ChatGPT or Codex Subscription** (ChatGPT OAuth, uses Codex models) | | **GitHub Copilot** | `hermes […]

---

## v1-083 · no_answer
**Question :** What lunar calibration constant does 'Running Hermes on a Personal or Work Machine' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/bundled/github/github-github-auth.md` — **Github Auth — GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Github Auth GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login. ## Skill metadata | | | |---|---| | Source | Bundled (installed by default) | | Path | `skills/github/github-auth` | | Version | `1.1.0` | | Author | Hermes Agent | | License | MIT | | Platforms | linux, macos, windows | | Tags | `GitHub`, `Authentication`, `Git`, `gh-cli`, `SSH`, `Setup` | | Related skills | [`github-pr-workflow`](./github-github-pr-workflow.md), [`github-code-review`](./github-github-code-review.md), [`github-issues`](./github-github-issues.md), […]

---

## v1-084 · no_answer
**Question :** What lunar calibration constant does 'Set Up a Team Telegram Assistant' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/learning-path.md` — **'Learning Path'**

  > # Learning Path Hermes Agent can do a lot — CLI assistant, Telegram/Discord bot, task automation, RL training, and more. This page helps you figure out where to start and what to read based on your experience level and what you're trying to accomplish. :::tip Start Here If you haven't installed Hermes Agent yet, begin with the [Installation guide](./installation.md) and then run through the [Quickstart](./quickstart.md). Everything below assumes you have a working installation. ::: :::tip First-time provider setup First-time users almost always want `hermes setup --portal` — one OAuth covers a model plus the four Tool Gateway tools (search/image/TTS/browser). See [Nous […]

---

## v1-085 · no_answer
**Question :** What lunar calibration constant does 'Tips & Best Practices' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:index.mdx` — **Hermes Agent Documentation**

  > import Link from "@docusaurus/Link"; # Hermes Agent The self-improving AI agent built by [Nous Research](https://nousresearch.com). The only agent with a built-in learning loop — it creates skills from experience, improves them during use, nudges itself to persist knowledge, and builds a deepening model of who you are across sessions. <div style={{ display: "flex", gap: "1rem", marginBottom: "2rem", flexWrap: "wrap", }} > <Link to="/getting-started/installation" style={{ display: "inline-block", padding: "0.6rem 1.2rem", backgroundColor: "#FFD700", color: "#07070d", borderRadius: "8px", fontWeight: 600, textDecoration: "none", }} > Get Started → </Link> <Link to="/user-guide/bot-mode" […]

---

## v1-086 · no_answer
**Question :** What lunar calibration constant does 'Troubleshooting: "My Agent Feels Dumber"' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/use-soul-with-hermes.md` — **Use SOUL.md with Hermes**

  > # Use SOUL.md with Hermes `SOUL.md` is the **primary identity** for your Hermes instance. It's the first thing in the system prompt — it defines who the agent is, how it speaks, and what it avoids. If you want Hermes to feel like the same assistant every time you talk to it — or if you want to replace the Hermes persona entirely with your own — this is the file to use. ## What SOUL.md is for Use `SOUL.md` for: - tone - personality - communication style - how direct or warm Hermes should be - what Hermes should avoid stylistically - how Hermes should relate to uncertainty, disagreement, and ambiguity In short: - `SOUL.md` is about who Hermes is and how Hermes speaks ## What SOUL.md is not […]

---

## v1-087 · no_answer
**Question :** What lunar calibration constant does 'Use MCP with Hermes' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/mcp.md` — **MCP (Model Context Protocol)**

  > # MCP (Model Context Protocol) MCP lets Hermes Agent connect to external tool servers so the agent can use tools that live outside Hermes itself — GitHub, databases, file systems, browser stacks, internal APIs, and more. If you have ever wanted Hermes to use a tool that already exists somewhere else, MCP is usually the cleanest way to do it. :::tip Coming from Claude Code? The `mcpServers` block in your `~/.claude.json` maps to `mcp_servers` in Hermes' `config.yaml` — and `hermes import-agent claude-code` migrates it (along with skills and instructions) automatically. See [Import from Other Agents](../import-from-other-agents.md). ::: ## What MCP gives you - Access to external tool […]

---

## v1-088 · no_answer
**Question :** What lunar calibration constant does 'Use SOUL.md with Hermes' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/personality.md` — **Personality & SOUL.md**

  > # Personality & SOUL.md Hermes Agent's personality is fully customizable. `SOUL.md` is the **primary identity** — it's the first thing in the system prompt and defines who the agent is. - `SOUL.md` — a durable persona file that lives in `HERMES_HOME` and serves as the agent's identity (slot #1 in the system prompt) - built-in or custom `/personality` presets — session-level system-prompt overlays If you want to change who Hermes is — or replace it with an entirely different agent persona — edit `SOUL.md`. ## How SOUL.md works now Hermes now seeds a default `SOUL.md` automatically in: ```text ~/.hermes/SOUL.md ``` More precisely, it uses the current instance's `HERMES_HOME`, so if you run […]

---

## v1-089 · no_answer
**Question :** What lunar calibration constant does 'Use Voice Mode with Hermes' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/voice-mode.md` — **Voice Mode**

  > # Voice Mode Hermes Agent supports full voice interaction across CLI and messaging platforms. Talk to the agent using your microphone, hear spoken replies, and have live voice conversations in Discord voice channels. If you want a practical setup walkthrough with recommended configurations and real usage patterns, see [Use Voice Mode with Hermes](../../guides/use-voice-mode-with-hermes.md). For hands-free session start — saying "hey hermes" (or any phrase) to open a fresh voice session on the CLI, TUI, or desktop app — see [Wake Word](./wake-word.md). ## Prerequisites Before using voice features, make sure you have: 1. **Hermes Agent installed** — via the install script (see […]

---

## v1-090 · no_answer
**Question :** What lunar calibration constant does 'Automated GitHub PR Comments with Webhooks' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/github-pr-review-agent.md` — **Tutorial: GitHub PR Review Agent**

  > # Tutorial: Build a GitHub PR Review Agent **The problem:** Your team opens PRs faster than you can review them. PRs sit for days waiting for eyeballs. Junior devs merge bugs because nobody had time to check. You spend your mornings catching up on diffs instead of building. **The solution:** An AI agent that watches your repos around the clock, reviews every new PR for bugs, security issues, and code quality, and sends you a summary — so you only spend time on PRs that actually need human judgment. **What you'll build:** ``` ┌───────────────────────────────────────────────────────────────────┐ │ │ │ Cron Timer ──▶ Hermes Agent ──▶ GitHub API ──▶ Review │ │ (every 2h) + gh CLI (PR diffs) […]

---

## v1-091 · no_answer
**Question :** What lunar calibration constant does 'Working with Skills' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/quickstart.md` — **Hermes Agent Quickstart**

  > # Hermes Agent Quickstart This guide gets you from zero to a working Hermes setup that survives real use. Install, choose a provider, verify a working chat, and know exactly what to do when something breaks. ## Prefer to watch? **Onchain AI Garage** put together a Masterclass walkthrough of installation, setup, and basic commands — a good companion to this page if you'd rather follow along on video. For more, see the full [Hermes Agent Tutorials & Use Cases](https://www.youtube.com/playlist?list=PLmpUb_PWAkDxewld5ZYyKifuHxgIbiq2d) playlist. <div style={{position: 'relative', paddingBottom: '56.25%', height: 0, overflow: 'hidden', maxWidth: '100%', marginBottom: '1.5rem'}}> <iframe […]

---

## v1-092 · no_answer
**Question :** What lunar calibration constant does 'xAI Grok OAuth (SuperGrok / X Premium+)' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/x-search.md` — **X (Twitter) Search**

  > # X (Twitter) Search The `x_search` tool lets the agent search X (Twitter) posts, profiles, and threads directly. It's backed by xAI's built-in `x_search` tool on the Responses API at `https://api.x.ai/v1/responses` — Grok itself runs the search server-side and returns synthesized results with citations to the originating posts. **Use this instead of `web_search`** when you specifically want current discussion, reactions, or claims **on X**. For general web pages, keep using `web_search` / `web_extract`. ## `x_search` vs `xurl` Hermes can expose two different X surfaces: | Surface | Use it for | Do not use it for | |---------|------------|-------------------| | `x_search` | Read-only public […]

---

## v1-093 · no_answer
**Question :** What lunar calibration constant does 'Hermes Agent' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/nix-setup.md` — **Nix & NixOS Setup**

  > # Nix & NixOS Setup :::warning Tier 2 platform Nix and NixOS are [Tier 2 platforms](./platform-support.md#tier-2). The flake and NixOS module documented here are maintained on a best-effort basis only. Commits to `main` may break these packages at any point in time. For a supported setup, use one of the standard [installation](./installation.md) paths - either Docker or an FHS environment. ::: Hermes Agent ships a Nix flake, a NixOS module, and a Home Manager module. | Level | Who it's for | What you get | |-------|-------------|--------------| | **`nix run` / `nix profile install`** | Any Nix user (macOS, Linux) | Pre-built binary with all deps — then use the standard CLI workflow | | […]

---

## v1-094 · no_answer
**Question :** What lunar calibration constant does 'Buzz Integration' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/acp.md` — **ACP Host Integration**

  > # ACP Host Integration Hermes Agent can run as an ACP server, letting ACP-compatible hosts talk to Hermes over stdio. Editors can render: - chat messages - tool activity - file diffs - terminal commands - approval prompts - streamed thinking / response chunks Other hosts can use the same protocol to route collaboration events into Hermes. ACP is a good fit when you want Hermes to keep its existing identity, provider setup, memory, skills, and tools while another application owns the conversation transport. ## What Hermes exposes in ACP mode Hermes runs with a curated `hermes-acp` toolset designed for editor workflows. It includes: - file tools: `read_file`, `write_file`, `patch`, […]

---

## v1-095 · no_answer
**Question :** What lunar calibration constant does 'Integrations' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/overview.md` — **Features Overview**

  > # Features Overview Hermes Agent includes a rich set of capabilities that extend far beyond basic chat. From persistent memory and file-aware context to browser automation and voice conversations, these features work together to make Hermes a powerful autonomous assistant. :::tip Don't know where to start? `hermes setup --portal` covers a model provider plus all four Tool Gateway tools (web search, image generation, TTS, browser) in one command. See [Nous Portal](../../integrations/nous-portal.md). ::: ## Core - **[Tools & Toolsets](tools.md)** — Tools are functions that extend the agent's capabilities. They're organized into logical toolsets that can be enabled or disabled per platform, […]

---

## v1-096 · no_answer
**Question :** What lunar calibration constant does 'Nous Portal' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/run-hermes-with-nous-portal.md` — **Run Hermes Agent with Nous Portal**

  > # Run Hermes Agent with Nous Portal This guide walks you through running Hermes Agent on a [Nous Portal](https://portal.nousresearch.com) subscription end to end — from signing up to verifying that every tool routes correctly. If you just want the overview of what the Portal is and what's in the subscription, see the [Nous Portal integration page](../integrations/nous-portal.md). This page is the task script. ## Prerequisites - Hermes Agent installed ([Quickstart](../getting-started/quickstart.md)) - A web browser on the machine you're setting up (or SSH port forwarding — see [OAuth over SSH](./oauth-over-ssh.md)) - About 5 minutes You do **not** need: an OpenAI key, an Anthropic key, a […]

---

## v1-097 · no_answer
**Question :** What lunar calibration constant does 'LLM and Model Providers' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/plugins.md` — **Plugins**

  > # Plugins Hermes has a plugin system for adding custom tools, hooks, and integrations without modifying core code. If you want to create a custom tool for yourself, your team, or one project, this is usually the right path. The developer guide's [Adding Tools](../../developer-guide/adding-tools.md) page is for built-in Hermes core tools that live in `tools/` and `toolsets.py`. **→ [Build a Hermes Plugin](../../developer-guide/plugins/index.md)** — step-by-step guide with a complete working example. ## Quick overview Drop a directory into `~/.hermes/plugins/` with a `plugin.yaml` and Python code: ``` ~/.hermes/plugins/my-plugin/ ├── plugin.yaml # manifest ├── __init__.py # register() — wires […]

---

## v1-098 · no_answer
**Question :** What lunar calibration constant does 'Automation Blueprints' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/automation-blueprints.md` — **Automation Blueprints**

  > # Automation Blueprints Copy-paste blueprints for common automation patterns. Each blueprint uses Hermes's built-in [cron scheduler](../user-guide/features/cron.md) for time-based triggers and [webhook platform](../user-guide/messaging/webhooks.md) for event-driven triggers. Every blueprint works with **any model** — not locked to a single provider. For parameterized blueprints with forms instead of cron syntax, see the [Automation Blueprints Catalog](../reference/automation-blueprints-catalog.mdx). :::tip Three Trigger Types | Trigger | How | Tool | |---------|-----|------| | **Schedule** | Runs on a cadence (hourly, nightly, weekly) | `cronjob` tool or `/cron` slash command | | **GitHub […]

---

## v1-099 · no_answer
**Question :** What lunar calibration constant does 'CLI Commands Reference' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-antigravity-cli.md` — **Antigravity Cli — Operate the Antigravity CLI (agy): plugins, auth, sandbox**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # Antigravity Cli Operate the Antigravity CLI (agy): plugins, auth, sandbox. ## Skill metadata | | | |---|---| | Source | Optional — install with `hermes skills install official/autonomous-ai-agents/antigravity-cli` | | Path | `optional-skills/autonomous-ai-agents\antigravity-cli` | | Version | `0.2.0` | | Author | Tony Simons (asimons81), Hermes Agent | | License | MIT | | Platforms | linux, macos, windows | | Tags | `Coding-Agent`, `Antigravity`, `CLI`, `Auth`, `Plugins`, `Sandbox` | | Related skills | [`grok`](./autonomous-ai-agents-grok.md), […]

---

## v1-100 · no_answer
**Question :** What lunar calibration constant does 'CLI Symbols Glossary' prescribe for an offline telescope controller?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/skills/optional/creative/creative-system-atlas.md` — **System Atlas — Build explorable isometric architecture atlases as HTML**

  > {/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */} # System Atlas Build explorable isometric architecture atlases as HTML. ## Skill metadata | | | |---|---| | Source | Optional — install with `hermes skills install official/creative/system-atlas` | | Path | `optional-skills/creative/system-atlas` | | Version | `1.0.0` | | Author | Harshyt Goel (adapted by Nous Research) | | License | MIT | | Platforms | linux, macos | | Tags | `architecture`, `diagrams`, `isometric`, `documentation` | | Related skills | [`architecture-diagram`](../../bundled/creative/creative-architecture-diagram.md), […]
