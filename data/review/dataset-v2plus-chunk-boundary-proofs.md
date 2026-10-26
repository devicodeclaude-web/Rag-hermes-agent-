# Preuves chunk_boundary — lot v2+ (rejouées en revue indépendante)

Chunker réel du harnais : `chunk_document_tokens` (rag_hermes/ingestion.py),
fenêtres 384 tokens, pas de 320 (overlap 64). Tokenizer local
`bge-reranker-v2-m3` (même famille XLM-RoBERTa que BAAI/bge-m3 ; à reconfirmer
au smoke GPU avec le vrai tokenizer bge-m3). VRAIE FRONTIERE = aucun chunk
unique ne contient les deux sous-faits.

## v2p-029 — api-server.md
- doc_id : `hermes-agent:user-guide/features/api-server.md`
- chars : 39481 | chunks : 38
- sha256(content) : `0a6d52fcc9d73ef1c3945f48b35a2897384a45418ec335e5793da7f18c8fe7b0`
- params : MAXT=384, OV=64, STEP=320
- fait A — endpoint stateless : regex `Stateless` → @char 2010, chunk[1]
  (« Stateless — the full conversation is included in each request »)
- fait B — réponse stockée récupérable par id : regex `previously stored response by ID`
  → @char 8719, chunk[8] (« GET /v1/responses/{id} — Retrieve a previously stored response by ID »)
- chunks communs : {} → VRAIE FRONTIERE (rejoué 2026-10-26, devicodeclaude-web)

(030 et 032 à rejouer et consigner ici de la même façon lors de leur revue.)

## v2p-030 — sessions.md
- doc_id : `hermes-agent:user-guide/sessions.md`
- chars : 52542 | chunks : 47 | sha256 : `5c87b32e1906de9db15fcd2fd02a45ba0e5dd54fd81f5882754e41bfdef141d1` | 384/64/step320
- fait A — commande non destructive : `sessions optimize` → @char 2986, chunk[2]
- fait B — purge auto + rétention : `retention_days` → @char 47574, chunk[42] (default 90, auto_prune)
- chunks communs : {} → VRAIE FRONTIERE (rejoué 2026-10-26, devicodeclaude-web)

## v2p-032 — computer-use.md
- doc_id : `hermes-agent:user-guide/features/computer-use.md`
- chars : 29762 | chunks : 28 | sha256 : `5f3a0e5c22e272432bf2fed583c48ef0ab483c5b61031794efa2bcc11c8f3e12` | 384/64/step320
- fait A — pointer vers son binaire : `HERMES_CUA_DRIVER_CMD=/path/to/your` → @char 22056, chunk[19]
- fait B — reste sous contrôle, pas d'auto-réparation : `reports the incompatibility` → @char 2919, chunk[2]
- chunks communs : {} → VRAIE FRONTIERE (rejoué 2026-10-26, devicodeclaude-web)
