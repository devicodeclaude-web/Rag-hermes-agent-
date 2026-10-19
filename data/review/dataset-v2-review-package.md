# Paquet de revue humaine — dataset-v2 (100 questions)
Généré par `scripts/build_review_package.py`. Règles : lire chaque extrait, ne consulter aucun score BGE-M3/reranker, ne pas valider une question au seul motif que le document contient son titre. Reporte tes décisions dans `dataset-v2-full-100.csv`. Un cas `no_answer` est correct si AUCUN document ne répond : vérifie-le sur l'extrait du distracteur.

---

## v2-001 · simple
**Question :** At startup, once I pass a provider:model string, which part of Hermes works out the concrete API credentials and the exact model that end up being used for the run?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/provider-runtime.md` — **Provider Runtime Resolution**

  > # Provider Runtime Resolution Hermes has a shared provider runtime resolver used across: - CLI - gateway - cron jobs - ACP - auxiliary model calls Primary implementation: - `hermes_cli/runtime_provider.py` — credential resolution, custom-endpoint runtime resolution - `hermes_cli/auth.py` — provider registry, `resolve_provider()` - `hermes_cli/model_switch.py` — shared `/model` switch pipeline (CLI + gateway) - `agent/auxiliary_client.py` — auxiliary model routing - `providers/` — ABC + registry entry points (`ProviderProfile`, `register_provider`, `get_provider_profile`, `list_providers`) - `plugins/model-providers/<name>/` — per-provider plugins (bundled) that declare `api_mode`, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/adding-providers.md` — **Adding Providers**

  > # Adding Providers Hermes can already talk to any OpenAI-compatible endpoint through the custom provider path. Do not add a built-in provider unless you want first-class UX for that service: - provider-specific auth or token refresh - a curated model catalog - setup / `hermes model` menu entries - provider aliases for `provider:model` syntax - a non-OpenAI API shape that needs an adapter If the provider is just "another OpenAI-compatible base URL and API key", a named custom provider may be enough. ## The mental model A built-in provider has to line up across a few layers: 1. `hermes_cli/auth.py` decides how credentials are found. 2. `hermes_cli/runtime_provider.py` turns that into runtime […]

---

## v2-002 · simple
**Question :** I want to give the model a brand-new built-in capability baked into the Hermes core — where do I begin and which files do I need to touch?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/adding-tools.md` — **Adding Tools**

  > # Adding Tools Before writing a tool, ask yourself: **should this be a [skill](creating-skills.md) instead?** :::warning Built-in Core Tools Only This page is for adding a **built-in Hermes tool** to the repository itself. If you want a personal, project-local, or otherwise custom tool without modifying Hermes core, use the plugin route instead: - [Plugins](../user-guide/features/plugins.md) - [Build a Hermes Plugin](./plugins/index.md) Default to plugins for most custom tool creation. Only follow this page when you explicitly want to ship a new built-in tool in `tools/` and `toolsets.py`. ::: Make it a **Skill** when the capability can be expressed as instructions + shell commands + […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/tools-runtime.md` — **Tools Runtime**

  > # Tools Runtime Hermes tools are self-registering functions grouped into toolsets and executed through a central registry/dispatch system. Primary files: - `tools/registry.py` - `model_tools.py` - `toolsets.py` - `tools/terminal_tool.py` - `tools/environments/*` ## Tool registration model Each tool module calls `registry.register(...)` at import time. `model_tools.py` is responsible for importing/discovering tool modules and building the schema list used by the model. ### How `registry.register()` works Every tool file in `tools/` calls `registry.register()` at module level to declare itself. The function signature is: ```python registry.register( name="terminal", # Unique tool name (used […]

---

## v2-003 · simple
**Question :** Which component drives the repeating cycle where the model reasons, invokes a tool, then consumes that tool's output on each turn?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/agent-loop.md` — **Agent Loop Internals**

  > # Agent Loop Internals The core orchestration engine is the `AIAgent` class. `run_agent.py` is now a thin facade: the loop itself lives in `agent/conversation_loop.py`, each turn phase in `agent/turn_*.py` (iteration prep, API call, API error, overflow, truncation, recovery), constructor wiring in `agent/agent_init.py`, and everything from prompt assembly to tool dispatch to provider failover in focused `agent/*.py` modules mixed into `AIAgent`. ## Core Responsibilities `AIAgent` is responsible for: - Assembling the effective system prompt and tool schemas via `prompt_builder.py` - Selecting the correct provider/API mode (chat_completions, codex_responses, anthropic_messages) - Making […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v2-004 · simple
**Question :** Over a very long session, how does Hermes progressively shrink the working context without resetting or losing track of earlier work?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/micro-compaction.md` — **Micro-compaction**

  > # Micro-compaction **A way to amortize the cost of compression.** Long conversations eventually outgrow the model's context window, and something has to be thrown away or summarized. Hermes has always done this in one batch: when the transcript crosses a threshold, the session stops, a large chunk of the middle is summarized in a single call, and the conversation resumes. That works, but the whole bill comes due at once — one visible pause, one big summarization request, at whatever moment you happened to cross the line. Micro-compaction pays the same bill in instalments. After each completed turn, Hermes folds the single oldest un-absorbed exchange into a running summary. The work is the […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/context-compression-and-caching.md` — **(sans titre)**

  > # Context Compression and Caching Hermes Agent uses a dual compression system and Anthropic prompt caching to manage context window usage efficiently across long conversations. Source files: `agent/context_engine.py` (ABC), `agent/context_compressor.py` (default engine), `agent/prompt_caching.py`, `gateway/run_turn.py` (session hygiene), `agent/compression_facade.py` (search for `_compress_context`) ## Bedrock context window cache Bedrock context resolution in `agent/model_metadata.py` uses this precedence: - **Explicit overrides win.** Configured context lengths take priority over cache, probes, and the static table. - **Provider-confirmed limits persist.** A successful probe or a limit […]

---

## v2-005 · paraphrase
**Question :** If I'd rather my agent keep its long-term memories in a store I control instead of the built-in one, how do I plug that custom store in?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/memory-provider-plugin.md` — **Memory Provider Plugins**

  > # Building a Memory Provider Plugin Memory provider plugins give Hermes Agent persistent, cross-session knowledge beyond the built-in MEMORY.md and USER.md. This guide covers how to build one. :::tip Memory providers are one of two **provider plugin** types. The other is [Context Engine Plugins](./context-engine-plugin.md), which replace the built-in context compressor. Both follow the same pattern: single-select, config-driven, managed via `hermes plugins`. ::: ## Installation Layouts Hermes discovers memory providers from four sources, in this precedence order: | Source | Location | Notes | |---|---|---| | Bundled | `plugins/memory/<name>/` | Ships with Hermes. Closed to new providers — […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/model-provider-plugin.md` — **Model Provider Plugins**

  > # Building a Model Provider Plugin Model provider plugins declare an inference backend — an OpenAI-compatible endpoint, an Anthropic Messages server, a Codex-style Responses API, or a Bedrock-native surface — that Hermes can route `AIAgent` calls through. Every built-in provider (OpenRouter, Anthropic, GMI, DeepSeek, Nvidia, …) ships as one of these plugins. Third parties can add their own by dropping a directory under `$HERMES_HOME/plugins/model-providers/` with zero changes to the repo. :::tip Model provider plugins are the third kind of **provider plugin**. The others are [Memory Provider Plugins](./memory-provider-plugin.md) (cross-session knowledge) and [Context Engine […]

---

## v2-006 · paraphrase
**Question :** How do I get Hermes to run several agents at the same time, each handling a different slice of the work?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/delegation-patterns.md` — **Delegation & Parallel Work**

  > # Delegation & Parallel Work Hermes can spawn isolated child agents to work on tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window. For the full feature reference, see [Subagent Delegation](../user-guide/features/delegation.md). --- ## When to Delegate **Good candidates for delegation:** - Reasoning-heavy subtasks (debugging, code review, research synthesis) - Tasks that would flood your context with intermediate data - Parallel independent workstreams (research A and B simultaneously) - Fresh-context tasks where you want the agent to approach without bias **Use […]

---

## v2-007 · paraphrase
**Question :** If my primary model fails partway through a request, how does Hermes pick which alternate model to switch to, and does it carry on by itself?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/fallback-providers.md` — **Fallback Providers**

  > # Fallback Providers Hermes Agent has three layers of resilience that keep your sessions running when providers hit issues: 1. **[Credential pools](./credential-pools.md)** — rotate across multiple API keys for the *same* provider (tried first) 2. **Primary model fallback** — automatically switches to a *different* provider:model when your main model fails 3. **Auxiliary task fallback** — independent provider resolution for side tasks like vision and compression Credential pools handle same-provider rotation (e.g., multiple OpenRouter keys). This page covers cross-provider fallback. Both are optional and work independently. ## Primary Model Fallback When your main LLM provider encounters […]
- `hermes-agent:user-guide/features/provider-routing.md` — **Provider Routing**

  > # Provider Routing When using [OpenRouter](https://openrouter.ai) as your LLM provider, Hermes Agent supports **provider routing** — fine-grained control over which underlying AI providers handle your requests and how they're prioritized. OpenRouter routes requests to many providers (e.g., Anthropic, Google, AWS Bedrock, Together AI). Provider routing lets you optimize for cost, speed, quality, or enforce specific provider requirements. :::note [Nous Portal](../../integrations/nous-portal.md) decides routing centrally per model and does not accept caller-supplied provider preferences; Hermes never sends the `provider` object to Portal, so `provider_routing` is simply ignored there. ::: ## […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/provider-runtime.md` — **Provider Runtime Resolution**

  > # Provider Runtime Resolution Hermes has a shared provider runtime resolver used across: - CLI - gateway - cron jobs - ACP - auxiliary model calls Primary implementation: - `hermes_cli/runtime_provider.py` — credential resolution, custom-endpoint runtime resolution - `hermes_cli/auth.py` — provider registry, `resolve_provider()` - `hermes_cli/model_switch.py` — shared `/model` switch pipeline (CLI + gateway) - `agent/auxiliary_client.py` — auxiliary model routing - `providers/` — ABC + registry entry points (`ProviderProfile`, `register_provider`, `get_provider_profile`, `list_providers`) - `plugins/model-providers/<name>/` — per-provider plugins (bundled) that declare `api_mode`, […]

---

## v2-008 · paraphrase
**Question :** In what structure does Hermes keep a record of an entire session so it can be replayed or audited later?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/trajectory-format.md` — **(sans titre)**

  > # Trajectory Format Hermes Agent saves conversation trajectories in ShareGPT-compatible JSONL format for use as training data, debugging artifacts, and reinforcement learning datasets. Source files: `agent/trajectory.py`, `agent/session_persistence.py` (search for `_save_trajectory`), `batch_runner.py` ## File Naming Convention Trajectories are written to files in the current working directory: | File | When | |------|------| | `trajectory_samples.jsonl` | Conversations that completed successfully (`completed=True`) | | `failed_trajectories.jsonl` | Conversations that failed or were interrupted (`completed=False`) | The batch runner (`batch_runner.py`) writes to a custom output file per […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/agent-loop.md` — **Agent Loop Internals**

  > # Agent Loop Internals The core orchestration engine is the `AIAgent` class. `run_agent.py` is now a thin facade: the loop itself lives in `agent/conversation_loop.py`, each turn phase in `agent/turn_*.py` (iteration prep, API call, API error, overflow, truncation, recovery), constructor wiring in `agent/agent_init.py`, and everything from prompt assembly to tool dispatch to provider failover in focused `agent/*.py` modules mixed into `AIAgent`. ## Core Responsibilities `AIAgent` is responsible for: - Assembling the effective system prompt and tool schemas via `prompt_builder.py` - Selecting the correct provider/API mode (chat_completions, codex_responses, anthropic_messages) - Making […]

---

## v2-009 · close_distractor
**Question :** Between declaring a new provider and resolving one at run time, which layer is the one that maps a provider:model string to real credentials on every execution?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/provider-runtime.md` — **Provider Runtime Resolution**

  > # Provider Runtime Resolution Hermes has a shared provider runtime resolver used across: - CLI - gateway - cron jobs - ACP - auxiliary model calls Primary implementation: - `hermes_cli/runtime_provider.py` — credential resolution, custom-endpoint runtime resolution - `hermes_cli/auth.py` — provider registry, `resolve_provider()` - `hermes_cli/model_switch.py` — shared `/model` switch pipeline (CLI + gateway) - `agent/auxiliary_client.py` — auxiliary model routing - `providers/` — ABC + registry entry points (`ProviderProfile`, `register_provider`, `get_provider_profile`, `list_providers`) - `plugins/model-providers/<name>/` — per-provider plugins (bundled) that declare `api_mode`, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/adding-providers.md` — **Adding Providers**

  > # Adding Providers Hermes can already talk to any OpenAI-compatible endpoint through the custom provider path. Do not add a built-in provider unless you want first-class UX for that service: - provider-specific auth or token refresh - a curated model catalog - setup / `hermes model` menu entries - provider aliases for `provider:model` syntax - a non-OpenAI API shape that needs an adapter If the provider is just "another OpenAI-compatible base URL and API key", a named custom provider may be enough. ## The mental model A built-in provider has to line up across a few layers: 1. `hermes_cli/auth.py` decides how credentials are found. 2. `hermes_cli/runtime_provider.py` turns that into runtime […]

---

## v2-010 · close_distractor
**Question :** Where is the everyday use of delegation covered — switching it on and actually using it — rather than the advanced strategies for orchestrating it?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/delegation-patterns.md` — **Delegation & Parallel Work**

  > # Delegation & Parallel Work Hermes can spawn isolated child agents to work on tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window. For the full feature reference, see [Subagent Delegation](../user-guide/features/delegation.md). --- ## When to Delegate **Good candidates for delegation:** - Reasoning-heavy subtasks (debugging, code review, research synthesis) - Tasks that would flood your context with intermediate data - Parallel independent workstreams (research A and B simultaneously) - Fresh-context tasks where you want the agent to approach without bias **Use […]

---

## v2-011 · close_distractor
**Question :** As an end user, how do I turn on and configure an already-existing memory provider without writing any code?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/memory-providers.md` — **Memory Providers**

  > # Memory Providers Hermes Agent ships with 8 external memory provider plugins that give the agent persistent, cross-session knowledge beyond the built-in MEMORY.md and USER.md. Only **one** external provider can be active at a time — the built-in memory is always active alongside it. ## Quick Start ```bash hermes memory setup # interactive picker + configuration hermes memory status # check what's active hermes memory off # disable external provider ``` You can also select the active memory provider via `hermes plugins` → Provider Plugins → Memory Provider. Or set manually in `~/.hermes/config.yaml`: ```yaml memory: provider: openviking # or honcho, mem0, hindsight, holographic, retaindb, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/memory-provider-plugin.md` — **Memory Provider Plugins**

  > # Building a Memory Provider Plugin Memory provider plugins give Hermes Agent persistent, cross-session knowledge beyond the built-in MEMORY.md and USER.md. This guide covers how to build one. :::tip Memory providers are one of two **provider plugin** types. The other is [Context Engine Plugins](./context-engine-plugin.md), which replace the built-in context compressor. Both follow the same pattern: single-select, config-driven, managed via `hermes plugins`. ::: ## Installation Layouts Hermes discovers memory providers from four sources, in this precedence order: | Source | Location | Notes | |---|---|---| | Bundled | `plugins/memory/<name>/` | Ships with Hermes. Closed to new providers — […]

---

