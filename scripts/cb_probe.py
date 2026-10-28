#!/usr/bin/env python3
"""Sonde chunk_boundary: reproduit le chunker réel (384 tokens, overlap 64, step 320)
avec le tokenizer local bge-reranker-v2-m3, et teste des (doc, ancreA, ancreB):
vraie frontière = aucun chunk unique ne contient A ET B.
Lancer: /root/work/venv/bin/python scripts/cb_probe.py
"""
import json, re
from tokenizers import Tokenizer

TOK = Tokenizer.from_file("/root/work/models/bge-reranker-v2-m3/tokenizer.json")
CORPUS = "data/generated/hermes_public_documents.jsonl"
docs = {json.loads(l)["document_id"]: json.loads(l)["content"]
        for l in open(CORPUS) if l.strip()}

def spans(content, max_tok=384, step=320):
    enc = TOK.encode(content)
    offs = enc.offsets  # (char_start, char_end) per token
    n = len(offs)
    out = []
    i = 0
    while i < n:
        window = offs[i:i+max_tok]
        so = window[0][0]
        eo = window[-1][1]
        out.append((so, eo))
        if i + max_tok >= n:
            break
        i += step
    return out

def chunks_with(content, sp, pat):
    rx = re.compile(pat, re.I)
    idx = set()
    for k, (so, eo) in enumerate(sp):
        if rx.search(content[so:eo]):
            idx.add(k)
    return idx

# (id, docshort, ancreA, ancreB, libellé)
CANDS = [
 ("t1","user-guide/messaging/telegram.md", r"long polling", r"getFile.{0,20}(2\s?GB|2048)|20MB.{0,15}2\s?GB", "long polling vs getFile 2GB"),
 ("a1","user-guide/features/api-server.md", r"stateless", r"retriev\w*.{0,25}\bid\b|stored response", "stateless vs retrieve by id"),
 ("b1","user-guide/features/browser.md", r"session=<name>|isolates browser work", r"real.?profile|your own logins|real_profile", "session isolation vs real-profile"),
 ("m1","user-guide/messaging/matrix.md", r"mautrix", r"end-to-end|E2EE|device verification|encrypted room", "mautrix SDK vs E2E encryption"),
 ("g1","user-guide/features/goals.md", r"max_turns|20 continuation turns", r"unachievable|blocked.{0,15}verdict|judge.{0,15}(pause|blocked)", "turn budget vs judge unachievable"),
 ("mc1","user-guide/features/mcp.md", r"run sequentially|one at a time", r"parallel_tool_calls|Parallel Tool Calls", "sequential default vs parallel tool calls"),
 ("p1","user-guide/features/plugins.md", r"hermes plugins install|pip install", r"pre_tool_call|post_tool_call", "install plugin vs hook names"),
 ("v1","user-guide/features/voice-mode.md", r"barge.?in|interrupt", r"push.?to.?talk|half.?duplex|full.?duplex", "barge-in vs duplex mode"),
 ("n1","getting-started/nix-setup.md", r"flake", r"home-manager|systemd (user )?service", "flake vs home-manager/systemd"),
 ("tt1","user-guide/features/tts.md", r"piper", r"streaming.{0,15}(tts|audio)|first.?audio", "piper vs streaming tts"),
 ("mp1","user-guide/multi-profile-gateways.md", r"HERMES_HOME|profile home", r"systemd|supervisor|process manager", "profile home vs systemd supervision"),
 ("cu1","user-guide/features/computer-use.md", r"1568", r"double.?click|key combo|type text|scroll", "1568 downscale vs action primitives"),
 ("mo1","user-guide/features/memory-providers.md", r"Honcho", r"messageMaxChars|25000", "Honcho vs messageMaxChars"),
 ("d1","developer-guide/trajectory-format.md", r"tool_call", r"usage|token count|replay", "tool_call record vs usage/replay"),
 ("w1","user-guide/features/web-search.md", r"EXA_API_KEY|Brave|Tavily", r"max_web_searches|per turn", "backends vs per-turn cap"),
 ("c1","user-guide/features/cron.md", r"HERMES_CRON_MAX_PARALLEL|max_parallel", r"inactivity.{0,15}timeout|HERMES_CRON_TIMEOUT", "cron parallel vs inactivity timeout"),
]
for cid, short, A, B, lab in CANDS:
    did = "hermes-agent:"+short
    if did not in docs:
        print(f"{cid} [{short}] DOC ABSENT"); continue
    c = docs[did]; sp = spans(c)
    ca = chunks_with(c, sp, A); cb = chunks_with(c, sp, B)
    inter = ca & cb
    verdict = "VRAIE FRONTIERE" if (ca and cb and not inter) else ("A ou B absent" if not (ca and cb) else "co-localise (simple)")
    print(f"{cid} [{short}] chunks={len(sp)} | A={sorted(ca)} B={sorted(cb)} inter={sorted(inter)} -> {verdict}  ({lab})")
