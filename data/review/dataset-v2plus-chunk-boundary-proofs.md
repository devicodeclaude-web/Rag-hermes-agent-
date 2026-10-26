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
