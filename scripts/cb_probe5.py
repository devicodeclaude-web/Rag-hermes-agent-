#!/usr/bin/env python3
import json, re
from tokenizers import Tokenizer
TOK = Tokenizer.from_file("/root/work/models/bge-reranker-v2-m3/tokenizer.json")
docs = {json.loads(l)["document_id"]: json.loads(l)["content"]
        for l in open("data/generated/hermes_public_documents.jsonl") if l.strip()}
def spans(c, mt=384, st=320):
    o=TOK.encode(c).offsets; n=len(o); out=[]; i=0
    while i<n:
        w=o[i:i+mt]; out.append((w[0][0],w[-1][1]))
        if i+mt>=n: break
        i+=st
    return out
def cw(c,sp,p):
    rx=re.compile(p,re.I); return sorted({k for k,(s,e) in enumerate(sp) if rx.search(c[s:e])})
C=[
 ("tts","user-guide/features/tts.md", r"piper.download_voices|download the model", r"stream.{0,10}audio|first.?audio|chunk.{0,10}sentence"),
 ("hooks","user-guide/features/hooks.md", r"agent:start", r"blocking.{0,10}hook|hook.{0,10}(timeout|blocking)|async hook"),
 ("plugins","user-guide/features/plugins.md", r"hermes plugins install", r"plugin\.yaml|manifest|entry_?point"),
 ("skills","user-guide/features/skills.md", r"/skill ", r"SKILL\.md|frontmatter|description.{0,15}57"),
 ("memprov","user-guide/features/memory-providers.md", r"Honcho", r"retain_user_prefix|auto-retain|retain_assistant"),
 ("curator","user-guide/features/curator.md", r"stale_after_days", r"archive_after_days|spawns? a.{0,10}review"),
 ("persona","user-guide/features/personality.md", r"SOUL\.md", r"/personality|switch.{0,10}persona|skin"),
 ("codex","user-guide/features/codex-app-server-runtime.md", r"enable.{0,15}codex|openai-codex", r"sandbox|approval policy|filesystem access"),
 ("azure","guides/azure-foundry.md", r"/v1/chat/completions|openai\.azure\.com", r"api-version|deployment name"),
 ("feishu","user-guide/messaging/feishu.md", r"App ID|FEISHU_APP_ID", r"Encrypt Key|FEISHU_ENCRYPT|Verification Token"),
 ("dingtalk","user-guide/messaging/dingtalk.md", r"Stream Mode", r"AppKey|Client ID"),
 ("teams","user-guide/messaging/teams.md", r"Bot Framework|Azure Bot", r"3978|BOT_PORT|tunnel"),
 ("email","user-guide/messaging/email.md", r"IMAP", r"EMAIL_POLL_INTERVAL|poll interval"),
 ("whatsappc","user-guide/messaging/whatsapp-cloud.md", r"Verify Token|verification", r"24.hour|template|customer service window"),
 ("webdash","user-guide/features/web-dashboard.md", r"API [Kk]ey", r"PTY|embedded terminal"),
 ("websearch","user-guide/features/web-search.md", r"EXA_API_KEY|Brave|Tavily", r"scrape|extract|read the page|full text"),
 ("imagegen","user-guide/features/image-generation.md", r"image_gen\.provider", r"\$0\.0001|per request|cost"),
 ("sessions","user-guide/features/sessions.md", r"--resume|hermes sessions", r"breadcrumb|30 days|prune"),
 ("ccache","developer-guide/context-compression-and-caching.md", r"threshold.{0,12}0\.50", r"tail_mode|target_ratio"),
 ("botmode","user-guide/bot-mode.md", r"roster|named bots?", r"deliberate|group chat|message each other"),
 ("fallback","user-guide/features/fallback-providers.md", r"fallback", r"cooldown|unhealthy|health check|retry"),
 ("nix","getting-started/nix-setup.md", r"flake", r"home-manager|NixOS module"),
]
for cid,short,A,B in C:
    did="hermes-agent:"+short
    if did not in docs: print(f"{cid} ABSENT"); continue
    c=docs[did]; sp=spans(c); a=cw(c,sp,A); b=cw(c,sp,B); it=sorted(set(a)&set(b))
    v="FRONTIERE" if (a and b and not it) else ("A/B absent" if not(a and b) else "co-loc")
    print(f"{cid:10} ch={len(sp):3} A={a[:6]} B={b[:6]} inter={it} -> {v}")
