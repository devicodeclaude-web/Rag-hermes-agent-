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
 # secondes frontières sur longs docs déjà utilisés (paires NOUVELLES)
 ("slack2","user-guide/messaging/slack.md", r"app.?level token|xapp-", r"event subscription|Event Subscriptions|slash command"),
 ("tele2","user-guide/messaging/telegram.md", r"Webhook Mode|set a webhook", r"inline button|reply keyboard|parse_mode|MarkdownV2"),
 ("wd2","user-guide/features/web-dashboard.md", r"Analytics", r"real-?time (status|system)|Status page|live.{0,10}status"),
 ("kan2","user-guide/features/kanban.md", r"idempoten", r"model override|per-task model|--model"),
 ("mcp2","user-guide/features/mcp.md", r"stdio", r"streamable.?http|SSE transport|remote server"),
 ("disc2","user-guide/messaging/discord.md", r"Message Content Intent", r"permission integer|permissions=\d"),
 ("brow2","user-guide/features/browser.md", r"CDP|connect over CDP|headed", r"captcha|Cloudflare|bot wall|blocked page"),
 ("cron2","user-guide/features/cron.md", r"HERMES_CRON_MAX_PARALLEL|max_parallel", r"HERMES_CRON_TIMEOUT|inactivity.{0,12}timeout"),
 ("vm2","user-guide/features/voice-mode.md", r"wake", r"half.?duplex|full.?duplex|push.?to.?talk"),
 ("del2","user-guide/features/delegation.md", r"oneshot_max_children", r"max_spawn_depth"),
 ("skills2","user-guide/features/skills.md", r"hermes skills install", r"curator|archiv|usage tracking"),
 ("cu2","user-guide/features/computer-use.md", r"background", r"1568|screenshot.{0,15}token|~30K tokens"),
 ("plug2","user-guide/features/plugins.md", r"plugin\.yaml|manifest", r"pre_tool_call|post_tool_call|register_hook"),
 ("cfg2","user-guide/configuration.md", r"compression:", r"tool_output:|max_bytes"),
]
for cid,short,A,B in C:
    did="hermes-agent:"+short
    if did not in docs: print(f"{cid} ABSENT"); continue
    c=docs[did]; sp=spans(c); a=cw(c,sp,A); b=cw(c,sp,B); it=sorted(set(a)&set(b))
    v="FRONTIERE" if (a and b and not it) else ("A/B absent" if not(a and b) else "co-loc")
    print(f"{cid:9} ch={len(sp):3} A={a[:6]} B={b[:6]} inter={it} -> {v}")
