# Preuves chunk_boundary — lot final v3cb3 (chunker réel 384/64, step 320)
tokenizer: /root/work/models/bge-reranker-v2-m3/tokenizer.json

## v3cb-132 — hermes-agent:user-guide/features/hooks.md
- chars=108983 | chunks=111 | sha256(content)[:16]=4e111a48020bf2ca | params=384tok/overlap64/step320
- A «évènement agent:start»: chunks [1, 3, 4]
- B «hook bloquant (vs async)»: chunks [15, 38, 63, 97]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-133 — hermes-agent:user-guide/features/memory-providers.md
- chars=32853 | chunks=35 | sha256(content)[:16]=089c3affcf2b62eb | params=384tok/overlap64/step320
- A «1er provider = Honcho»: chunks [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 31, 32, 33]
- B «préfixes d'auto-rétention»: chunks [22, 23]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-134 — hermes-agent:user-guide/features/skills.md
- chars=53905 | chunks=49 | sha256(content)[:16]=9133289045bc3fff | params=384tok/overlap64/step320
- A «installer un skill»: chunks [29, 30, 32, 33, 35, 37, 38, 39, 44, 45]
- B «archivage par le curator»: chunks [8, 17, 19, 24, 25]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-135 — hermes-agent:user-guide/features/plugins.md
- chars=48073 | chunks=47 | sha256(content)[:16]=81557eb96ca1f267 | params=384tok/overlap64/step320
- A «manifeste plugin.yaml»: chunks [0, 1, 4, 24, 25, 28, 35]
- B «hooks enregistrables»: chunks [2, 3, 9, 10, 16, 17]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-136 — hermes-agent:user-guide/features/cron.md
- chars=73596 | chunks=66 | sha256(content)[:16]=609bd65b5d87e534 | params=384tok/overlap64/step320
- A «parallélisme cron»: chunks [9]
- B «timeout d'inactivité»: chunks [41, 42]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-137 — hermes-agent:user-guide/messaging/telegram.md
- chars=72675 | chunks=66 | sha256(content)[:16]=fbc37aaa4de3e614 | params=384tok/overlap64/step320
- A «mode webhook»: chunks [10, 11]
- B «parse_mode de formatage»: chunks [47, 48, 49]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-138 — hermes-agent:user-guide/features/web-dashboard.md
- chars=76034 | chunks=73 | sha256(content)[:16]=efe671f10c864077 | params=384tok/overlap64/step320
- A «page Analytics»: chunks [0, 15, 16, 29]
- B «page de statut temps réel»: chunks [23]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-139 — hermes-agent:user-guide/messaging/discord.md
- chars=59408 | chunks=53 | sha256(content)[:16]=56f420ee34d9b788 | params=384tok/overlap64/step320
- A «Message Content Intent»: chunks [6, 7, 47, 48]
- B «sync des slash-commands»: chunks [13]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-140 — hermes-agent:user-guide/features/fallback-providers.md
- chars=25032 | chunks=24 | sha256(content)[:16]=5364683071e586c2 | params=384tok/overlap64/step320
- A «chaîne de fallback»: chunks [11, 12, 15, 19, 21]
- B «cooldown provider défaillant»: chunks [10, 13]
- intersection=[] -> VRAIE FRONTIERE

## v3cb-141 — hermes-agent:user-guide/configuration.md
- chars=224573 | chunks=204 | sha256(content)[:16]=bf549752176383e3 | params=384tok/overlap64/step320
- A «seuil de compression auto»: chunks [56, 58, 70, 71, 72, 73, 100, 103, 104, 107, 108, 110, 111, 113]
- B «plafond d'octets de sortie d'outil»: chunks [13, 39, 51, 52, 53]
- intersection=[] -> VRAIE FRONTIERE

# Preuves chunk_boundary — complément lot final (chunker 384/64 step320)

## v3cb-142 — hermes-agent:user-guide/messaging/matrix.md
- chunks=36 sha16=26eaf30e8c790d29
- A «lib mautrix»: [0, 13, 18, 19, 23, 24, 32]
- B «features Matrix (spaces/reactions)»: [1, 2, 3, 5, 14, 15]
- inter=[] -> VRAIE FRONTIERE

## v3cb-143 — hermes-agent:user-guide/features/tts.md
- chunks=43 sha16=9c7127e1f43063b5
- A «Edge TTS par défaut»: [0, 1, 2, 9, 10, 11]
- B «téléchargement voix Piper»: [5, 12]
- inter=[] -> VRAIE FRONTIERE