## v2-012 · close_distractor
**Question :** How do I define the rules that pick which model handles a request while everything is operating normally?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/provider-routing.md` — **Provider Routing**

  > # Provider Routing When using [OpenRouter](https://openrouter.ai) as your LLM provider, Hermes Agent supports **provider routing** — fine-grained control over which underlying AI providers handle your requests and how they're prioritized. OpenRouter routes requests to many providers (e.g., Anthropic, Google, AWS Bedrock, Together AI). Provider routing lets you optimize for cost, speed, quality, or enforce specific provider requirements. :::note [Nous Portal](../../integrations/nous-portal.md) decides routing centrally per model and does not accept caller-supplied provider preferences; Hermes never sends the `provider` object to Portal, so `provider_routing` is simply ignored there. ::: ## […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/fallback-providers.md` — **Fallback Providers**

  > # Fallback Providers Hermes Agent has three layers of resilience that keep your sessions running when providers hit issues: 1. **[Credential pools](./credential-pools.md)** — rotate across multiple API keys for the *same* provider (tried first) 2. **Primary model fallback** — automatically switches to a *different* provider:model when your main model fails 3. **Auxiliary task fallback** — independent provider resolution for side tasks like vision and compression Credential pools handle same-provider rotation (e.g., multiple OpenRouter keys). This page covers cross-provider fallback. Both are optional and work independently. ## Primary Model Fallback When your main LLM provider encounters […]

---

## v2-013 · chunk_boundary
**Question :** What puts a ceiling on how many subagents run in parallel, and where do I change that limit?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/delegation-patterns.md` — **Delegation & Parallel Work**

  > # Delegation & Parallel Work Hermes can spawn isolated child agents to work on tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window. For the full feature reference, see [Subagent Delegation](../user-guide/features/delegation.md). --- ## When to Delegate **Good candidates for delegation:** - Reasoning-heavy subtasks (debugging, code review, research synthesis) - Tasks that would flood your context with intermediate data - Parallel independent workstreams (research A and B simultaneously) - Fresh-context tasks where you want the agent to approach without bias **Use […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

---

## v2-014 · chunk_boundary
**Question :** What makes an agent's loop come to a stop instead of continuing endlessly?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/agent-loop.md` — **Agent Loop Internals**

  > # Agent Loop Internals The core orchestration engine is the `AIAgent` class. `run_agent.py` is now a thin facade: the loop itself lives in `agent/conversation_loop.py`, each turn phase in `agent/turn_*.py` (iteration prep, API call, API error, overflow, truncation, recovery), constructor wiring in `agent/agent_init.py`, and everything from prompt assembly to tool dispatch to provider failover in focused `agent/*.py` modules mixed into `AIAgent`. ## Core Responsibilities `AIAgent` is responsible for: - Assembling the effective system prompt and tool schemas via `prompt_builder.py` - Selecting the correct provider/API mode (chat_completions, codex_responses, anthropic_messages) - Making […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/middleware.md` — **Middleware**

  > # Hermes Middleware Hermes middleware is the behavior-changing companion to observer hooks. Observer hooks report what happened. Middleware can change what happens by rewriting a request before execution or by wrapping the execution callback itself. This contract is intentionally backend-neutral. A plugin can use it for local policy, request shaping, tracing, adaptive routing, cache control, sandbox selection, or handoff to runtimes such as NeMo Relay without changing Hermes' planner, model provider adapters, tool registry, memory, or CLI UX. With middleware enabled, plugins can: - Rewrite LLM provider request kwargs before Hermes calls the provider. - Rewrite tool arguments before […]

---

## v2-015 · chunk_boundary
**Question :** Which piece assembles the final prompt just before the model is called, and at what point in the flow does it act?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/codebase-ownership.md` — **Codebase Ownership Map**

  > # Codebase Ownership Map Hermes is a large repository, and most contributions touch exactly one subsystem. This page maps each subsystem to its source directories and the documentation entry point you should read before changing it. Use it to find the right starting doc, the right place for a change, and the right test directory (tests mirror source: code in `tools/` is tested in `tests/tools/`, plugins in `tests/plugins/<type>/`, and so on). | Subsystem | Source directories | Docs entry point | |-----------|-------------------|------------------| | Agent core (loop, transports, compression) | `agent/`, `run_agent.py` | [Agent Loop](agent-loop.md), [Context Compression & […]

---

## v2-016 · chunk_boundary
**Question :** Past what context size does Hermes start trimming the history, and can that threshold be tuned?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/context-compression-and-caching.md` — **(sans titre)**

  > # Context Compression and Caching Hermes Agent uses a dual compression system and Anthropic prompt caching to manage context window usage efficiently across long conversations. Source files: `agent/context_engine.py` (ABC), `agent/context_compressor.py` (default engine), `agent/prompt_caching.py`, `gateway/run_turn.py` (session hygiene), `agent/compression_facade.py` (search for `_compress_context`) ## Bedrock context window cache Bedrock context resolution in `agent/model_metadata.py` uses this precedence: - **Explicit overrides win.** Configured context lengths take priority over cache, probes, and the static table. - **Provider-confirmed limits persist.** A successful probe or a limit […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/micro-compaction.md` — **Micro-compaction**

  > # Micro-compaction **A way to amortize the cost of compression.** Long conversations eventually outgrow the model's context window, and something has to be thrown away or summarized. Hermes has always done this in one batch: when the transcript crosses a threshold, the session stops, a large chunk of the middle is summarized in a single call, and the conversation resumes. That works, but the whole bill comes due at once — one visible pause, one big summarization request, at whatever moment you happened to cross the line. Micro-compaction pays the same bill in instalments. After each completed turn, Hermes folds the single oldest un-absorbed exchange into a running summary. The work is the […]

---

## v2-017 · no_answer
**Question :** What is the Telegram adapter's default retry delay before Hermes gives up on sending a message?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/telegram.md` — **Telegram**

  > # Telegram Setup Hermes Agent integrates with Telegram as a full-featured conversational bot. Once connected, you can chat with your agent from any device, send voice memos that get auto-transcribed, receive scheduled task results, and use the agent in group chats. The integration is built on [python-telegram-bot](https://python-telegram-bot.org/) and supports text, voice, images, and file attachments. ## Quick setup (dashboard and desktop app) The **Messaging → Telegram** page in the [dashboard](../features/web-dashboard.md) and the [desktop app](../desktop.md) has a **Create with QR** button. Scan the code (or open the link) in Telegram; Hermes creates the bot for you, detects your […]

---

## v2-018 · no_answer
**Question :** Which environment variable forces Hermes to resolve its providers in offline mode?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/provider-runtime.md` — **Provider Runtime Resolution**

  > # Provider Runtime Resolution Hermes has a shared provider runtime resolver used across: - CLI - gateway - cron jobs - ACP - auxiliary model calls Primary implementation: - `hermes_cli/runtime_provider.py` — credential resolution, custom-endpoint runtime resolution - `hermes_cli/auth.py` — provider registry, `resolve_provider()` - `hermes_cli/model_switch.py` — shared `/model` switch pipeline (CLI + gateway) - `agent/auxiliary_client.py` — auxiliary model routing - `providers/` — ABC + registry entry points (`ProviderProfile`, `register_provider`, `get_provider_profile`, `list_providers`) - `plugins/model-providers/<name>/` — per-provider plugins (bundled) that declare `api_mode`, […]

---

## v2-019 · no_answer
**Question :** What is the maximum number of skills Hermes will load into context at the same time?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/skills.md` — **Skills System**

  > # Skills System Skills are on-demand knowledge documents the agent can load when needed. They follow a **progressive disclosure** pattern to minimize token usage and are compatible with the [agentskills.io](https://agentskills.io/specification) open standard. All skills live in **`~/.hermes/skills/`** — the primary directory and source of truth. On fresh install, bundled skills are copied from the repo. Hub-installed and agent-created skills also go here. The agent can modify or delete any skill. You can also point Hermes at **external skill directories** — additional folders scanned alongside the local one. See [External Skill Directories](#external-skill-directories) below. See also: - […]

---

## v2-020 · no_answer
**Question :** What oven temperature does Hermes recommend for slow-roasting a leg of lamb?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**

---

## v2-021 · simple
**Question :** How do I turn a recurring procedure into a reusable module made of instructions plus shell commands, instead of writing a hard-coded tool for it?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/creating-skills.md` — **Creating Skills**

  > # Creating Skills Skills are the preferred way to add new capabilities to Hermes Agent. They're easier to create than tools, require no code changes to the agent, and can be shared with the community. ## Should it be a Skill or a Tool? Make it a **Skill** when: - The capability can be expressed as instructions + shell commands + existing tools - It wraps an external CLI or API that the agent can call via `terminal` or `web_extract` - It doesn't need custom Python integration or API key management baked into the agent - Examples: arXiv search, git workflows, Docker management, PDF processing, email via CLI tools Make it a **Tool** when: - It requires end-to-end integration with API keys, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/adding-tools.md` — **Adding Tools**

  > # Adding Tools Before writing a tool, ask yourself: **should this be a [skill](creating-skills.md) instead?** :::warning Built-in Core Tools Only This page is for adding a **built-in Hermes tool** to the repository itself. If you want a personal, project-local, or otherwise custom tool without modifying Hermes core, use the plugin route instead: - [Plugins](../user-guide/features/plugins.md) - [Build a Hermes Plugin](./plugins/index.md) Default to plugins for most custom tool creation. Only follow this page when you explicitly want to ship a new built-in tool in `tools/` and `toolsets.py`. ::: Make it a **Skill** when the capability can be expressed as instructions + shell commands + […]

---

## v2-022 · simple
**Question :** What does the standard mechanism for external tools give the agent, and how do I switch it on as a user?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/tool-gateway.md` — **Nous Tool Gateway**

  > # Nous Tool Gateway **One subscription. Every tool built in.** The Tool Gateway is included with every paid [Nous Portal](https://portal.nousresearch.com) subscription. It routes Hermes' tool calls — web search, image generation, text-to-speech, and cloud browser automation — through infrastructure Nous already runs, so you don't have to sign up with Firecrawl, FAL, OpenAI, Browser Use, or anyone else just to make your agent useful. <div style={{display: 'flex', gap: '1rem', flexWrap: 'wrap', margin: '1.5rem 0'}}> <a href="https://portal.nousresearch.com/manage-subscription" style={{background: 'var(--ifm-color-primary)', color: 'white', padding: '0.75rem 1.5rem', borderRadius: '6px', […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/tools.md` — **Tools & Toolsets**

  > # Tools & Toolsets Tools are functions that extend the agent's capabilities. They're organized into logical **toolsets** that can be enabled or disabled per platform. ## Available Tools Hermes ships with a broad built-in tool registry covering web search, browser automation, terminal execution, file editing, memory, delegation, scheduled tasks, Home Assistant, and more. :::note **Honcho cross-session memory** is available as a memory provider plugin (`plugins/memory/honcho/`), not as a built-in toolset. See [Plugins](./plugins.md) for installation. ::: High-level categories: | Category | Examples | Description | |----------|----------|-------------| | **Web** | `web_search`, `web_extract` | […]

---

