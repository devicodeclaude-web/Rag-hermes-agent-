# Preuves chunk_boundary — lot v3cb2 (chunker réel 384/64, step 320)
tokenizer: /root/work/models/bge-reranker-v2-m3/tokenizer.json (XLM-RoBERTa, famille bge-m3)

## v3cb-082 — hermes-agent:user-guide/messaging/telegram.md
- chars=72675 | chunks=66 | sha256(content)[:16]=fbc37aaa4de3e614 | params=384tok/overlap64/step320
- sous-fait A «défaut=long polling»: chunks [10, 11]
- sous-fait B «Bot API local 20MB->2GB»: chunks [16, 17]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-083 — hermes-agent:user-guide/features/api-server.md
- chars=39481 | chunks=38 | sha256(content)[:16]=0a6d52fcc9d73ef1 | params=384tok/overlap64/step320
- sous-fait A «completions stateless»: chunks [1]
- sous-fait B «réponse stockée récupérable par id»: chunks [6, 7, 8, 17, 18, 21, 22, 36]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-084 — hermes-agent:user-guide/features/kanban.md
- chars=119600 | chunks=111 | sha256(content)[:16]=c65359b44d17ed80 | params=384tok/overlap64/step320
- sous-fait A «créer une tâche»: chunks [17, 18, 19, 21, 38, 39, 42, 43, 65, 72, 80, 85, 87]
- sous-fait B «option --max-retries»: chunks [66, 69, 70]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-085 — hermes-agent:user-guide/features/lsp.md
- chars=16491 | chunks=16 | sha256(content)[:16]=c25e1cee6e4748e2 | params=384tok/overlap64/step320
- sous-fait A «idle_timeout (arrêt serveur inactif)»: chunks [9, 12, 13]
- sous-fait B «wait_mode (attente diagnostics)»: chunks [7]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-086 — hermes-agent:user-guide/features/mcp.md
- chars=46427 | chunks=43 | sha256(content)[:16]=6b6afbedb4ddae58 | params=384tok/overlap64/step320
- sous-fait A «déclarer sous mcp_servers:»: chunks [0, 1, 8, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 23, 24, 27, 28, 29, 33, 35, 36, 37, 38]
- sous-fait B «appliquer via /reload-mcp»: chunks [3, 4, 9, 30, 31, 32]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-087 — hermes-agent:user-guide/messaging/whatsapp.md
- chars=15053 | chunks=14 | sha256(content)[:16]=0ba095585ab12066 | params=384tok/overlap64/step320
- sous-fait A «scanner le QR code»: chunks [1]
- sous-fait B «inconnu -> pairing code»: chunks [4, 12]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-088 — hermes-agent:user-guide/features/voice-mode.md
- chars=28706 | chunks=27 | sha256(content)[:16]=04addd63f68f9ef9 | params=384tok/overlap64/step320
- sous-fait A «STT local sans clé»: chunks [3, 18]
- sous-fait B «barge-in (interruption)»: chunks [11, 12]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-089 — hermes-agent:user-guide/messaging/matrix.md
- chars=38149 | chunks=36 | sha256(content)[:16]=26eaf30e8c790d29 | params=384tok/overlap64/step320
- sous-fait A «copier access_token»: chunks [8, 9]
- sous-fait B «DM sans @mention par défaut»: chunks [0]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-090 — hermes-agent:user-guide/features/browser.md
- chars=51046 | chunks=46 | sha256(content)[:16]=183162738b0ac845 | params=384tok/overlap64/step320
- sous-fait A «session=<name> isole»: chunks [5]
- sous-fait B «identifiants vault réinjectés»: chunks [13]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)

## v3cb-091 — hermes-agent:user-guide/features/goals.md
- chars=21828 | chunks=20 | sha256(content)[:16]=a9e7dbeb08df28cf | params=384tok/overlap64/step320
- sous-fait A «brouillon /goal (draft/show)»: chunks [4]
- sous-fait B «budget défaut 20 tours»: chunks [14, 15]
- intersection=[] -> VRAIE FRONTIERE (chunks disjoints)
