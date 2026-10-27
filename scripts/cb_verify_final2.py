#!/usr/bin/env python3
"""Verrouille les 10 frontières du lot final + génère preuves (hash+params+chunks)."""
import json, re, hashlib
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
F=[
 ("v3cb-132","user-guide/features/hooks.md", r"agent:start","évènement agent:start", r"blocking.{0,10}hook|hook.{0,10}(timeout|blocking)","hook bloquant (vs async)"),
 ("v3cb-133","user-guide/features/memory-providers.md", r"Honcho","1er provider = Honcho", r"retain_user_prefix|retain_assistant_prefix","préfixes d'auto-rétention"),
 ("v3cb-134","user-guide/features/skills.md", r"hermes skills install","installer un skill", r"curator|archiv","archivage par le curator"),
 ("v3cb-135","user-guide/features/plugins.md", r"plugin\.yaml|manifest","manifeste plugin.yaml", r"pre_tool_call|post_tool_call","hooks enregistrables"),
 ("v3cb-136","user-guide/features/cron.md", r"HERMES_CRON_MAX_PARALLEL|max_parallel_jobs","parallélisme cron", r"HERMES_CRON_TIMEOUT|inactivity.{0,12}timeout","timeout d'inactivité"),
 ("v3cb-137","user-guide/messaging/telegram.md", r"## Webhook Mode|set a webhook","mode webhook", r"MarkdownV2|parse_mode","parse_mode de formatage"),
 ("v3cb-138","user-guide/features/web-dashboard.md", r"Analytics","page Analytics", r"real-?time (status|system)|system status|live.{0,8}status","page de statut temps réel"),
 ("v3cb-139","user-guide/messaging/discord.md", r"Message Content Intent","Message Content Intent", r"command sync|COMMAND_SYNC|slash.?command.{0,10}sync","sync des slash-commands"),
 ("v3cb-140","user-guide/features/fallback-providers.md", r"fallback_models|fallback chain|fallback list","chaîne de fallback", r"cooldown|mark.{0,10}unhealthy|unhealthy","cooldown provider défaillant"),
 ("v3cb-141","user-guide/configuration.md", r"compression:","seuil de compression auto", r"tool_output:|max_bytes","plafond d'octets de sortie d'outil"),
]
out=["# Preuves chunk_boundary — lot final v3cb3 (chunker réel 384/64, step 320)",
     "tokenizer: /root/work/models/bge-reranker-v2-m3/tokenizer.json",""]
allok=True
for case,short,A,la,B,lb in F:
    did="hermes-agent:"+short; c=docs[did]; sp=spans(c); ca=cw(c,sp,A); cb=cw(c,sp,B); it=sorted(set(ca)&set(cb))
    ok=bool(ca and cb and not it); allok=allok and ok
    h=hashlib.sha256(c.encode()).hexdigest()[:16]
    out+=[f"## {case} — {did}",
          f"- chars={len(c)} | chunks={len(sp)} | sha256(content)[:16]={h} | params=384tok/overlap64/step320",
          f"- A «{la}»: chunks {ca}", f"- B «{lb}»: chunks {cb}",
          f"- intersection={it} -> {'VRAIE FRONTIERE' if ok else 'ECHEC'}",""]
    print(f"{case} [{short.split('/')[-1]}] A={ca[:5]} B={cb[:5]} inter={it} -> {'OK' if ok else 'ECHEC'}")
open("data/review/dataset-v3cb3-chunk-boundary-proofs.md","w").write("\n".join(out))
print("TOUT BON:",allok)
