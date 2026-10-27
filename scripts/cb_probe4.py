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
 ("ni","user-guide/egress/network-isolation.md", r"network_mode: host", r"allowlist|iptables|DNS","host net vs allowlist/dns"),
 ("sp","user-guide/features/spotify.md", r"get_currently_playing|playback", r"SPOTIFY_CLIENT|OAuth|redirect uri","playback vs OAuth creds"),
 ("lo","user-guide/features/loops.md", r"/loop", r"loop_caps|max_iterations|max_web_searches","/loop vs loop_caps"),
 ("ts","user-guide/features/tool-search.md", r"tool_search", r"tool_describe|tool_call","tool_search vs describe/call"),
 ("pe","user-guide/features/personality.md", r"SOUL\.md", r"/personality|switch persona|preset","SOUL.md vs personality switch"),
 ("ca","user-guide/features/credential-vault.md", r"browser_vault_save|save.{0,10}login", r"bound to.{0,15}origin|origin.{0,10}match","vault save vs origin binding"),
 ("go2","user-guide/features/goals.md", r"draft/show|/goal draft", r"max_turns|20 continuation","goal draft vs max_turns"),
 ("ig2","user-guide/features/image-generation.md", r"aspect ratio|1024|resolution", r"\$0\.0001|per request|cost","resolution vs per-request cost"),
]
for cid, short, A, B, lab in CANDS:
    did="hermes-agent:"+short
    if did not in docs: print(f"{cid} [{short}] ABSENT"); continue
    c=docs[did]; sp=spans(c); ca=cw(c,sp,A); cb=cw(c,sp,B); it=ca&cb
    v="VRAIE FRONTIERE" if (ca and cb and not it) else ("A/B absent" if not(ca and cb) else "co-localise")
    print(f"{cid} [{short}] ch={len(sp)} A={sorted(ca)} B={sorted(cb)} inter={sorted(it)} -> {v} ({lab})")
