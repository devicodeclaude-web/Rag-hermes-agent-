#!/usr/bin/env python3
"""Reconfirme les 10 frontières chunk_boundary avec ancres exactes + génère le fichier de preuves."""
import json, re, hashlib
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
    rx=re.compile(pat,re.I); return sorted({k for k,(so,eo) in enumerate(sp) if rx.search(content[so:eo])})
# (case, short, ancreA, labelA, ancreB, labelB)
F=[
 ("v3cb-082","messaging/telegram.md", r"\blong polling\b","défaut=long polling", r"getFile ceiling to 2GB|20MB getFile","Bot API local 20MB->2GB"),
 ("v3cb-083","features/api-server.md", r"Stateless — the full conversation","completions stateless", r"stored response chain|response_id","réponse stockée récupérable par id"),
 ("v3cb-084","features/kanban.md", r"hermes kanban create","créer une tâche", r"--max-retries","option --max-retries"),
 ("v3cb-085","features/lsp.md", r"idle_timeout","idle_timeout (arrêt serveur inactif)", r"wait_mode","wait_mode (attente diagnostics)"),
 ("v3cb-086","features/mcp.md", r"mcp_servers:","déclarer sous mcp_servers:", r"/reload-mcp","appliquer via /reload-mcp"),
 ("v3cb-087","messaging/whatsapp.md", r"scanning the QR code","scanner le QR code", r"pairing code","inconnu -> pairing code"),
 ("v3cb-088","features/voice-mode.md", r"local provider needs NO key","STT local sans clé", r"Barge-in|barge.?in","barge-in (interruption)"),
 ("v3cb-089","messaging/matrix.md", r"access_token` field","copier access_token", r"No `@mention` needed|@mention. needed","DM sans @mention par défaut"),
 ("v3cb-090","features/browser.md", r"isolates browser work per","session=<name> isole", r"saved vault credentials|vault credentials","identifiants vault réinjectés"),
 ("v3cb-091","features/goals.md", r"draft/show","brouillon /goal (draft/show)", r"20 continuation turns|goals.max_turns|Default is 20","budget défaut 20 tours"),
]
out=["# Preuves chunk_boundary — lot v3cb2 (chunker réel 384/64, step 320)",
     "tokenizer: /root/work/models/bge-reranker-v2-m3/tokenizer.json (XLM-RoBERTa, famille bge-m3)",""]
allok=True
for case,short,A,la,B,lb in F:
    did="hermes-agent:user-guide/"+short
    c=docs[did]; sp=spans(c); ca=cw(c,sp,A); cb=cw(c,sp,B); it=sorted(set(ca)&set(cb))
    ok = bool(ca and cb and not it); allok=allok and ok
    h=hashlib.sha256(c.encode()).hexdigest()[:16]
    out+=[f"## {case} — {did}",
          f"- chars={len(c)} | chunks={len(sp)} | sha256(content)[:16]={h} | params=384tok/overlap64/step320",
          f"- sous-fait A «{la}»: chunks {ca}",
          f"- sous-fait B «{lb}»: chunks {cb}",
          f"- intersection={it} -> {'VRAIE FRONTIERE (chunks disjoints)' if ok else 'ECHEC'}",""]
    print(f"{case} [{short}] A={ca} B={cb} inter={it} -> {'OK' if ok else 'ECHEC'}")
open("data/review/dataset-v3cb2-chunk-boundary-proofs.md","w").write("\n".join(out))
print("\nTOUT BON:",allok,"| preuves: data/review/dataset-v3cb2-chunk-boundary-proofs.md")
