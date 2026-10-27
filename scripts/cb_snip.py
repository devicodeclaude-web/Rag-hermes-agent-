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
def snip(content, sp, pat, k):
    rx=re.compile(pat,re.I)
    for ch in k:
        so,eo=sp[ch]; m=rx.search(content[so:eo])
        if m:
            s=max(so,so+m.start()-90); e=min(eo,so+m.end()+90)
            return f"ch{ch}: …{content[s:e].strip()}…"
    return "??"
FIN=[
 ("telegram","user-guide/messaging/telegram.md", r"long polling",[10,11], r"getFile.{0,20}(2\s?GB|2048)|20MB.{0,15}2\s?GB",[16,17,19]),
 ("api-server","user-guide/features/api-server.md", r"stateless",[1], r"retriev\w*.{0,25}\bid\b|stored response",[8,9,36]),
 ("kanban","user-guide/features/kanban.md", r"kanban create|create a card",[17,18], r"worker lane|--max-retries",[66,69,70]),
 ("lsp","user-guide/features/lsp.md", r"idle_timeout|lazy",[9,11], r"wait_mode",[7]),
 ("mcp","user-guide/features/mcp.md", r"mcp_servers:",[0,1], r"/reload-mcp|reload-mcp",[3,4,30,31,32]),
 ("whatsapp","user-guide/messaging/whatsapp.md", r"QR code",[1,2], r"pairing code",[4,12]),
 ("voice-mode","user-guide/features/voice-mode.md", r"speech-to-text|STT provider",[3,8], r"barge.?in",[11,12]),
 ("matrix","user-guide/messaging/matrix.md", r"access_token|ACCESS_TOKEN",[8,9], r"spaces|reactions|threads",[0,1,2,3]),
 ("browser","user-guide/features/browser.md", r"isolates browser work per",[5], r"vault|browser_vault|saved login",[13,14]),
 ("computer-use","user-guide/features/computer-use.md", r"1568",[16], r"double.?click|key combo|type text|scroll",[0,8,14,15,25]),
]
for name,short,A,ka,B,kb in FIN:
    c=docs["hermes-agent:"+short]; sp=spans(c)
    print(f"\n=== {name} ===")
    print("  A:",snip(c,sp,A,ka))
    print("  B:",snip(c,sp,B,kb))
