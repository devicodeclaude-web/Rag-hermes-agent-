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
 ("br","user-guide/features/browser.md", r"isolates browser work per", r"vault|browser_vault|saved login","session isolation vs vault logins"),
 ("mc2","user-guide/features/mcp.md", r"mcp_servers:", r"/reload-mcp|reload-mcp","mcp config vs /reload-mcp"),
 ("pl","user-guide/features/plugins.md", r"hermes plugins install", r"trust.{0,15}(gate|prompt)|first.{0,10}load.{0,10}approv","install vs trust gate"),
 ("go","user-guide/features/goals.md", r"/goal `?<?text", r"max_turns","usage /goal vs max_turns budget"),
 ("wa","user-guide/messaging/whatsapp.md", r"QR code", r"pairing code|link.{0,10}code","whatsapp QR vs pairing code"),
 ("vo","user-guide/features/voice-mode.md", r"speech-to-text|STT provider", r"barge.?in","STT setup vs barge-in"),
 ("em","user-guide/messaging/email.md", r"IMAP", r"thread|In-Reply-To|References header","email IMAP vs threading"),
 ("ht","user-guide/features/hooks.md", r"agent:start", r"timeout.{0,12}(hook|\d)|hook.{0,12}timeout","hooks event vs timeout"),
 ("mx","user-guide/messaging/matrix.md", r"access_token|ACCESS_TOKEN", r"spaces|reactions|threads","matrix token vs spaces/threads"),
 ("cx","user-guide/features/codex-app-server-runtime.md", r"enable.{0,15}codex|openai-codex", r"sandbox|approval|filesystem","codex enable vs sandbox/approval"),
 ("ba","user-guide/features/batch-processing.md", r"--batch_size", r"--resume|checkpoint","batch_size vs resume/checkpoint"),
 ("ds","user-guide/features/delegation.md", r"Gather Then Analyze|Multi-File Refactoring", r"max_concurrent_children","orchestration pattern vs concurrency cfg"),
]
for cid, short, A, B, lab in CANDS:
    did="hermes-agent:"+short
    if did not in docs: print(f"{cid} [{short}] ABSENT"); continue
    c=docs[did]; sp=spans(c); ca=cw(c,sp,A); cb=cw(c,sp,B); it=ca&cb
    v="VRAIE FRONTIERE" if (ca and cb and not it) else ("A/B absent" if not(ca and cb) else "co-localise")
    print(f"{cid} [{short}] ch={len(sp)} A={sorted(ca)} B={sorted(cb)} inter={sorted(it)} -> {v} ({lab})")