## v2-023 · simple
**Question :** Which component bridges Hermes and the messaging platforms, and what is it responsible for?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/adding-platform-adapters.md` — **(sans titre)**

  > # Adding a Platform Adapter This guide covers adding a new messaging platform to the Hermes gateway. A platform adapter connects Hermes to an external messaging service (Telegram, Discord, WeCom, etc.) so users can interact with the agent through that service. :::tip There are two ways to add a platform: - **Plugin** (recommended for community/third-party): Drop a plugin directory into `~/.hermes/plugins/` — zero core code changes needed. See [Plugin Path](#plugin-path-recommended) below. - **Built-in**: Modify 20+ files across code, config, and docs. Use the [Built-in Checklist](#step-by-step-checklist-built-in-path) below. ::: ## Architecture Overview ``` User ↔ Messaging Platform ↔ […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

---

## v2-024 · simple
**Question :** Deep inside Hermes, how are recurring jobs scheduled and then fired at their due time?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/cron-internals.md` — **Cron Internals**

  > # Cron Internals The cron subsystem provides scheduled task execution — from simple one-shot delays to recurring cron-expression jobs with skill injection and cross-platform delivery. ## Key Files | File | Purpose | |------|---------| | `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` | | `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking | | `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler | | `gateway/run.py` | Gateway integration — cron ticking in the long-running loop | | `hermes_cli/cron.py` | CLI `hermes cron` subcommands | ## Scheduling Model Four schedule formats are supported: | Format | Example | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/cron.md` — **Scheduled Tasks (Cron)**

  > # Scheduled Tasks (Cron) Schedule tasks to run automatically with natural language or cron expressions. Hermes exposes cron management through a single `cronjob` tool with action-style operations instead of separate schedule/list/remove tools. ## What cron can do now Cron jobs can: - schedule one-shot or recurring tasks - pause, resume, edit, trigger, and remove jobs - attach zero, one, or multiple skills to a job - deliver results back to the origin chat, local files, or configured platform targets - run in fresh agent sessions with the normal static tool list - run in **no-agent mode** — a script on a schedule, its stdout delivered verbatim, zero LLM involvement (see the [no-agent […]

---

## v2-025 · simple
**Question :** Through what steps is the final prompt assembled right before it's sent to the model?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/prompt-assembly.md` — **Prompt Assembly**

  > # Prompt Assembly Hermes deliberately separates: - **cached system prompt state** - **ephemeral API-call-time additions** This is one of the most important design choices in the project because it affects: - token usage - prompt caching effectiveness - session continuity - memory correctness Primary files: - `run_agent.py` - `agent/prompt_builder.py` - `tools/memory_tool.py` ## Cached system prompt layers The cached system prompt is assembled as three ordered tiers (see `agent/system_prompt.py`): 1. **stable** — identity (`SOUL.md` or fallback), tool/model guidance, coding operating brief 2. **context** — caller-supplied `system_message`, project context files (`.hermes.md` / `AGENTS.md` / […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/architecture.md` — **Architecture**

  > # Architecture This page is the top-level map of Hermes Agent internals. Use it to orient yourself in the codebase, then dive into subsystem-specific docs for implementation details. ## System Overview ```text ┌─────────────────────────────────────────────────────────────────────┐ │ Entry Points │ │ │ │ CLI (cli.py) Gateway (gateway/run.py) ACP (acp_adapter/) │ │ Batch Runner API Server Python Library │ └──────────┬──────────────┬───────────────────────┬───────────────────┘ │ │ │ ▼ ▼ ▼ ┌─────────────────────────────────────────────────────────────────────┐ │ AIAgent (run_agent.py) │ │ │ │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │ │ │ Prompt │ │ Provider │ │ Tool │ │ │ │ Builder │ […]

---

## v2-026 · simple
**Question :** How do I insert logic that runs automatically before and after each request is handled?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/middleware.md` — **Middleware**

  > # Hermes Middleware Hermes middleware is the behavior-changing companion to observer hooks. Observer hooks report what happened. Middleware can change what happens by rewriting a request before execution or by wrapping the execution callback itself. This contract is intentionally backend-neutral. A plugin can use it for local policy, request shaping, tracing, adaptive routing, cache control, sandbox selection, or handoff to runtimes such as NeMo Relay without changing Hermes' planner, model provider adapters, tool registry, memory, or CLI UX. With middleware enabled, plugins can: - Rewrite LLM provider request kwargs before Hermes calls the provider. - Rewrite tool arguments before […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/observer-hooks.md` — **Observer Hooks**

  > # Hermes Observer Hooks Hermes observer hooks are the read-only telemetry contract for plugins that need to reconstruct agent execution without changing runtime behavior. This contract supports trace, metrics, audit, replay, and export integrations such as Langfuse, OpenTelemetry-style collectors, and NeMo Relay. Observer hooks are intentionally backend-neutral. They expose stable lifecycle events, correlation IDs, sanitized payloads, timing, status, and error fields. They do not replace Hermes' planner, model providers, memory, tool registry, approval UX, CLI, gateway behavior, or execution semantics. Behavior-changing request or execution wrappers are outside this observer contract. […]

---

## v2-027 · simple
**Question :** Where is a session's state written, and in what form is it kept between runs?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/session-storage.md` — **(sans titre)**

  > # Session Storage Hermes Agent uses a SQLite database (`~/.hermes/state.db`) to persist session metadata, full message history, and model configuration across CLI and gateway sessions. This replaces the earlier per-session JSONL file approach. Source files: `hermes_state.py` (facade) plus the `hermes_state_*.py` siblings (schema, fts, search, compression, portability, gateway, ...) ## Hermes home and profile isolation `get_hermes_home()` is the authoritative filesystem resolver for state and configuration. It uses a context-local override first, then the `HERMES_HOME` environment variable, and finally the platform default (`~/.hermes` on macOS and Linux; `%LOCALAPPDATA%/hermes` on Windows). […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/trajectory-format.md` — **(sans titre)**

  > # Trajectory Format Hermes Agent saves conversation trajectories in ShareGPT-compatible JSONL format for use as training data, debugging artifacts, and reinforcement learning datasets. Source files: `agent/trajectory.py`, `agent/session_persistence.py` (search for `_save_trajectory`), `batch_runner.py` ## File Naming Convention Trajectories are written to files in the current working directory: | File | When | |------|------| | `trajectory_samples.jsonl` | Conversations that completed successfully (`completed=True`) | | `failed_trajectories.jsonl` | Conversations that failed or were interrupted (`completed=False`) | The batch runner (`batch_runner.py`) writes to a custom output file per […]

---

## v2-028 · simple
**Question :** As a user, how do I get my agent to drive a web browser and interact with pages?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/browser.md` — **Browser Automation**

  > # Browser Automation Hermes Agent includes a full browser automation toolset with multiple backend options: - **Browser Use cloud mode** via [Browser Use](https://browser-use.com) for managed Chromium with stealth, residential proxies, CAPTCHA solving, and reusable browser profiles - **Browserbase cloud mode** via [Browserbase](https://browserbase.com) as an alternative cloud browser provider with anti-bot tooling - **Browser Use mode** via the [Browser Use CLI 3.0](https://github.com/browser-use/browser-use), the default browser driver for local Chrome and Browser Use cloud browsers - **Firecrawl cloud mode** via [Firecrawl](https://firecrawl.dev) for cloud browsers with built-in scraping […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/browser-supervisor.md` — **Browser CDP Supervisor**

  > # Browser CDP Supervisor The CDP supervisor closes two long-standing gaps in Hermes' browser tooling: 1. **Native JS dialogs** (`alert`/`confirm`/`prompt`/`beforeunload`) block the page's JS thread. Without supervision, the agent has no way to know a dialog is open — subsequent tool calls hang or throw opaque errors. 2. **Cross-origin iframes (OOPIFs)** are invisible to top-level `Runtime.evaluate`. The agent can see iframe nodes in the DOM snapshot but can't click, type, or eval inside them without a CDP session attached to the child target. The supervisor solves both by holding a persistent WebSocket to the backend's CDP endpoint per browser task, surfacing pending dialogs and frame […]

---

## v2-029 · simple
**Question :** How can I submit a whole series of requests to be processed as a batch rather than one at a time?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/batch-processing.md` — **Batch Processing**

  > # Batch Processing Batch processing lets you run the Hermes agent across hundreds or thousands of prompts in parallel, generating structured trajectory data. This is primarily used for **training data generation** — producing ShareGPT-format trajectories with tool usage statistics that can be used for fine-tuning or evaluation. ## Overview The batch runner (`batch_runner.py`) processes a JSONL dataset of prompts, running each through a full agent session with tool access. Each prompt gets its own isolated environment. The output is structured trajectory data with full conversation history, tool call statistics, and reasoning coverage metrics. ## Quick Start ```bash # Basic batch run python […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

---

## v2-030 · simple
**Question :** How do I give my agent a steady character and tone that carries across different conversations?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/personality.md` — **Personality & SOUL.md**

  > # Personality & SOUL.md Hermes Agent's personality is fully customizable. `SOUL.md` is the **primary identity** — it's the first thing in the system prompt and defines who the agent is. - `SOUL.md` — a durable persona file that lives in `HERMES_HOME` and serves as the agent's identity (slot #1 in the system prompt) - built-in or custom `/personality` presets — session-level system-prompt overlays If you want to change who Hermes is — or replace it with an entirely different agent persona — edit `SOUL.md`. ## How SOUL.md works now Hermes now seeds a default `SOUL.md` automatically in: ```text ~/.hermes/SOUL.md ``` More precisely, it uses the current instance's `HERMES_HOME`, so if you run […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/sessions.md` — **Sessions**

  > import useBaseUrl from '@docusaurus/useBaseUrl'; # Sessions Hermes Agent automatically saves every conversation as a session. Sessions enable conversation resume, cross-session search, and full conversation history management. ## How Sessions Work Every conversation — whether from the CLI, Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Teams, or any other messaging platform — is stored as a session with full message history. Sessions are tracked in: 1. **SQLite database** (`~/.hermes/state.db`) — structured session metadata with FTS5 full-text search, plus full message history The SQLite database stores: - Session ID, source platform, user ID - **Session title** (unique, human-readable […]

---

## v2-031 · simple
**Question :** What do I set up so the agent's replies are read out loud?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/tts.md` — **Voice & TTS**

  > # Voice & TTS Hermes Agent supports both text-to-speech output and voice message transcription across all messaging platforms. :::tip Nous Subscribers If you have a paid [Nous Portal](https://portal.nousresearch.com) subscription, OpenAI TTS is available through the **[Tool Gateway](tool-gateway.md)** without a separate OpenAI API key. New installs can run `hermes setup --portal` to log in and turn on every gateway tool at once; existing installs can pick **Nous Subscription** for just TTS via `hermes model` or `hermes tools`. ::: ## Text-to-Speech Convert text to speech with eleven providers: | Provider | Quality | Cost | API Key | |----------|---------|------|---------| | **Edge TTS** […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/use-voice-mode-with-hermes.md` — **Use Voice Mode with Hermes**

  > # Use Voice Mode with Hermes This guide is the practical companion to the [Voice Mode feature reference](../user-guide/features/voice-mode.md). If the feature page explains what voice mode can do, this guide shows how to actually use it well. :::tip [Nous Portal](../integrations/nous-portal.md) bundles both the LLM and TTS through one OAuth — voice mode works end-to-end with no extra credentials. ::: ## What voice mode is good for Voice mode is especially useful when: - you want a hands-free CLI workflow - you want spoken responses in Telegram or Discord - you want Hermes sitting in a Discord voice channel for live conversation - you want quick idea capture, debugging, or back-and-forth […]

---

## v2-032 · simple
**Question :** For everyday use, how do I work on several branches at once through separate working copies?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/git-worktrees.md` — **Git Worktrees**

  > # Git Worktrees Hermes Agent is often used on large, long‑lived repositories. When you want to: - Run **multiple agents in parallel** on the same project, or - Keep experimental refactors isolated from your main branch, Git **worktrees** are the safest way to give each agent its own checkout without duplicating the entire repository. This page shows how to combine worktrees with Hermes so each session has a clean, isolated working directory. ## Why Use Worktrees with Hermes? Hermes treats the **current working directory** as the project root: - CLI: the directory where you run `hermes` or `hermes chat` - Messaging gateways: the directory set by `terminal.cwd` in `~/.hermes/config.yaml` If […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/worktree-ui-dev.md` — **TUI & Desktop from Worktrees**

  > # TUI & Desktop from Worktrees The Python core runs fine from any [git worktree](../user-guide/git-worktrees.md) — `cd` in and `hermes` just works. The two TypeScript surfaces do not: `ui-tui/` and `apps/desktop/` each need a populated `node_modules`, and a fresh `npm ci` per worktree is slow and duplicates gigabytes across every branch you have checked out. `htui` and `hgui` are two shell helpers that close that gap. Each launches its surface **from the current worktree** while borrowing `node_modules` from one canonical checkout — so a throwaway branch costs a symlink, not an install. They're developer conveniences, not shipped commands. Drop them in `~/.zshrc`; adapt paths to taste. ## […]

---

## v2-033 · simple
**Question :** On the implementation side, how is the agent's outbound network traffic filtered and routed?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/egress-internals.md` — **Egress proxy internals**

  > # Egress proxy internals This page covers the architecture of the egress credential-injection firewall (`hermes egress` / iron-proxy) from a contributor / plugin author's perspective. End-user setup + usage docs live at [Egress proxy](../user-guide/egress/iron-proxy.md). The threat model and high-level design are summarised on the user page; this page is about *how* it's wired, where the security-relevant code lives, and what invariants you have to preserve if you touch it. ## Module layout ```text agent/proxy_sources/iron_proxy.py Core: binary install, CA gen, config build, subprocess lifecycle, mappings I/O, PID/nonce defense. Pure-function surface where possible. hermes_cli/proxy_cli.py […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/egress/index.md` — **Egress proxy**

  > # Egress proxy Optional outbound credential-injection firewall for remote terminal sandboxes. The sandbox only ever holds opaque proxy tokens; real API keys never leave the host. - [iron-proxy](./iron-proxy) — single-binary TLS-intercepting proxy from [ironsh/iron-proxy](https://github.com/ironsh/iron-proxy), lazy-installed and managed by `hermes egress`.

---

## v2-034 · simple
**Question :** How do I react to agent lifecycle events by subscribing to them, without changing the core code?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/observer-hooks.md` — **Observer Hooks**

  > # Hermes Observer Hooks Hermes observer hooks are the read-only telemetry contract for plugins that need to reconstruct agent execution without changing runtime behavior. This contract supports trace, metrics, audit, replay, and export integrations such as Langfuse, OpenTelemetry-style collectors, and NeMo Relay. Observer hooks are intentionally backend-neutral. They expose stable lifecycle events, correlation IDs, sanitized payloads, timing, status, and error fields. They do not replace Hermes' planner, model providers, memory, tool registry, approval UX, CLI, gateway behavior, or execution semantics. Behavior-changing request or execution wrappers are outside this observer contract. […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/hooks.md` — **Event Hooks**

  > # Event Hooks Hermes has four hook systems that run custom code at key lifecycle points: | System | Registered via | Runs in | Use case | |--------|---------------|---------|----------| | **[Gateway hooks](#gateway-event-hooks)** | `HOOK.yaml` + `handler.py` in `~/.hermes/hooks/` | Gateway only | Logging, alerts, webhooks | | **[Plugin hooks](#plugin-hooks)** | `ctx.register_hook()` in a [plugin](./plugins.md) | CLI + Gateway | Tool interception, metrics, guardrails | | **[Shell hooks](#shell-hooks)** | `hooks:` block in profile `config.yaml` pointing at shell scripts | CLI + Gateway + Desktop/TUI/dashboard chat | Drop-in scripts for blocking, auto-formatting, context injection | | […]

---

## v2-035 · simple
**Question :** What do I do to recover the state database after it's corrupted or crashes?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/state-db-recovery.md` — **State DB Recovery**

  > # State database and FTS recovery `state.db` stores two different data classes: - `sessions` and `messages` are the canonical transcript. - `messages_fts*` tables and their sync triggers are derived search indexes. The derived indexes may be detached temporarily. They must not turn a live message write or search into an unbounded full-transcript rebuild. ## Live behavior when FTS is corrupt If an FTS write or search reports the corruption error class, `SessionDB`: 1. records the durable `fts_stale` marker; 2. removes the FTS sync triggers in the same transaction; 3. retries canonical writes without the derived-index sinks; and 4. serves searches from canonical rows through the `LIKE` […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/checkpoints-and-rollback.md` — **Checkpoints and /rollback**

  > # Checkpoints and `/rollback` Hermes Agent can automatically snapshot your project before **destructive operations** and restore it with a single command. Checkpoints are **opt-in** as of v2 — most users never use `/rollback`, and the shadow-store storage is non-trivial over time, so the default is off. Enable checkpoints per-session with `--checkpoints`: ```bash hermes chat --checkpoints ``` Or enable globally in `~/.hermes/config.yaml`: ```yaml checkpoints: enabled: true ``` This safety net is powered by an internal **Checkpoint Manager** that keeps a single shared shadow git repository under `~/.hermes/checkpoints/store/` — your real project `.git` is never touched. Every project the […]

---

## v2-036 · simple
**Question :** Where is the complete reference listing the configuration variables Hermes reads from the environment?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:reference/environment-variables.md` — **Environment Variables**

  > # Environment Variables Reference Hermes reads environment variables from the process environment and, for user-managed secrets, from `~/.hermes/.env`. Keep API keys, bot tokens, OAuth secrets, and other credentials in `.env`; prefer `config.yaml` for non-secret behaviour settings when a config key exists. Some variables below are process-only overrides or internal bridge variables and should not be committed to `.env` just because they are documented here. ## LLM Providers | Variable | Description | |----------|-------------| | `OPENROUTER_API_KEY` | OpenRouter API key (recommended for flexibility) | | `OPENROUTER_BASE_URL` | Override the OpenRouter-compatible base URL | | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/configuration.md` — **Hermes Agent Configuration**

  > # Hermes Agent Configuration All settings are stored in the `~/.hermes/` directory for easy access. :::tip Easiest path to a working `config.yaml` Run `hermes setup --portal` — one OAuth gets you a model provider and all four Tool Gateway tools without hand-editing YAML. Portal subscribers also get 10% off token-billed providers. See [Nous Portal](../integrations/nous-portal.md). ::: ## Directory Structure ```text ~/.hermes/ ├── config.yaml # Settings (model, terminal, TTS, compression, etc.) ├── .env # API keys and secrets ├── auth.json # OAuth provider credentials (Nous Portal, etc.) ├── SOUL.md # Primary agent identity (slot #1 in system prompt) ├── memories/ # Persistent memory […]

---

## v2-037 · simple
**Question :** As a user, how do I install and switch on a ready-made extension?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/plugins.md` — **Plugins**

  > # Plugins Hermes has a plugin system for adding custom tools, hooks, and integrations without modifying core code. If you want to create a custom tool for yourself, your team, or one project, this is usually the right path. The developer guide's [Adding Tools](../../developer-guide/adding-tools.md) page is for built-in Hermes core tools that live in `tools/` and `toolsets.py`. **→ [Build a Hermes Plugin](../../developer-guide/plugins/index.md)** — step-by-step guide with a complete working example. ## Quick overview Drop a directory into `~/.hermes/plugins/` with a `plugin.yaml` and Python code: ``` ~/.hermes/plugins/my-plugin/ ├── plugin.yaml # manifest ├── __init__.py # register() — wires […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/plugins/index.md` — **Build a Hermes Plugin**

  > # Build a Hermes Plugin This guide walks through building a complete Hermes plugin from scratch. By the end you'll have a working plugin with multiple tools, lifecycle hooks, shipped data files, and a bundled skill — everything the plugin system supports. :::info Not sure which guide you need? Hermes has several distinct pluggable interfaces — some use Python `register_*` APIs, others are config-driven or drop-in directories. Use this map first: | If you want to add… | Read | |---|---| | Custom tools, hooks, slash commands, skills, or CLI subcommands | **This guide** (the general plugin surface) | | A **native desktop app** extension (panes, pages, status bar, palette, themes) | [Desktop […]

---

## v2-038 · simple
**Question :** What are the steps to get Hermes set up on my machine?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:getting-started/installation.md` — **Installation**

  > # Installation Get Hermes Agent up and running in under two minutes! :::tip Platform Support For the full platform support matrix (which OSes, distribution methods, and platform-gated features are supported), see **[Platform Support](./platform-support.md)**. ::: ## Quick Install ### With the Hermes Desktop installer on macOS or Windows (recommended) To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it. :::note The macOS installer is **Apple Silicon only**. macOS on x86 (Intel) processors is [not a supported platform](./platform-support.md#unsupported). ::: ### Without Hermes […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/quickstart.md` — **Hermes Agent Quickstart**

  > # Hermes Agent Quickstart This guide gets you from zero to a working Hermes setup that survives real use. Install, choose a provider, verify a working chat, and know exactly what to do when something breaks. ## Prefer to watch? **Onchain AI Garage** put together a Masterclass walkthrough of installation, setup, and basic commands — a good companion to this page if you'd rather follow along on video. For more, see the full [Hermes Agent Tutorials & Use Cases](https://www.youtube.com/playlist?list=PLmpUb_PWAkDxewld5ZYyKifuHxgIbiq2d) playlist. <div style={{position: 'relative', paddingBottom: '56.25%', height: 0, overflow: 'hidden', maxWidth: '100%', marginBottom: '1.5rem'}}> <iframe […]

---

## v2-039 · simple
**Question :** Give me the overall picture: how do I run models locally with Hermes?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/local-models.md` — **Local Models**

  > # Local Models Hermes can run open models entirely on your own machine. It downloads and manages the inference engine (llama.cpp), picks the right build of each model for your hardware, and handles memory so you never configure context sizes, GPU layers, or quantization. You pick a model; Hermes does the rest. Nothing leaves your computer: no account, no API key, and no network access after a model is downloaded. ## Getting started 1. Open **Settings → Providers → Local Models** (or choose **Run models locally** during onboarding). 2. Click **Install runtime**. Hermes downloads the official llama.cpp build for your hardware (a few hundred MB), verifies it, and keeps it updated. 3. Pick a […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/local-ollama-setup.md` — **Run Hermes Locally with Ollama — Zero API Cost**

  > # Run Hermes Locally with Ollama — Zero API Cost :::tip Desktop users: there's a one-click path On the Hermes desktop app, **Settings → Providers → Local Models** installs and manages a local llama.cpp server for you — model downloads, memory fitting, and context sizing included. See [Local Models](../user-guide/local-models.md). This guide is for manual setup: Ollama specifically, CLI-first workflows, or servers you want to run yourself. ::: ## The Problem Cloud LLM APIs charge per token. A heavy coding session can cost $5–20. For personal projects, learning, or privacy-sensitive work, that adds up — and you're sending every conversation to a third party. ## What This Guide Solves You'll […]

---

## v2-040 · simple
**Question :** Which API lets me programmatically create and track a subagent's lifecycle?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/delegation-patterns.md` — **Delegation & Parallel Work**

  > # Delegation & Parallel Work Hermes can spawn isolated child agents to work on tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window. For the full feature reference, see [Subagent Delegation](../user-guide/features/delegation.md). --- ## When to Delegate **Good candidates for delegation:** - Reasoning-heavy subtasks (debugging, code review, research synthesis) - Tasks that would flood your context with intermediate data - Parallel independent workstreams (research A and B simultaneously) - Fresh-context tasks where you want the agent to approach without bias **Use […]

---

## v2-041 · simple
**Question :** As a user, which service shuttles messages back and forth between the chat platforms and my agent?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/messaging/index.md` — **Messaging Gateway**

  > # Messaging Gateway Chat with Hermes from Telegram, Discord, Slack, WhatsApp, Signal, SMS, Email, Home Assistant, Mattermost, Matrix, DingTalk, Feishu/Lark, WeCom, Weixin, BlueBubbles (iMessage), QQ, Yuanbao, Microsoft Teams, LINE, ntfy, or your browser. The gateway is a single background process that connects to all your configured platforms, handles sessions, runs cron jobs, and delivers voice messages. For the full voice feature set — including CLI microphone mode, spoken replies in messaging, and Discord voice-channel conversations — see [Voice Mode](../features/voice-mode.md) and [Use Voice Mode with Hermes](../../guides/use-voice-mode-with-hermes.md). :::tip Bots need both a model […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

---

## v2-042 · paraphrase
**Question :** How do I plug in a custom component that decides which pieces of information stay in the context as a session goes on?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/context-engine-plugin.md` — **Context Engine Plugins**

  > # Building a Context Engine Plugin Context engine plugins replace the built-in `ContextCompressor` with an alternative strategy for managing conversation context. For example, a Lossless Context Management (LCM) engine that builds a knowledge DAG instead of lossy summarization. ## How it works The agent's context management is built on the `ContextEngine` ABC (`agent/context_engine.py`). The built-in `ContextCompressor` is the default implementation. Plugin engines must implement the same interface. Only **one** context engine can be active at a time. Selection is config-driven: ```yaml # config.yaml context: engine: "compressor" # default built-in engine: "lcm" # activates a plugin engine […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/context-compression-and-caching.md` — **(sans titre)**

  > # Context Compression and Caching Hermes Agent uses a dual compression system and Anthropic prompt caching to manage context window usage efficiently across long conversations. Source files: `agent/context_engine.py` (ABC), `agent/context_compressor.py` (default engine), `agent/prompt_caching.py`, `gateway/run_turn.py` (session hygiene), `agent/compression_facade.py` (search for `_compress_context`) ## Bedrock context window cache Bedrock context resolution in `agent/model_metadata.py` uses this precedence: - **Explicit overrides win.** Configured context lengths take priority over cache, probes, and the static table. - **Provider-confirmed limits persist.** A successful probe or a limit […]

---

## v2-043 · paraphrase
**Question :** How do I make my keys and secrets come from an outside vault instead of being kept on my own box?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/secret-source-plugin.md` — **Secret Source Plugins**

  > # Building a Secret Source Plugin Secret sources resolve provider credentials from an external secret manager (a vault, a password manager, an OS keystore, a custom script) into environment variables at process startup — after `~/.hermes/.env` loads, before Hermes reads credentials. Bitwarden, 1Password, and a generic command-helper source ship in-tree; **every other backend is a plugin**. This guide covers building one. :::tip The bundled set is deliberately closed, same policy as [memory providers](./memory-provider-plugin.md): PRs adding new vault backends under `agent/secret_sources/` are closed with a pointer to this guide. Publish your backend as a standalone plugin repo and share it […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/egress/iron-proxy.md` — **(sans titre)**

  > # Egress credential-injection proxy (iron-proxy) When Hermes runs your agent inside a Docker terminal sandbox, that sandbox normally holds your real upstream API keys (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`, etc.). A prompt-injected agent in that sandbox can `cat ~/.config/openrouter/auth.json` or `printenv | grep -i key` and exfiltrate them. The egress proxy fixes this: the sandbox holds opaque **proxy tokens**, never the real keys. All outbound traffic from the sandbox routes through a local [iron-proxy](https://github.com/ironsh/iron-proxy) daemon (Apache-2.0, Go) on the host, which terminates TLS and swaps the proxy token for the real credential before forwarding the request upstream. […]

---

## v2-044 · paraphrase
**Question :** How can I add a new model backend as an external add-on without touching the Hermes core?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/model-provider-plugin.md` — **Model Provider Plugins**

  > # Building a Model Provider Plugin Model provider plugins declare an inference backend — an OpenAI-compatible endpoint, an Anthropic Messages server, a Codex-style Responses API, or a Bedrock-native surface — that Hermes can route `AIAgent` calls through. Every built-in provider (OpenRouter, Anthropic, GMI, DeepSeek, Nvidia, …) ships as one of these plugins. Third parties can add their own by dropping a directory under `$HERMES_HOME/plugins/model-providers/` with zero changes to the repo. :::tip Model provider plugins are the third kind of **provider plugin**. The others are [Memory Provider Plugins](./memory-provider-plugin.md) (cross-session knowledge) and [Context Engine […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/adding-providers.md` — **Adding Providers**

  > # Adding Providers Hermes can already talk to any OpenAI-compatible endpoint through the custom provider path. Do not add a built-in provider unless you want first-class UX for that service: - provider-specific auth or token refresh - a curated model catalog - setup / `hermes model` menu entries - provider aliases for `provider:model` syntax - a non-OpenAI API shape that needs an adapter If the provider is just "another OpenAI-compatible base URL and API key", a named custom provider may be enough. ## The mental model A built-in provider has to line up across a few layers: 1. `hermes_cli/auth.py` decides how credentials are found. 2. `hermes_cli/runtime_provider.py` turns that into runtime […]

---

## v2-045 · paraphrase
**Question :** How do I hook my own web search engine up to the agent through an add-on?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/web-search-provider-plugin.md` — **Web Search Provider Plugins**

  > # Building a Web Search Provider Plugin Web-search provider plugins register a backend that services `web_search`, `web_extract`, and (optionally) deep-crawl tool calls. Built-in providers — Firecrawl, SearXNG, Tavily, Perplexity, Exa, Parallel, Keenable, Brave Search (free tier), xAI, and DDGS — all ship as plugins under `plugins/web/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Web search is one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Image Generation Provider Plugins](./image-gen-provider-plugin.md), [Video Generation Provider Plugins](./video-gen-provider-plugin.md), [Memory Provider […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/browser-provider-plugin.md` — **Browser Provider Plugins**

  > # Building a Browser Provider Plugin Browser provider plugins register a **cloud browser backend** that services cloud-mode `browser_*` tool calls (navigate, click, screenshot, …). Built-in providers — Browserbase, Browser Use, and Firecrawl — all ship as plugins under `plugins/browser/<name>/`. You can add a new one, or override a bundled one, by dropping a directory next to them. :::tip Browser backends are one of several **backend plugins** Hermes supports. The others (with their own ABCs) are [Web Search Provider Plugins](./web-search-provider-plugin.md) (which this ABC deliberately mirrors), [Image Generation](./image-gen-provider-plugin.md), [Video […]

---

## v2-046 · paraphrase
**Question :** How do I add a third-party image generator to Hermes as an add-on?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/image-gen-provider-plugin.md` — **Image Generation Provider Plugins**

  > # Building an Image Generation Provider Plugin Image-gen provider plugins register a backend that services every `image_generate` tool call — DALL·E, gpt-image, Grok, Flux, Imagen, Stable Diffusion, fal, Replicate, a local ComfyUI rig, anything. Built-in providers (OpenAI, OpenAI-Codex, xAI, FAL, Krea, DeepInfra, OpenRouter, Meta Model API) all ship as plugins. You can add a new one, or override a bundled one, by dropping a directory into `plugins/image_gen/<name>/`. :::tip Image-gen is one of several **backend plugins** Hermes supports. The others (with more specialized ABCs) are [Memory Provider Plugins](./memory-provider-plugin.md), [Context Engine Plugins](./context-engine-plugin.md), […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/video-gen-provider-plugin.md` — **Video Generation Provider Plugins**

  > # Building a Video Generation Provider Plugin Video-gen provider plugins register a backend that services every `video_generate` tool call. Built-in providers (xAI, FAL, OpenRouter, DeepInfra) ship as plugins. Add a new one, or override a bundled one, by dropping a directory into `plugins/video_gen/<name>/`. :::tip Video-gen mirrors [Image Generation Provider Plugins](./image-gen-provider-plugin.md) almost line-for-line — if you've built an image-gen backend, you already know the shape. The main differences: a `capabilities()` method advertising modalities/aspect-ratios/durations, and a routing convention (pass `image_url` to use image-to-video, omit it to use text-to-video — the provider […]

---

## v2-047 · paraphrase
**Question :** On the implementation side, how is spoken audio streamed out as it is being produced?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/streaming-tts.md` — **Streaming TTS Internals**

  > # Streaming TTS Hermes can stream TTS audio as it arrives from the provider, instead of waiting for the full audio before playing. This is used by voice mode (CLI/TUI live conversation), the dashboard speak-stream WebSocket, and — via the gateway `StreamingTTSConsumer` — any platform adapter that opts into streaming audio. Voice replies start speaking after the first clause instead of after full generation + synthesis. ## Architecture The streaming pipeline has four parts: 1. **Producer** — the LLM emits text deltas as it generates a response 2. **Sentence chunker** — `tools.tts_streaming.SentenceChunker` accumulates deltas, strips `<think>` blocks (even split across deltas), and flushes […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/tts.md` — **Voice & TTS**

  > # Voice & TTS Hermes Agent supports both text-to-speech output and voice message transcription across all messaging platforms. :::tip Nous Subscribers If you have a paid [Nous Portal](https://portal.nousresearch.com) subscription, OpenAI TTS is available through the **[Tool Gateway](tool-gateway.md)** without a separate OpenAI API key. New installs can run `hermes setup --portal` to log in and turn on every gateway tool at once; existing installs can pick **Nous Subscription** for just TTS via `hermes model` or `hermes tools`. ::: ## Text-to-Speech Convert text to speech with eleven providers: | Provider | Quality | Cost | API Key | |----------|---------|------|---------| | **Edge TTS** […]

---

## v2-048 · paraphrase
**Question :** How do I keep an eye on the health and metrics of the running message gateway?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/gateway-monitoring.md` — **Gateway Monitoring**

  > # Gateway Monitoring Service health monitoring plus structured operational diagnostics for the Hermes gateway daemon, exported over OTLP/HTTP to an operator-configured endpoint (OpenTelemetry Collector, DataDog, or any OTLP receiver). This plane is content-free by construction. It exports gateway and cron lifecycle state, platform connector health, and content-free warning/error diagnostics. It never exports prompts, messages, tool arguments or results, job names, destinations, schedules, raw errors, session history, usage analytics, audit logs, or detailed execution traces. Run/model/tool trajectory capture is a separate plane served by Hermes's native NeMo Relay SDK integration and […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

---

## v2-049 · paraphrase
**Question :** How do I integrate and drive Hermes straight from my own program?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/programmatic-integration.md` — **Programmatic Integration**

  > # Programmatic Integration Hermes ships three protocols for driving the agent from external programs — IDE plugins, custom UIs, CI pipelines, embedded sub-agents. Pick the one that matches your transport and consumer. | Protocol | Transport | Best for | Defined by | |----------|-----------|----------|------------| | **ACP** | JSON-RPC over stdio | IDE clients (VS Code, Zed, JetBrains) that already speak the [Agent Client Protocol](https://github.com/zed-industries/agent-client-protocol) | `acp_adapter/` | | **TUI gateway** | JSON-RPC over stdio (or WebSocket) | Custom hosts that want fine-grained control of sessions, slash commands, approvals, and streaming events | `tui_gateway/server.py` […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/api-server.md` — **API Server**

  > # API Server The API server exposes hermes-agent as an OpenAI-compatible HTTP endpoint. Any frontend that speaks the OpenAI format — Open WebUI, LobeChat, LibreChat, NextChat, ChatBox, and hundreds more — can connect to hermes-agent and use it as a backend. Your agent handles requests with its full toolset (terminal, file operations, web search, memory, skills) and returns the final response. When streaming, tool progress indicators appear inline so frontends can show what the agent is doing. :::tip One backend covers models + tools Hermes itself needs a configured provider and tool backends for the API server to be useful. A [Nous Portal](./tool-gateway.md) subscription handles both — 300+ […]

---

## v2-050 · paraphrase
**Question :** How do I import Hermes as a Python library and call it from my own script?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/python-library.md` — **Using Hermes as a Python Library**

  > # Using Hermes as a Python Library Hermes isn't just a CLI tool. You can import `AIAgent` directly and use it programmatically in your own Python scripts, web applications, or automation pipelines. This guide shows you how. --- ## Installation Clone Hermes and create its supported editable development environment: ```bash git clone https://github.com/NousResearch/hermes-agent.git cd hermes-agent uv sync ``` Run your application with `uv run python your_app.py` from that checkout. Hermes does not publish a supported wheel or source distribution for `requirements.txt` installs. :::tip The same environment variables used by the CLI are required when using Hermes as a library. At minimum, set […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/programmatic-integration.md` — **Programmatic Integration**

  > # Programmatic Integration Hermes ships three protocols for driving the agent from external programs — IDE plugins, custom UIs, CI pipelines, embedded sub-agents. Pick the one that matches your transport and consumer. | Protocol | Transport | Best for | Defined by | |----------|-----------|----------|------------| | **ACP** | JSON-RPC over stdio | IDE clients (VS Code, Zed, JetBrains) that already speak the [Agent Client Protocol](https://github.com/zed-industries/agent-client-protocol) | `acp_adapter/` | | **TUI gateway** | JSON-RPC over stdio (or WebSocket) | Custom hosts that want fine-grained control of sessions, slash commands, approvals, and streaming events | `tui_gateway/server.py` […]

---

## v2-051 · paraphrase
**Question :** How is billing state tracked and fetched on the client side within the terminal interface?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/billing-lifecycle.md` — **Billing Lifecycle (TUI)**

  > # Billing lifecycle: client-side state, errors, and recovery This is the map from every `billing.*`/`subscription.*` state shape the gateway serves (from NAS) to what the terminal actually renders, and from every typed refusal/error code to its exact user-facing copy and recovery action. The guarantee: no NAS billing state and no typed refusal falls through to a generic toast — every case below is an explicit branch in `ui-tui/src/app/slash/commands/topup.ts`, `ui-tui/src/components/billingOverlay.tsx`, or `ui-tui/src/components/subscriptionOverlay.tsx`. An **unknown** code still degrades gracefully: it hits the `default` branch (a generic-but-real message pulled from the server payload, […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:integrations/nous-portal.md` — **Nous Portal**

  > # Nous Portal [Nous Portal](https://portal.nousresearch.com) is Nous Research's unified subscription gateway and **the recommended way to run Hermes Agent**. One OAuth login replaces the juggling act of separate accounts, API keys, and billing relationships across every model lab, search API, image generator, and browser provider you'd otherwise need to wire up by hand. If you only have time to set up one thing, set up this. The fastest path: ```bash hermes setup --portal ``` That single command runs the Portal OAuth, lets you pick a Nous model, sets Nous as your inference provider in `config.yaml`, and turns on the Tool Gateway. You're ready to `hermes chat` immediately after. Don't have a […]

---

## v2-052 · paraphrase
**Question :** How does Hermes deal with completions left waiting and get them delivered in the background?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/completion-backlog-delivery.md` — **Background completion backlogs**

  > # Background completion backlogs Interactive surfaces coalesce consecutive background-process completions that are already ready for one conversation into a single notification turn. This does not add a delay or promise to combine jobs that finish at different times. Failures and successful outputs remain in the batch; one completion keeps its original text. Process identity remains available until dispatch. Explicit `process_manage` wait/log/kill consumption can therefore suppress a CLI completion even after it has left the process registry and entered the input queue. An entirely consumed batch starts no turn. Watching output and async-delegation results remain separate notifications, in […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-session-lifecycle.md` — **Gateway Session Lifecycle**

  > # Session Lifecycle > **Audience:** Gateway developers and maintainers > **Source files:** `gateway/session.py` (~1200 lines + `session_*.py` siblings), `gateway/run.py` (~5500 lines facade + `run_*.py` phases), `gateway/config.py` > **Last updated:** 2026-06-16 ## Overview A **session** represents a continuous conversation between the agent and one or more users on a messaging platform. The session lifecycle governs when conversations persist, when they reset, how they survive gateway restarts, and how messages queue during concurrent operations. The session system lives primarily in two modules: - `gateway/session.py` — Data model (`SessionSource`, `SessionEntry`, `SessionContext`), key […]

---

## v2-053 · paraphrase
**Question :** How is Hermes's command line put together under the hood?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/cli-internals.md` — **CLI Internals**

  > # CLI Internals Companion to `hermes_cli/AGENTS.md` (the rules) — this page holds the longer explanations. ## Update pipeline The stage-by-stage contract (`plan → snapshot → apply → restart-per-kind → verify → report`) and the field failure each stage guards are documented in `hermes_cli/AGENTS.md`; user-facing behaviour (receipts, `--plan`, snapshot modes) is in [Updating](../getting-started/updating.md). The systemd blunt-restart fallback waits for the unit's `TimeoutStopUSec` plus `TimeoutStartUSec`, with 15 seconds of client-side slack. It reads the target unit in the same manager scope as the restart; both the initial attempt and retry use this budget, including the catch-up restart […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/extending-the-cli.md` — **Extending the CLI**

  > # Extending the CLI Hermes exposes protected extension hooks on `HermesCLI` so wrapper CLIs can add widgets, keybindings, and layout customizations without overriding the `run()` method or the TUI construction in `hermes_cli/cli_tui_mixin.py` (where these hooks are defined; `HermesCLI` in `cli.py` mixes it in). This keeps your extension decoupled from internal changes. ## Extension points There are five extension seams available: | Hook | Purpose | Override when... | |------|---------|------------------| | `_get_extra_tui_widgets()` | Inject widgets into the layout | You need a persistent UI element (panel, status line, mini-player) | | `_register_extra_tui_keybindings(kb, *, input_area)` | […]

---

## v2-054 · paraphrase
**Question :** How do I add my own command to Hermes's command-line tool?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/extending-the-cli.md` — **Extending the CLI**

  > # Extending the CLI Hermes exposes protected extension hooks on `HermesCLI` so wrapper CLIs can add widgets, keybindings, and layout customizations without overriding the `run()` method or the TUI construction in `hermes_cli/cli_tui_mixin.py` (where these hooks are defined; `HermesCLI` in `cli.py` mixes it in). This keeps your extension decoupled from internal changes. ## Extension points There are five extension seams available: | Hook | Purpose | Override when... | |------|---------|------------------| | `_get_extra_tui_widgets()` | Inject widgets into the layout | You need a persistent UI element (panel, status line, mini-player) | | `_register_extra_tui_keybindings(kb, *, input_area)` | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/cli-internals.md` — **CLI Internals**

  > # CLI Internals Companion to `hermes_cli/AGENTS.md` (the rules) — this page holds the longer explanations. ## Update pipeline The stage-by-stage contract (`plan → snapshot → apply → restart-per-kind → verify → report`) and the field failure each stage guards are documented in `hermes_cli/AGENTS.md`; user-facing behaviour (receipts, `--plan`, snapshot modes) is in [Updating](../getting-started/updating.md). The systemd blunt-restart fallback waits for the unit's `TimeoutStopUSec` plus `TimeoutStartUSec`, with 15 seconds of client-side slack. It reads the target unit in the same manager scope as the restart; both the initial attempt and retry use this budget, including the catch-up restart […]

---

## v2-055 · paraphrase
**Question :** What does the open standard for plugging in external tool servers actually give the agent, and how do I install one of those servers to use it?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/mcp.md` — **MCP (Model Context Protocol)**

  > # MCP (Model Context Protocol) MCP lets Hermes Agent connect to external tool servers so the agent can use tools that live outside Hermes itself — GitHub, databases, file systems, browser stacks, internal APIs, and more. If you have ever wanted Hermes to use a tool that already exists somewhere else, MCP is usually the cleanest way to do it. :::tip Coming from Claude Code? The `mcpServers` block in your `~/.claude.json` maps to `mcp_servers` in Hermes' `config.yaml` — and `hermes import-agent claude-code` migrates it (along with skills and instructions) automatically. See [Import from Other Agents](../import-from-other-agents.md). ::: ## What MCP gives you - Access to external tool […]
- `hermes-agent:guides/use-mcp-with-hermes.md` — **Use MCP with Hermes**

  > # Use MCP with Hermes This guide shows how to actually use MCP with Hermes Agent in day-to-day workflows. If the feature page explains what MCP is, this guide is about how to get value from it quickly and safely. ## When should you use MCP? Use MCP when: - a tool already exists in MCP form and you do not want to build a native Hermes tool - you want Hermes to operate against a local or remote system through a clean RPC layer - you want fine-grained per-server exposure control - you want to connect Hermes to internal APIs, databases, or company systems without modifying Hermes core Do not use MCP when: - a built-in Hermes tool already solves the job well - the server exposes a huge dangerous […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/tool-gateway.md` — **Nous Tool Gateway**

  > # Nous Tool Gateway **One subscription. Every tool built in.** The Tool Gateway is included with every paid [Nous Portal](https://portal.nousresearch.com) subscription. It routes Hermes' tool calls — web search, image generation, text-to-speech, and cloud browser automation — through infrastructure Nous already runs, so you don't have to sign up with Firecrawl, FAL, OpenAI, Browser Use, or anyone else just to make your agent useful. <div style={{display: 'flex', gap: '1rem', flexWrap: 'wrap', margin: '1.5rem 0'}}> <a href="https://portal.nousresearch.com/manage-subscription" style={{background: 'var(--ifm-color-primary)', color: 'white', padding: '0.75rem 1.5rem', borderRadius: '6px', […]

---

## v2-056 · paraphrase
**Question :** How do I build an add-on for the desktop app using its dedicated development kit?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/desktop-plugin-sdk.md` — **Desktop Plugin SDK (@hermes/plugin-sdk)**

  > # Desktop Plugin SDK The native [Hermes Desktop](../user-guide/desktop.md) app is contribution-driven: every surface in the window — panes, routes, sidebar nav, status-bar items, palette entries, keybinds, themes — registers into one central registry. Core registers its surfaces exactly the way a plugin does, so the plugin story is the real one, not a bolted-on afterthought. A **desktop plugin** is a single ESM file that default-exports a `HermesPlugin`. It imports one module — `@hermes/plugin-sdk` — and gets everything: the app's live state, the gateway JSON-RPC door, a scoped REST/socket backend namespace, React Query, and the app's own UI kit so plugin UI looks native by default. No repo […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/plugins/index.md` — **Build a Hermes Plugin**

  > # Build a Hermes Plugin This guide walks through building a complete Hermes plugin from scratch. By the end you'll have a working plugin with multiple tools, lifecycle hooks, shipped data files, and a bundled skill — everything the plugin system supports. :::info Not sure which guide you need? Hermes has several distinct pluggable interfaces — some use Python `register_*` APIs, others are config-driven or drop-in directories. Use this map first: | If you want to add… | Read | |---|---| | Custom tools, hooks, slash commands, skills, or CLI subcommands | **This guide** (the general plugin surface) | | A **native desktop app** extension (panes, pages, status bar, palette, themes) | [Desktop […]

---

## v2-057 · paraphrase
**Question :** On a Mac, how do I run a large language model right on the machine without going through the cloud, and what general settings apply to offline models?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/local-llm-on-mac.md` — **Run Local LLMs on Mac**

  > # Run Local LLMs on Mac :::tip Desktop users: there's a one-click path On the Hermes desktop app, **Settings → Providers → Local Models** installs and manages a local llama.cpp server for you — model downloads, memory fitting, and context sizing included. See [Local Models](../user-guide/local-models.md). This guide is for manual setup: MLX, custom builds, or servers you want to run yourself. ::: This guide walks you through running a local LLM server on macOS with an OpenAI-compatible API. You get full privacy, zero API costs, and surprisingly good performance on Apple Silicon. We cover two backends: | Backend | Install | Best at | Format | |---------|---------|---------|--------| | […]
- `hermes-agent:user-guide/local-models.md` — **Local Models**

  > # Local Models Hermes can run open models entirely on your own machine. It downloads and manages the inference engine (llama.cpp), picks the right build of each model for your hardware, and handles memory so you never configure context sizes, GPU layers, or quantization. You pick a model; Hermes does the rest. Nothing leaves your computer: no account, no API key, and no network access after a model is downloaded. ## Getting started 1. Open **Settings → Providers → Local Models** (or choose **Run models locally** during onboarding). 2. Click **Install runtime**. Hermes downloads the official llama.cpp build for your hardware (a few hundred MB), verifies it, and keeps it updated. 3. Pick a […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/local-ollama-setup.md` — **Run Hermes Locally with Ollama — Zero API Cost**

  > # Run Hermes Locally with Ollama — Zero API Cost :::tip Desktop users: there's a one-click path On the Hermes desktop app, **Settings → Providers → Local Models** installs and manages a local llama.cpp server for you — model downloads, memory fitting, and context sizing included. See [Local Models](../user-guide/local-models.md). This guide is for manual setup: Ollama specifically, CLI-first workflows, or servers you want to run yourself. ::: ## The Problem Cloud LLM APIs charge per token. A heavy coding session can cost $5–20. For personal projects, learning, or privacy-sensitive work, that adds up — and you're sending every conversation to a third party. ## What This Guide Solves You'll […]

---

## v2-058 · close_distractor
**Question :** Between adding a tool and running one, which part handles a tool's execution while the agent works — not its creation?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/tools-runtime.md` — **Tools Runtime**

  > # Tools Runtime Hermes tools are self-registering functions grouped into toolsets and executed through a central registry/dispatch system. Primary files: - `tools/registry.py` - `model_tools.py` - `toolsets.py` - `tools/terminal_tool.py` - `tools/environments/*` ## Tool registration model Each tool module calls `registry.register(...)` at import time. `model_tools.py` is responsible for importing/discovering tool modules and building the schema list used by the model. ### How `registry.register()` works Every tool file in `tools/` calls `registry.register()` at module level to declare itself. The function signature is: ```python registry.register( name="terminal", # Unique tool name (used […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/adding-tools.md` — **Adding Tools**

  > # Adding Tools Before writing a tool, ask yourself: **should this be a [skill](creating-skills.md) instead?** :::warning Built-in Core Tools Only This page is for adding a **built-in Hermes tool** to the repository itself. If you want a personal, project-local, or otherwise custom tool without modifying Hermes core, use the plugin route instead: - [Plugins](../user-guide/features/plugins.md) - [Build a Hermes Plugin](./plugins/index.md) Default to plugins for most custom tool creation. Only follow this page when you explicitly want to ship a new built-in tool in `tools/` and `toolsets.py`. ::: Make it a **Skill** when the capability can be expressed as instructions + shell commands + […]

---

## v2-059 · close_distractor
**Question :** Where is the how-to for scheduling my own recurring jobs, as opposed to how the scheduler works internally?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/automate-with-cron.md` — **Automate Anything with Cron**

  > # Automate Anything with Cron The [daily briefing bot tutorial](./daily-briefing-bot.md) covers the basics. This guide goes further — five real-world automation patterns you can adapt for your own workflows. For the full feature reference, see [Scheduled Tasks (Cron)](../user-guide/features/cron.md). :::info Key Concept Cron jobs run in fresh agent sessions with no memory of your current chat. Prompts must be **completely self-contained** — include everything the agent needs to know. ::: :::tip Don't need the LLM? You have two zero-token options. - **Recurring watchdog** where the script already produces the exact message (memory alerts, disk alerts, heartbeats): use [script-only cron […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/cron-internals.md` — **Cron Internals**

  > # Cron Internals The cron subsystem provides scheduled task execution — from simple one-shot delays to recurring cron-expression jobs with skill injection and cross-platform delivery. ## Key Files | File | Purpose | |------|---------| | `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` | | `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking | | `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler | | `gateway/run.py` | Gateway integration — cron ticking in the long-running loop | | `hermes_cli/cron.py` | CLI `hermes cron` subcommands | ## Scheduling Model Four schedule formats are supported: | Format | Example | […]

---

## v2-060 · close_distractor
**Question :** How do I schedule a job that only runs a script with no model involved, as opposed to the regular scheduled tasks?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/cron-script-only.md` — **Script-Only Cron Jobs (No LLM)**

  > # Script-Only Cron Jobs Sometimes you already know exactly what message you want to send. You don't need an agent to reason about it — you just need a script to run on a timer, and its output (if any) to land in Telegram / Discord / Slack / Signal. Hermes calls this **no-agent mode**. It's the cron system minus the LLM. <!-- ascii-guard-ignore --> ``` ┌──────────────────┐ ┌──────────────────┐ │ scheduler tick │ every │ run script │ │ (every N minutes)│ ──────▶ │ (bash or python) │ └──────────────────┘ └──────────────────┘ │ │ stdout ▼ ┌──────────────────┐ │ delivery router │ │ (telegram/disc…) │ └──────────────────┘ ``` <!-- ascii-guard-ignore-end --> - **No LLM call.** Zero tokens, zero […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/cron.md` — **Scheduled Tasks (Cron)**

  > # Scheduled Tasks (Cron) Schedule tasks to run automatically with natural language or cron expressions. Hermes exposes cron management through a single `cronjob` tool with action-style operations instead of separate schedule/list/remove tools. ## What cron can do now Cron jobs can: - schedule one-shot or recurring tasks - pause, resume, edit, trigger, and remove jobs - attach zero, one, or multiple skills to a job - deliver results back to the origin chat, local files, or configured platform targets - run in fresh agent sessions with the normal static tool list - run in **no-agent mode** — a script on a schedule, its stdout delivered verbatim, zero LLM involvement (see the [no-agent […]

---

## v2-061 · close_distractor
**Question :** What manages a session's lifecycle on the gateway side — opening it, keeping it alive, closing it — as opposed to where that session's state is stored?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/gateway-session-lifecycle.md` — **Gateway Session Lifecycle**

  > # Session Lifecycle > **Audience:** Gateway developers and maintainers > **Source files:** `gateway/session.py` (~1200 lines + `session_*.py` siblings), `gateway/run.py` (~5500 lines facade + `run_*.py` phases), `gateway/config.py` > **Last updated:** 2026-06-16 ## Overview A **session** represents a continuous conversation between the agent and one or more users on a messaging platform. The session lifecycle governs when conversations persist, when they reset, how they survive gateway restarts, and how messages queue during concurrent operations. The session system lives primarily in two modules: - `gateway/session.py` — Data model (`SessionSource`, `SessionEntry`, `SessionContext`), key […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/session-storage.md` — **(sans titre)**

  > # Session Storage Hermes Agent uses a SQLite database (`~/.hermes/state.db`) to persist session metadata, full message history, and model configuration across CLI and gateway sessions. This replaces the earlier per-session JSONL file approach. Source files: `hermes_state.py` (facade) plus the `hermes_state_*.py` siblings (schema, fts, search, compression, portability, gateway, ...) ## Hermes home and profile isolation `get_hermes_home()` is the authoritative filesystem resolver for state and configuration. It uses a context-local override first, then the `HERMES_HOME` environment variable, and finally the platform default (`~/.hermes` on macOS and Linux; `%LOCALAPPDATA%/hermes` on Windows). […]

---

## v2-062 · close_distractor
**Question :** Which part handles multiplexing several connections over a single gateway, rather than how the basic gateway itself works?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/multiplexing-gateway.md` — **Multiplexing Gateway Internals**

  > # Multiplexing Gateway One gateway process can serve every profile in the install. The mode is on by default (`gateway.multiplex_profiles`, default `true`), and everything it changes reverts the moment the flag is off. An *unset* flag is settled at boot by `hermes_cli/gateway_multiplex_mode.py::resolve_multiplex_mode`, which runs the `hermes gateway migrate` preflight and keeps the gateway standalone when a secondary still runs its own gateway, a blocker exists, or the host cannot be migrated (see "The mode flag"). This document is the design rationale referenced from `agent/secret_scope.py` ("Workstream A"): what is isolated per profile, the mechanism that isolates it, and what […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

---

## v2-063 · close_distractor
**Question :** How do I turn on back-and-forth spoken conversation mode, as opposed to merely having replies synthesized into audio?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/voice-mode.md` — **Voice Mode**

  > # Voice Mode Hermes Agent supports full voice interaction across CLI and messaging platforms. Talk to the agent using your microphone, hear spoken replies, and have live voice conversations in Discord voice channels. If you want a practical setup walkthrough with recommended configurations and real usage patterns, see [Use Voice Mode with Hermes](../../guides/use-voice-mode-with-hermes.md). For hands-free session start — saying "hey hermes" (or any phrase) to open a fresh voice session on the CLI, TUI, or desktop app — see [Wake Word](./wake-word.md). ## Prerequisites Before using voice features, make sure you have: 1. **Hermes Agent installed** — via the install script (see […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/tts.md` — **Voice & TTS**

  > # Voice & TTS Hermes Agent supports both text-to-speech output and voice message transcription across all messaging platforms. :::tip Nous Subscribers If you have a paid [Nous Portal](https://portal.nousresearch.com) subscription, OpenAI TTS is available through the **[Tool Gateway](tool-gateway.md)** without a separate OpenAI API key. New installs can run `hermes setup --portal` to log in and turn on every gateway tool at once; existing installs can pick **Nous Subscription** for just TTS via `hermes model` or `hermes tools`. ::: ## Text-to-Speech Convert text to speech with eleven providers: | Provider | Quality | Cost | API Key | |----------|---------|------|---------| | **Edge TTS** […]

---

## v2-064 · close_distractor
**Question :** Where do I browse the inventory of available add-ons, as opposed to the instructions for actually using them?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/plugin-catalog.md` — **Plugin Catalog**

  > # Plugin Catalog The plugin catalog is a curated, human-reviewed directory of Hermes plugins you can install by name with a single command: ```bash hermes plugins install <name> ``` Browse it visually at **[/docs/plugins](/plugins)** — entries are shelved by category (Memory, Desktop, Platforms, Web & Browser, Tools, Voice, Automation, Models), with search, tier filters (Official / Community), capability chips, and copyable install commands for every entry. The catalog complements — it does not replace — the existing [plugin system](plugins.md). Anything you can install from the catalog is a normal plugin under the hood; the catalog just adds discovery and a review layer on top. ## What's […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/plugins.md` — **Plugins**

  > # Plugins Hermes has a plugin system for adding custom tools, hooks, and integrations without modifying core code. If you want to create a custom tool for yourself, your team, or one project, this is usually the right path. The developer guide's [Adding Tools](../../developer-guide/adding-tools.md) page is for built-in Hermes core tools that live in `tools/` and `toolsets.py`. **→ [Build a Hermes Plugin](../../developer-guide/plugins/index.md)** — step-by-step guide with a complete working example. ## Quick overview Drop a directory into `~/.hermes/plugins/` with a `plugin.yaml` and Python code: ``` ~/.hermes/plugins/my-plugin/ ├── plugin.yaml # manifest ├── __init__.py # register() — wires […]

---

## v2-065 · close_distractor
**Question :** How do I launch the terminal UI or the desktop app from a dedicated working copy, as opposed to managing Git working copies in general?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/worktree-ui-dev.md` — **TUI & Desktop from Worktrees**

  > # TUI & Desktop from Worktrees The Python core runs fine from any [git worktree](../user-guide/git-worktrees.md) — `cd` in and `hermes` just works. The two TypeScript surfaces do not: `ui-tui/` and `apps/desktop/` each need a populated `node_modules`, and a fresh `npm ci` per worktree is slow and duplicates gigabytes across every branch you have checked out. `htui` and `hgui` are two shell helpers that close that gap. Each launches its surface **from the current worktree** while borrowing `node_modules` from one canonical checkout — so a throwaway branch costs a symlink, not an install. They're developer conveniences, not shipped commands. Drop them in `~/.zshrc`; adapt paths to taste. ## […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/git-worktrees.md` — **Git Worktrees**

  > # Git Worktrees Hermes Agent is often used on large, long‑lived repositories. When you want to: - Run **multiple agents in parallel** on the same project, or - Keep experimental refactors isolated from your main branch, Git **worktrees** are the safest way to give each agent its own checkout without duplicating the entire repository. This page shows how to combine worktrees with Hermes so each session has a clean, isolated working directory. ## Why Use Worktrees with Hermes? Hermes treats the **current working directory** as the project root: - CLI: the directory where you run `hermes` or `hermes chat` - Messaging gateways: the directory set by `terminal.cwd` in `~/.hermes/config.yaml` If […]

---

## v2-066 · close_distractor
**Question :** How do I remotely administer my hosted Hermes instance through the standard protocol for external tool servers, as opposed to using that protocol locally in the general case?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/manage-hermes-cloud-with-mcp.md` — **Manage Hermes Cloud with MCP**

  > # Manage Hermes Cloud with MCP [Hermes Cloud](https://portal.nousresearch.com/cloud) runs hosted Hermes Agent instances for you. Normally you manage them from the `/agents` page in the [Nous Portal](../integrations/nous-portal.md). This guide connects your **local** Hermes Agent to the Portal's MCP server so you can manage those cloud instances by just asking — "list my cloud agents", "restart the stopped one", "what's it costing me" — without leaving your terminal. It's a standard [MCP](../user-guide/features/mcp.md) server hosted by Nous Research, gated by the same OAuth login you already use for the Portal. Once connected, Hermes gets two tools it can call on your behalf. ## What you can […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/use-mcp-with-hermes.md` — **Use MCP with Hermes**

  > # Use MCP with Hermes This guide shows how to actually use MCP with Hermes Agent in day-to-day workflows. If the feature page explains what MCP is, this guide is about how to get value from it quickly and safely. ## When should you use MCP? Use MCP when: - a tool already exists in MCP form and you do not want to build a native Hermes tool - you want Hermes to operate against a local or remote system through a clean RPC layer - you want fine-grained per-server exposure control - you want to connect Hermes to internal APIs, databases, or company systems without modifying Hermes core Do not use MCP when: - a built-in Hermes tool already solves the job well - the server exposes a huge dangerous […]

---

## v2-067 · close_distractor
**Question :** How do I run the Teams meetings workflow day to day once it is set up, as opposed to the initial meeting setup?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/operate-teams-meeting-pipeline.md` — **Operate the Teams Meeting Pipeline**

  > # Operate the Teams Meeting Pipeline Use this guide after you have already enabled the feature from [Teams Meetings](../user-guide/messaging/teams-meetings.md). This page covers: - operator CLI flows - routine subscription maintenance - failure triage - go-live checks - rollout worksheet ## Core Operator Commands ### Validate the config snapshot ```bash hermes teams-pipeline validate ``` Use this first after any config change. ### Inspect token health ```bash hermes teams-pipeline token-health hermes teams-pipeline token-health --force-refresh ``` Use `--force-refresh` when you suspect stale auth state. ### Inspect subscriptions ```bash hermes teams-pipeline subscriptions ``` ### Renew […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/teams-meetings.md` — **Teams Meetings**

  > # Microsoft Teams Meetings Use the Teams meeting pipeline when you want Hermes to ingest Microsoft Graph meeting events, fetch transcripts first, fall back to recordings plus STT when needed, and deliver a structured summary to downstream sinks. Prerequisites: see [Microsoft Teams](./teams.md) for the underlying bot/credential setup. > Run `hermes gateway setup` and pick **Teams Meetings** for a guided walk-through. This page focuses on setup and enablement: - Graph credentials - webhook listener configuration - Teams delivery modes - pipeline config shape For day-2 operations, go-live checks, and the operator worksheet, use the dedicated guide: [Operate the Teams Meeting […]

---

## v2-068 · close_distractor
**Question :** How do I register an application with Microsoft Graph to obtain the permissions, as opposed to listening for the incoming notifications?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/microsoft-graph-app-registration.md` — **Register a Microsoft Graph Application**

  > # Register a Microsoft Graph Application The Teams meeting pipeline reads meeting transcripts, recordings, and related artifacts from Microsoft Graph using **app-only** (daemon) authentication — no user sign-in, no interactive consent per meeting. That requires an Azure AD application registration with admin-consented application permissions. This guide walks through: 1. Creating the app registration 2. Creating a client secret 3. Granting the Graph API permissions the pipeline needs 4. Admin-consenting those permissions 5. (Optional) Scoping the app to specific users with an Application Access Policy You need **tenant admin rights** (or an admin to grant consent on your behalf) to finish […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/msgraph-webhook.md` — **Microsoft Graph Webhook Listener**

  > # Microsoft Graph Webhook Listener The `msgraph_webhook` gateway platform is an inbound event listener. It's how Hermes receives **change notifications** from Microsoft Graph — "a Teams meeting ended," "a new message landed in this chat," "this calendar event was updated." Different from the `teams` platform (which is a chat bot users type to) — this one is M365 telling Hermes something happened, not a person. Right now the primary consumer is the Teams meeting summary pipeline: Graph notifies when a meeting produces a transcript, the pipeline fetches it, and Hermes posts a summary back into Teams. Other Graph resources (`/chats/.../messages`, `/users/.../events`) use the same listener — […]

---

## v2-069 · close_distractor
**Question :** How do I set Hermes up to go through Google Cloud's managed machine-learning platform with deployed model endpoints, as opposed to the consumer Gemini API?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/google-vertex.md` — **Google Vertex AI**

  > # Google Vertex AI Hermes Agent supports **Gemini models on Google Cloud Vertex AI** through Vertex's OpenAI-compatible endpoint. Unlike the [Google AI Studio provider](./google-gemini.md) (which uses a static API key against `generativelanguage.googleapis.com`), Vertex gives you **enterprise-grade rate limits and GCP billing/credits**, and is the right choice when you want Gemini usage to draw on your Google Cloud account rather than an AI Studio key. :::info Vertex authenticates with OAuth2, not an API key Vertex has **no static API key** for the standard endpoint. Every request needs a short-lived **OAuth2 access token** (≈1 hour TTL) minted from either a service-account JSON or […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/google-gemini.md` — **Google Gemini**

  > # Google Gemini Hermes Agent supports Google Gemini as a native provider using the **Google AI Studio / Gemini API** — not the OpenAI-compatible endpoint. This lets Hermes translate its internal OpenAI-shaped message and tool loop into Gemini's native `generateContent` API while preserving tool calling, streaming, multimodal inputs, and Gemini-specific response metadata. ## Prerequisites - **Google AI Studio API key** — create one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) - **Billing-enabled Google Cloud project** — recommended for agent use. Gemini's free tier is too small for long-running agent sessions because Hermes may make several model calls per user turn. - […]

---

## v2-070 · close_distractor
**Question :** As a user, how do I configure the outbound traffic proxy, as opposed to how it works internally?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/egress/index.md` — **Egress proxy**

  > # Egress proxy Optional outbound credential-injection firewall for remote terminal sandboxes. The sandbox only ever holds opaque proxy tokens; real API keys never leave the host. - [iron-proxy](./iron-proxy) — single-binary TLS-intercepting proxy from [ironsh/iron-proxy](https://github.com/ironsh/iron-proxy), lazy-installed and managed by `hermes egress`.

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/egress-internals.md` — **Egress proxy internals**

  > # Egress proxy internals This page covers the architecture of the egress credential-injection firewall (`hermes egress` / iron-proxy) from a contributor / plugin author's perspective. End-user setup + usage docs live at [Egress proxy](../user-guide/egress/iron-proxy.md). The threat model and high-level design are summarised on the user page; this page is about *how* it's wired, where the security-relevant code lives, and what invariants you have to preserve if you touch it. ## Module layout ```text agent/proxy_sources/iron_proxy.py Core: binary install, CA gen, config build, subprocess lifecycle, mappings I/O, PID/nonce defense. Pure-function surface where possible. hermes_cli/proxy_cli.py […]

---

## v2-071 · close_distractor
**Question :** Where is the reference integration page for the Nous subscription portal described — what it is and what it exposes — as opposed to the step-by-step setup tutorial?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:integrations/nous-portal.md` — **Nous Portal**

  > # Nous Portal [Nous Portal](https://portal.nousresearch.com) is Nous Research's unified subscription gateway and **the recommended way to run Hermes Agent**. One OAuth login replaces the juggling act of separate accounts, API keys, and billing relationships across every model lab, search API, image generator, and browser provider you'd otherwise need to wire up by hand. If you only have time to set up one thing, set up this. The fastest path: ```bash hermes setup --portal ``` That single command runs the Portal OAuth, lets you pick a Nous model, sets Nous as your inference provider in `config.yaml`, and turns on the Tool Gateway. You're ready to `hermes chat` immediately after. Don't have a […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/run-hermes-with-nous-portal.md` — **Run Hermes Agent with Nous Portal**

  > # Run Hermes Agent with Nous Portal This guide walks you through running Hermes Agent on a [Nous Portal](https://portal.nousresearch.com) subscription end to end — from signing up to verifying that every tool routes correctly. If you just want the overview of what the Portal is and what's in the subscription, see the [Nous Portal integration page](../integrations/nous-portal.md). This page is the task script. ## Prerequisites - Hermes Agent installed ([Quickstart](../getting-started/quickstart.md)) - A web browser on the machine you're setting up (or SSH port forwarding — see [OAuth over SSH](./oauth-over-ssh.md)) - About 5 minutes You do **not** need: an OpenAI key, an Anthropic key, a […]

---

## v2-072 · close_distractor
**Question :** How do I authenticate via OAuth on a remote host reached over SSH, as opposed to the native sign-in from the desktop app?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:guides/oauth-over-ssh.md` — **OAuth over SSH / Remote Hosts**

  > # OAuth over SSH / Remote Hosts Some Hermes providers — **Spotify** and **remote MCP servers** (Linear, Sentry, Atlassian, Asana, Figma, …) — use a *loopback redirect* OAuth flow. The auth server redirects your browser to `http://127.0.0.1:<port>/callback` so a tiny HTTP listener started by Hermes can grab the authorization code. This works perfectly when Hermes and your browser are on the same machine. It breaks the moment they aren't: your laptop's browser tries to reach `127.0.0.1` on **your laptop**, but the listener is bound to `127.0.0.1` on **the remote server**. The fix is a one-line SSH local-forward. For MCP servers on an interactive terminal, you can often paste the redirect URL […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/desktop-native-signin.md` — **Desktop Native Sign-In (RFC 8252)**

  > # Desktop Native Sign-In (RFC 8252) When the Hermes Desktop app connects to a **gated gateway** (a hosted or self-hosted dashboard that sits behind an OAuth provider), it can sign in two ways: 1. **Native sign-in (RFC 8252)** — the app opens your **real system browser**, you approve in the browser you already trust, and the app receives tokens it stores as owner-only files in its user-data directory (optionally encrypted with your OS keychain — Settings → Gateway). **No embedded webview, no browser session cookies.** This is the default whenever the gateway supports it. 2. **Embedded sign-in (legacy fallback)** — the app opens a small in-app browser window and captures the gateway's session […]

---

## v2-073 · close_distractor
**Question :** Where are the shared metrics emitted by the relay described, as opposed to the interface contract between the relay and a connector?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/relay-shared-metrics.md` — **Relay Shared Metrics**

  > # NeMo Relay Shared Metrics Hermes includes NeMo Relay as a normal runtime dependency on platforms for which Relay publishes a native wheel. The shared-metrics integration is built into Hermes and does not require a Hermes observability plugin. Hermes remains importable without Relay on other native targets. Those targets use an explicit reduced-capability no-op host: Hermes execution remains available, while Relay scopes, middleware, plugins, and subscribers are unavailable. The `hermes-agent[nemo-relay]` extra remains as a no-op compatibility alias for existing installation commands. > [!WARNING] > This removes the Hermes `observability/nemo_relay` plugin. Existing users > must remove […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/relay-connector-contract.md` — **Relay ↔ Connector Contract**

  > # Relay ↔ Connector Contract (v1, EXPERIMENTAL) > **Status:** EXPERIMENTAL. This contract MAY CHANGE without a deprecation > cycle until at least two real Class-1 platforms (Discord + Telegram) have > validated it. Evolution during the experimental phase is **additive-only**, > gated by `contract_version`. A breaking change updates both repos in lockstep. This document is the formal interface between the **Hermes gateway** (Python, `gateway/relay/`) and the **connector** (Node/TypeScript, `NousResearch/gateway-gateway`). The connector implementer's first action is to read this file. The gateway runs a generic `RelayAdapter` that dials **out** to the connector, receives a […]

---

## v2-074 · chunk_boundary
**Question :** When a gateway connection drops in the middle of a session, how are reconnection and session continuity handled?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/gateway-session-lifecycle.md` — **Gateway Session Lifecycle**

  > # Session Lifecycle > **Audience:** Gateway developers and maintainers > **Source files:** `gateway/session.py` (~1200 lines + `session_*.py` siblings), `gateway/run.py` (~5500 lines facade + `run_*.py` phases), `gateway/config.py` > **Last updated:** 2026-06-16 ## Overview A **session** represents a continuous conversation between the agent and one or more users on a messaging platform. The session lifecycle governs when conversations persist, when they reset, how they survive gateway restarts, and how messages queue during concurrent operations. The session system lives primarily in two modules: - `gateway/session.py` — Data model (`SessionSource`, `SessionEntry`, `SessionContext`), key […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

---

## v2-075 · chunk_boundary
**Question :** In what form are the state and schedule of recurring jobs persisted across restarts of the scheduler?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/cron-internals.md` — **Cron Internals**

  > # Cron Internals The cron subsystem provides scheduled task execution — from simple one-shot delays to recurring cron-expression jobs with skill injection and cross-platform delivery. ## Key Files | File | Purpose | |------|---------| | `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` | | `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking | | `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler | | `gateway/run.py` | Gateway integration — cron ticking in the long-running loop | | `hermes_cli/cron.py` | CLI `hermes cron` subcommands | ## Scheduling Model Four schedule formats are supported: | Format | Example | […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/chronos-managed-cron-contract.md` — **Chronos Managed-Cron Contract**

  > # Chronos managed-cron — agent ↔ NAS wire contract **Status:** authoritative wire spec for the Chronos cron provider. **Audience:** the NAS-side implementer of the `agent-cron` endpoints (`nous-account-service`) and anyone debugging the managed-cron path. Chronos lets a hosted Hermes gateway **scale to zero** while idle and still fire cron jobs. Instead of an in-process 60-second ticker, the agent asks NAS to arm exactly **one external one-shot per job at that job's real next-fire time**. NAS calls the agent back at fire time over an authenticated webhook; the agent runs the job and re-arms the next one-shot. Between fires the agent process can be fully stopped — it wakes only on a genuine […]

---

## v2-076 · chunk_boundary
**Question :** In the host-integration protocol, how does the adapter handle two tool calls that carry the same name within a single turn?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/acp-internals.md` — **ACP Internals**

  > # ACP Internals The ACP adapter wraps Hermes' synchronous `AIAgent` in an async JSON-RPC stdio server. Key implementation files: - `acp_adapter/entry.py` - `acp_adapter/server.py` - `acp_adapter/session.py` - `acp_adapter/events.py` - `acp_adapter/permissions.py` - `acp_adapter/tools.py` - `acp_adapter/auth.py` ## Boot flow ```text hermes acp / hermes-acp / python -m acp_adapter -> acp_adapter.entry.main() -> parse --version / --check / --setup before server startup -> load ~/.hermes/.env -> configure stderr logging -> construct HermesACPAgent -> acp.run_agent(agent, use_unstable_protocol=True) ``` Stdout is reserved for ACP JSON-RPC transport. Human-readable logs go to stderr. ## Major […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/programmatic-integration.md` — **Programmatic Integration**

  > # Programmatic Integration Hermes ships three protocols for driving the agent from external programs — IDE plugins, custom UIs, CI pipelines, embedded sub-agents. Pick the one that matches your transport and consumer. | Protocol | Transport | Best for | Defined by | |----------|-----------|----------|------------| | **ACP** | JSON-RPC over stdio | IDE clients (VS Code, Zed, JetBrains) that already speak the [Agent Client Protocol](https://github.com/zed-industries/agent-client-protocol) | `acp_adapter/` | | **TUI gateway** | JSON-RPC over stdio (or WebSocket) | Custom hosts that want fine-grained control of sessions, slash commands, approvals, and streaming events | `tui_gateway/server.py` […]

---

## v2-077 · chunk_boundary
**Question :** Which parts of the prompt are added only at the moment of the model call, rather than being part of the cached system layers?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/prompt-assembly.md` — **Prompt Assembly**

  > # Prompt Assembly Hermes deliberately separates: - **cached system prompt state** - **ephemeral API-call-time additions** This is one of the most important design choices in the project because it affects: - token usage - prompt caching effectiveness - session continuity - memory correctness Primary files: - `run_agent.py` - `agent/prompt_builder.py` - `tools/memory_tool.py` ## Cached system prompt layers The cached system prompt is assembled as three ordered tiers (see `agent/system_prompt.py`): 1. **stable** — identity (`SOUL.md` or fallback), tool/model guidance, coding operating brief 2. **context** — caller-supplied `system_message`, project context files (`.hermes.md` / `AGENTS.md` / […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/context-compression-and-caching.md` — **(sans titre)**

  > # Context Compression and Caching Hermes Agent uses a dual compression system and Anthropic prompt caching to manage context window usage efficiently across long conversations. Source files: `agent/context_engine.py` (ABC), `agent/context_compressor.py` (default engine), `agent/prompt_caching.py`, `gateway/run_turn.py` (session hygiene), `agent/compression_facade.py` (search for `_compress_context`) ## Bedrock context window cache Bedrock context resolution in `agent/model_metadata.py` uses this precedence: - **Explicit overrides win.** Configured context lengths take priority over cache, probes, and the static table. - **Provider-confirmed limits persist.** A successful probe or a limit […]

---

## v2-078 · chunk_boundary
**Question :** What watches the driven browser and relaunches it if it crashes or stops responding?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/browser-supervisor.md` — **Browser CDP Supervisor**

  > # Browser CDP Supervisor The CDP supervisor closes two long-standing gaps in Hermes' browser tooling: 1. **Native JS dialogs** (`alert`/`confirm`/`prompt`/`beforeunload`) block the page's JS thread. Without supervision, the agent has no way to know a dialog is open — subsequent tool calls hang or throw opaque errors. 2. **Cross-origin iframes (OOPIFs)** are invisible to top-level `Runtime.evaluate`. The agent can see iframe nodes in the DOM snapshot but can't click, type, or eval inside them without a CDP session attached to the child target. The supervisor solves both by holding a persistent WebSocket to the backend's CDP endpoint per browser task, surfacing pending dialogs and frame […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/browser.md` — **Browser Automation**

  > # Browser Automation Hermes Agent includes a full browser automation toolset with multiple backend options: - **Browser Use cloud mode** via [Browser Use](https://browser-use.com) for managed Chromium with stealth, residential proxies, CAPTCHA solving, and reusable browser profiles - **Browserbase cloud mode** via [Browserbase](https://browserbase.com) as an alternative cloud browser provider with anti-bot tooling - **Browser Use mode** via the [Browser Use CLI 3.0](https://github.com/browser-use/browser-use), the default browser driver for local Chrome and Browser Use cloud browsers - **Firecrawl cloud mode** via [Firecrawl](https://firecrawl.dev) for cloud browsers with built-in scraping […]

---

## v2-079 · chunk_boundary
**Question :** What specific state transitions does a subagent move through between its creation and its termination, as exposed by the public API?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/delegation-patterns.md` — **Delegation & Parallel Work**

  > # Delegation & Parallel Work Hermes can spawn isolated child agents to work on tasks in parallel. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary comes back — intermediate tool calls never enter your context window. For the full feature reference, see [Subagent Delegation](../user-guide/features/delegation.md). --- ## When to Delegate **Good candidates for delegation:** - Reasoning-heavy subtasks (debugging, code review, research synthesis) - Tasks that would flood your context with intermediate data - Parallel independent workstreams (research A and B simultaneously) - Fresh-context tasks where you want the agent to approach without bias **Use […]

---

## v2-080 · chunk_boundary
**Question :** Which specific field of the relay-to-connector contract governs acknowledgment or resumption of a message, and where is it defined in the spec?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/relay-connector-contract.md` — **Relay ↔ Connector Contract**

  > # Relay ↔ Connector Contract (v1, EXPERIMENTAL) > **Status:** EXPERIMENTAL. This contract MAY CHANGE without a deprecation > cycle until at least two real Class-1 platforms (Discord + Telegram) have > validated it. Evolution during the experimental phase is **additive-only**, > gated by `contract_version`. A breaking change updates both repos in lockstep. This document is the formal interface between the **Hermes gateway** (Python, `gateway/relay/`) and the **connector** (Node/TypeScript, `NousResearch/gateway-gateway`). The connector implementer's first action is to read this file. The gateway runs a generic `RelayAdapter` that dials **out** to the connector, receives a […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/relay-shared-metrics.md` — **Relay Shared Metrics**

  > # NeMo Relay Shared Metrics Hermes includes NeMo Relay as a normal runtime dependency on platforms for which Relay publishes a native wheel. The shared-metrics integration is built into Hermes and does not require a Hermes observability plugin. Hermes remains importable without Relay on other native targets. Those targets use an explicit reduced-capability no-op host: Hermes execution remains available, while Relay scopes, middleware, plugins, and subscribers are unavailable. The `hermes-agent[nemo-relay]` extra remains as a no-op compatibility alias for existing installation commands. > [!WARNING] > This removes the Hermes `observability/nemo_relay` plugin. Existing users > must remove […]

---

## v2-081 · chunk_boundary
**Question :** In the managed-cron agreement between the agent and the remote server, which field marks that a job has been taken over or must be replayed, and where is it defined?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/chronos-managed-cron-contract.md` — **Chronos Managed-Cron Contract**

  > # Chronos managed-cron — agent ↔ NAS wire contract **Status:** authoritative wire spec for the Chronos cron provider. **Audience:** the NAS-side implementer of the `agent-cron` endpoints (`nous-account-service`) and anyone debugging the managed-cron path. Chronos lets a hosted Hermes gateway **scale to zero** while idle and still fire cron jobs. Instead of an in-process 60-second ticker, the agent asks NAS to arm exactly **one external one-shot per job at that job's real next-fire time**. NAS calls the agent back at fire time over an authenticated webhook; the agent runs the job and re-arms the next one-shot. Between fires the agent process can be fully stopped — it wakes only on a genuine […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/cron-internals.md` — **Cron Internals**

  > # Cron Internals The cron subsystem provides scheduled task execution — from simple one-shot delays to recurring cron-expression jobs with skill injection and cross-platform delivery. ## Key Files | File | Purpose | |------|---------| | `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` | | `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking | | `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler | | `gateway/run.py` | Gateway integration — cron ticking in the long-running loop | | `hermes_cli/cron.py` | CLI `hermes cron` subcommands | ## Scheduling Model Four schedule formats are supported: | Format | Example | […]

---

## v2-082 · chunk_boundary
**Question :** During a recovery of the state database, how is the full-text search index rebuilt, and at which step?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/state-db-recovery.md` — **State DB Recovery**

  > # State database and FTS recovery `state.db` stores two different data classes: - `sessions` and `messages` are the canonical transcript. - `messages_fts*` tables and their sync triggers are derived search indexes. The derived indexes may be detached temporarily. They must not turn a live message write or search into an unbounded full-transcript rebuild. ## Live behavior when FTS is corrupt If an FTS write or search reports the corruption error class, `SessionDB`: 1. records the durable `fts_stale` marker; 2. removes the FTS sync triggers in the same transaction; 3. retries canonical writes without the derived-index sinks; and 4. serves searches from canonical rows through the `LIKE` […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/checkpoints-and-rollback.md` — **Checkpoints and /rollback**

  > # Checkpoints and `/rollback` Hermes Agent can automatically snapshot your project before **destructive operations** and restore it with a single command. Checkpoints are **opt-in** as of v2 — most users never use `/rollback`, and the shadow-store storage is non-trivial over time, so the default is off. Enable checkpoints per-session with `--checkpoints`: ```bash hermes chat --checkpoints ``` Or enable globally in `~/.hermes/config.yaml`: ```yaml checkpoints: enabled: true ``` This safety net is powered by an internal **Checkpoint Manager** that keeps a single shared shadow git repository under `~/.hermes/checkpoints/store/` — your real project `.git` is never touched. Every project the […]

---

## v2-083 · chunk_boundary
**Question :** At what threshold does monitoring of the running gateway raise an alert, and what signal is emitted?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/gateway-monitoring.md` — **Gateway Monitoring**

  > # Gateway Monitoring Service health monitoring plus structured operational diagnostics for the Hermes gateway daemon, exported over OTLP/HTTP to an operator-configured endpoint (OpenTelemetry Collector, DataDog, or any OTLP receiver). This plane is content-free by construction. It exports gateway and cron lifecycle state, platform connector health, and content-free warning/error diagnostics. It never exports prompts, messages, tool arguments or results, job names, destinations, schedules, raw errors, session history, usage analytics, audit logs, or detailed execution traces. Run/model/tool trajectory capture is a separate plane served by Hermes's native NeMo Relay SDK integration and […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

---

## v2-084 · chunk_boundary
**Question :** What precise filtering rule does the outbound proxy apply to requests aimed at domains that are not allowed, as described further down in the doc?

**Document(s) pertinent(s) proposé(s) :**
- `hermes-agent:developer-guide/egress-internals.md` — **Egress proxy internals**

  > # Egress proxy internals This page covers the architecture of the egress credential-injection firewall (`hermes egress` / iron-proxy) from a contributor / plugin author's perspective. End-user setup + usage docs live at [Egress proxy](../user-guide/egress/iron-proxy.md). The threat model and high-level design are summarised on the user page; this page is about *how* it's wired, where the security-relevant code lives, and what invariants you have to preserve if you touch it. ## Module layout ```text agent/proxy_sources/iron_proxy.py Core: binary install, CA gen, config build, subprocess lifecycle, mappings I/O, PID/nonce defense. Pure-function surface where possible. hermes_cli/proxy_cli.py […]

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/egress/index.md` — **Egress proxy**

  > # Egress proxy Optional outbound credential-injection firewall for remote terminal sandboxes. The sandbox only ever holds opaque proxy tokens; real API keys never leave the host. - [iron-proxy](./iron-proxy) — single-binary TLS-intercepting proxy from [ironsh/iron-proxy](https://github.com/ironsh/iron-proxy), lazy-installed and managed by `hermes egress`.

---

## v2-085 · no_answer
**Question :** What is the maximum number of browser tabs the agent can drive at the same time?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/browser.md` — **Browser Automation**

  > # Browser Automation Hermes Agent includes a full browser automation toolset with multiple backend options: - **Browser Use cloud mode** via [Browser Use](https://browser-use.com) for managed Chromium with stealth, residential proxies, CAPTCHA solving, and reusable browser profiles - **Browserbase cloud mode** via [Browserbase](https://browserbase.com) as an alternative cloud browser provider with anti-bot tooling - **Browser Use mode** via the [Browser Use CLI 3.0](https://github.com/browser-use/browser-use), the default browser driver for local Chrome and Browser Use cloud browsers - **Firecrawl cloud mode** via [Firecrawl](https://firecrawl.dev) for cloud browsers with built-in scraping […]

---

## v2-086 · no_answer
**Question :** What is the maximum number of cron jobs a single profile may schedule?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/cron-internals.md` — **Cron Internals**

  > # Cron Internals The cron subsystem provides scheduled task execution — from simple one-shot delays to recurring cron-expression jobs with skill injection and cross-platform delivery. ## Key Files | File | Purpose | |------|---------| | `cron/jobs.py` | Job model, storage, atomic read/write to `jobs.json` | | `cron/scheduler.py` | Scheduler loop — due-job detection, execution, repeat tracking | | `tools/cronjob_tools.py` | Model-facing `cronjob` tool registration and handler | | `gateway/run.py` | Gateway integration — cron ticking in the long-running loop | | `hermes_cli/cron.py` | CLI `hermes cron` subcommands | ## Scheduling Model Four schedule formats are supported: | Format | Example | […]

---

## v2-087 · no_answer
**Question :** What is the default speaking rate, in words per minute, of the synthesized voice?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/tts.md` — **Voice & TTS**

  > # Voice & TTS Hermes Agent supports both text-to-speech output and voice message transcription across all messaging platforms. :::tip Nous Subscribers If you have a paid [Nous Portal](https://portal.nousresearch.com) subscription, OpenAI TTS is available through the **[Tool Gateway](tool-gateway.md)** without a separate OpenAI API key. New installs can run `hermes setup --portal` to log in and turn on every gateway tool at once; existing installs can pick **Nous Subscription** for just TTS via `hermes model` or `hermes tools`. ::: ## Text-to-Speech Convert text to speech with eleven providers: | Provider | Quality | Cost | API Key | |----------|---------|------|---------| | **Edge TTS** […]

---

## v2-088 · no_answer
**Question :** Which TCP port does the gateway listen on by default?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/gateway-internals.md` — **Gateway Internals**

  > # Gateway Internals The messaging gateway is the long-running process that connects Hermes to 20+ external messaging platforms through a unified architecture. ## Key Files | File | Purpose | |------|---------| | `gateway/run.py` | `GatewayRunner` facade — composes the `gateway/run_*.py` sibling mixins (startup, adapters, inbound, turn, busy, goals, notifications, shutdown, …) and `gateway/slash_commands_*.py` handlers | | `gateway/session.py` | `SessionStore` — conversation persistence and session key construction | | `gateway/delivery.py` | Outbound message delivery to target platforms/channels | | `gateway/pairing.py` | DM pairing flow for user authorization | | […]

---

## v2-089 · no_answer
**Question :** What does the HERMES_MAX_TURNS environment variable do, and what is its default value?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:reference/environment-variables.md` — **Environment Variables**

  > # Environment Variables Reference Hermes reads environment variables from the process environment and, for user-managed secrets, from `~/.hermes/.env`. Keep API keys, bot tokens, OAuth secrets, and other credentials in `.env`; prefer `config.yaml` for non-secret behaviour settings when a config key exists. Some variables below are process-only overrides or internal bridge variables and should not be committed to `.env` just because they are documented here. ## LLM Providers | Variable | Description | |----------|-------------| | `OPENROUTER_API_KEY` | OpenRouter API key (recommended for flexibility) | | `OPENROUTER_BASE_URL` | Override the OpenRouter-compatible base URL | | […]

---

## v2-090 · no_answer
**Question :** At most how many external tool-protocol servers can be connected to a single agent at once?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/mcp.md` — **MCP (Model Context Protocol)**

  > # MCP (Model Context Protocol) MCP lets Hermes Agent connect to external tool servers so the agent can use tools that live outside Hermes itself — GitHub, databases, file systems, browser stacks, internal APIs, and more. If you have ever wanted Hermes to use a tool that already exists somewhere else, MCP is usually the cleanest way to do it. :::tip Coming from Claude Code? The `mcpServers` block in your `~/.claude.json` maps to `mcp_servers` in Hermes' `config.yaml` — and `hermes import-agent claude-code` migrates it (along with skills and instructions) automatically. See [Import from Other Agents](../import-from-other-agents.md). ::: ## What MCP gives you - Access to external tool […]

---

## v2-091 · no_answer
**Question :** After how long is an inactive session automatically purged by default?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/session-storage.md` — **(sans titre)**

  > # Session Storage Hermes Agent uses a SQLite database (`~/.hermes/state.db`) to persist session metadata, full message history, and model configuration across CLI and gateway sessions. This replaces the earlier per-session JSONL file approach. Source files: `hermes_state.py` (facade) plus the `hermes_state_*.py` siblings (schema, fts, search, compression, portability, gateway, ...) ## Hermes home and profile isolation `get_hermes_home()` is the authoritative filesystem resolver for state and configuration. It uses a context-local override first, then the `HERMES_HOME` environment variable, and finally the platform default (`~/.hermes` on macOS and Linux; `%LOCALAPPDATA%/hermes` on Windows). […]

---

## v2-092 · no_answer
**Question :** What is the minimum amount of RAM required to install and run Hermes?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:getting-started/installation.md` — **Installation**

  > # Installation Get Hermes Agent up and running in under two minutes! :::tip Platform Support For the full platform support matrix (which OSes, distribution methods, and platform-gated features are supported), see **[Platform Support](./platform-support.md)**. ::: ## Quick Install ### With the Hermes Desktop installer on macOS or Windows (recommended) To easily install the command-line and desktop applications, [download the Hermes Desktop installer](https://hermes-agent.nousresearch.com/) from our website and run it. :::note The macOS installer is **Apple Silicon only**. macOS on x86 (Intel) processors is [not a supported platform](./platform-support.md#unsupported). ::: ### Without Hermes […]

---

## v2-093 · no_answer
**Question :** How many extra tokens does each subagent consume on top of the main agent?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/delegation.md` — **Subagent Delegation**

  > # Subagent Delegation The `delegate_task` tool spawns child AIAgent instances with isolated context, inherited tool access, and their own terminal sessions. Each child gets a fresh conversation and works independently — only its final summary enters the parent's context. Top-level model calls run in the background automatically. Hermes returns a handle immediately so the conversation can continue, then posts the result back as a new message. An orchestrator subagent waits for its own workers so it can synthesize their results before returning. ## Completion delivery Messaging gateways acknowledge background completions only after their adapter actually schedules the event or inserts it into […]

---

## v2-094 · no_answer
**Question :** What first-audio-byte latency does the streaming voice output guarantee?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/streaming-tts.md` — **Streaming TTS Internals**

  > # Streaming TTS Hermes can stream TTS audio as it arrives from the provider, instead of waiting for the full audio before playing. This is used by voice mode (CLI/TUI live conversation), the dashboard speak-stream WebSocket, and — via the gateway `StreamingTTSConsumer` — any platform adapter that opts into streaming audio. Voice replies start speaking after the first clause instead of after full generation + synthesis. ## Architecture The streaming pipeline has four parts: 1. **Producer** — the LLM emits text deltas as it generates a response 2. **Sentence chunker** — `tools.tts_streaming.SentenceChunker` accumulates deltas, strips `<think>` blocks (even split across deltas), and flushes […]

---

## v2-095 · no_answer
**Question :** What is the maximum size of a single entry that a memory provider can store?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/memory-provider-plugin.md` — **Memory Provider Plugins**

  > # Building a Memory Provider Plugin Memory provider plugins give Hermes Agent persistent, cross-session knowledge beyond the built-in MEMORY.md and USER.md. This guide covers how to build one. :::tip Memory providers are one of two **provider plugin** types. The other is [Context Engine Plugins](./context-engine-plugin.md), which replace the built-in context compressor. Both follow the same pattern: single-select, config-driven, managed via `hermes plugins`. ::: ## Installation Layouts Hermes discovers memory providers from four sources, in this precedence order: | Source | Location | Notes | |---|---|---| | Bundled | `plugins/memory/<name>/` | Ships with Hermes. Closed to new providers — […]

---

## v2-096 · no_answer
**Question :** What default request timeout does Hermes apply to Bedrock API calls before giving up?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:guides/aws-bedrock.md` — **AWS Bedrock**

  > # AWS Bedrock Hermes Agent supports Amazon Bedrock as a native provider. This gives you full access to the Bedrock ecosystem: IAM authentication, Guardrails, cross-region inference profiles, and all foundation models. Hermes routes each model family through the API that serves it best: | Model family | API route | Why | |---|---|---| | Anthropic Claude | Anthropic SDK (`AnthropicBedrock`) | Prompt caching, thinking budgets, adaptive thinking — features not exposed via Converse | | OpenAI GPT-5.5 / GPT-5.6 (Sol, Terra, Luna) | Bedrock Mantle **OpenAI Responses** endpoint (`bedrock-mantle.<region>.api.aws/openai/v1`) | These models are Mantle-only — their model cards list […]

---

## v2-097 · no_answer
**Question :** Which domains are on the outbound proxy's default allow-list?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:developer-guide/egress-internals.md` — **Egress proxy internals**

  > # Egress proxy internals This page covers the architecture of the egress credential-injection firewall (`hermes egress` / iron-proxy) from a contributor / plugin author's perspective. End-user setup + usage docs live at [Egress proxy](../user-guide/egress/iron-proxy.md). The threat model and high-level design are summarised on the user page; this page is about *how* it's wired, where the security-relevant code lives, and what invariants you have to preserve if you touch it. ## Module layout ```text agent/proxy_sources/iron_proxy.py Core: binary install, CA gen, config build, subprocess lifecycle, mappings I/O, PID/nonce defense. Pure-function surface where possible. hermes_cli/proxy_cli.py […]

---

## v2-098 · no_answer
**Question :** Does the relay encrypt messages end-to-end, and if so with which algorithm?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/messaging/relay.md` — **Hermes Relay**

  > # Hermes Relay (Connector) :::warning Experimental Relay is **experimental**. The wire contract, auth scheme, and configuration may change without a deprecation cycle while the system is being validated. ::: Hermes Relay is not a chat platform itself — it is a **connector system** that lets your gateway front one or more real messaging platforms (Discord, Telegram, Slack, WhatsApp, …) **without holding any platform credentials**. A separate service, the *connector*, owns the platform bot tokens and sockets. Your gateway dials **out** to the connector over a single authenticated WebSocket, receives a capability descriptor at handshake, and then exchanges normalized message events (inbound) […]

---

## v2-099 · no_answer
**Question :** What is the maximum number of plugins that can be installed at once?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
- `hermes-agent:user-guide/features/plugins.md` — **Plugins**

  > # Plugins Hermes has a plugin system for adding custom tools, hooks, and integrations without modifying core code. If you want to create a custom tool for yourself, your team, or one project, this is usually the right path. The developer guide's [Adding Tools](../../developer-guide/adding-tools.md) page is for built-in Hermes core tools that live in `tools/` and `toolsets.py`. **→ [Build a Hermes Plugin](../../developer-guide/plugins/index.md)** — step-by-step guide with a complete working example. ## Quick overview Drop a directory into `~/.hermes/plugins/` with a `plugin.yaml` and Python code: ``` ~/.hermes/plugins/my-plugin/ ├── plugin.yaml # manifest ├── __init__.py # register() — wires […]

---

## v2-100 · no_answer
**Question :** What cable-tension setting do you recommend for adjusting a bike's rear derailleur?

**Document(s) pertinent(s) proposé(s) :**
- (aucun — cas `no_answer`, la bonne réponse attendue est l'abstention)

**Distracteur(s) proche(s) (ne répond PAS, à confirmer) :**
