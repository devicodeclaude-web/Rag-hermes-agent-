#!/usr/bin/env python3
import json, re
from tokenizers import Tokenizer
TOK = Tokenizer.from_file("/root/work/models/bge-reranker-v2-m3/tokenizer.json")
docs = {json.loads(l)["document_id"]: json.loads(l)["content"]
        for l in open("data/generated/hermes_public_documents.jsonl") if l.strip()}
def spans(content, max_tok=384, step=320):
    offs = TOK.encode(content).offsets; n=len(offs); out=[]; i=0
    while i < n:
        w=offs[i:i+max_tok]; out.append((w[0][0], w[-1][1]))
        if i+max_tok>=n: break
        i+=step
    return out
def cw(content, sp, pat):
    rx=re.compile(pat,re.I); return {k for k,(so,eo) in enumerate(sp) if rx.search(content[so:eo])}
CANDS=[
 ("dc","user-guide/messaging/discord.md", r"Message Content Intent", r"slash command|command sync|COMMAND_SYNC","MCI vs slash-command sync"),
 ("sk","user-guide/features/skills.md", r"progressive disclosure", r"first 57|self-contained trigger|description.{0,15}trigger","prog-disclosure vs 57-char trigger"),
 ("kb","user-guide/features/kanban.md", r"kanban create|create a card", r"worker lane|--max-retries","create card vs worker lane/retries"),
 ("dg","user-guide/features/delegation.md", r"delegate_task\(", r"max_spawn_depth","delegate_task vs max_spawn_depth"),
 ("cf","user-guide/configuration.md", r"compression:", r"tool_output:|max_bytes","compression vs tool_output cap"),
 ("cc","user-guide/features/context-compression-and-caching.md", r"threshold.{0,12}0\.50", r"tail_mode|target_ratio","threshold vs tail_mode"),
 ("vi","user-guide/features/vision.md", r"1568|wider than", r"embed_target_bytes|max_calls_per_image","1568 vs embed/max_calls"),
 ("ig","user-guide/features/image-generation.md", r"image_gen\.provider", r"max_parallel_requests","provider select vs max_parallel"),
 ("ls","user-guide/features/lsp.md", r"idle_timeout|lazy", r"wait_mode","idle/lazy vs wait_mode"),
 ("ww","user-guide/features/wake-word.md", r"confirmation_frames", r"custom.{0,12}(onnx|keyword)|openWakeWord","confirmation_frames vs custom model"),
 ("se","user-guide/features/sessions.md", r"--resume|\-c `", r"breadcrumb|30 days","resume vs breadcrumb 30d"),
 ("me","user-guide/features/memory.md", r"2,200", r"does not auto-compact|consolidat","2200 budget vs no auto-compact"),
 ("cp","user-guide/features/credential-pools.md", r"round.?robin|rotation", r"cooldown|rate limit recovery","rotation vs cooldown"),
 ("fp","user-guide/features/fallback-providers.md", r"fallback", r"circuit breaker|api_max_retries","fallback vs circuit breaker"),
 ("wd","user-guide/features/web-dashboard.md", r"API key", r"PTY|embedded terminal","api keys vs PTY terminal"),
 ("tt","user-guide/features/tts.md", r"piper.download_voices|piper-voices", r"KittenTTS","piper download vs KittenTTS"),
]
for cid, short, A, B, lab in CANDS:
    did="hermes-agent:"+short
    if did not in docs: print(f"{cid} [{short}] ABSENT"); continue
    c=docs[did]; sp=spans(c); ca=cw(c,sp,A); cb=cw(c,sp,B); it=ca&cb
    v="VRAIE FRONTIERE" if (ca and cb and not it) else ("A/B absent" if not(ca and cb) else "co-localise")
    print(f"{cid} [{short}] ch={len(sp)} A={sorted(ca)} B={sorted(cb)} inter={sorted(it)} -> {v} ({lab})")
