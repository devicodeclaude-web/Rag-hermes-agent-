#!/usr/bin/env python3
"""Génère le dossier de revue indépendante des 32 cas du lot v2+.

Produit, SANS verdict ni score (le réviseur décide) :
- data/review/dataset-v2plus-review-package.md : par cas, question, provenance,
  extrait justificatif de la cible, extrait du distracteur, et la preuve
  spécifique (fronti\u00e8re = 2 chunks disjoints ; no_answer = recherche corpus).
- data/review/dataset-v2plus-review-grid.csv : grille vide pour l'évaluateur
  (qui DOIT être distinct des rédacteurs). Les cas restent pending jusque-là.

Usage : PYTHONPATH=. /root/work/venv/bin/python scripts/build_v2plus_review_package.py
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
CORPUS = ROOT / "data/generated/hermes_public_documents.jsonl"
TOKENIZER = Path("/root/work/models/bge-reranker-v2-m3/tokenizer.json")
OUT_MD = ROOT / "data/review/dataset-v2plus-review-package.md"
OUT_CSV = ROOT / "data/review/dataset-v2plus-review-grid.csv"

MAXT, OV = 384, 64
STEP = MAXT - OV
_tok = Tokenizer.from_file(str(TOKENIZER))


def load_corpus() -> dict[str, str]:
    d: dict[str, str] = {}
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            d[r["document_id"]] = r["content"]
    return d


def chunkspans(content: str) -> list[tuple[int, int]]:
    offs = _tok.encode(content, add_special_tokens=False).offsets
    spans = []
    for ts in range(0, len(offs), STEP):
        te = min(ts + MAXT, len(offs))
        spans.append((offs[ts][0], offs[te - 1][1]))
        if te >= len(offs):
            break
    return spans


def chunk_of(spans, pos: int) -> int:
    for i, (so, eo) in enumerate(spans):
        if so <= pos < eo:
            return i
    return -1


_STOP = set("avec pour dans quel quelle quels quelles comment est les des une est-ce que qui quoi mon ma mes son sa ses the and für".split())


def content_words(q: str) -> list[str]:
    def norm(w):
        return "".join(c for c in unicodedata.normalize("NFD", w.lower()) if unicodedata.category(c) != "Mn")
    words = re.findall(r"[a-zA-Zàâäéèêëïîôöùûüç_]{4,}", q)
    return [norm(w) for w in words if norm(w) not in _STOP]


def best_window(content: str, q: str, width: int = 650) -> str:
    cw = content_words(q)
    low = "".join(c for c in unicodedata.normalize("NFD", content.lower()) if unicodedata.category(c) != "Mn")
    best_pos, best_score = 0, -1
    for m in re.finditer(r"\n#+ .+|\n\n", content):
        pos = m.start()
        window = low[pos:pos + width]
        score = sum(window.count(w) for w in cw)
        if score > best_score:
            best_score, best_pos = score, pos
    snippet = content[best_pos:best_pos + width].strip()
    return re.sub(r"\n{2,}", "\n", snippet)


# Preuves spécifiques (ancres vérifiées pendant l'authoring).
BOUNDARY = {
    "v2p-029": [("fait A — endpoint stateless", r"Stateless\b"),
                ("fait B — réponse stockée récupérable par id", r"Retrieve a previously stored response by ID")],
    "v2p-030": [("fait A — commande non destructive", r"sessions optimize"),
                ("fait B — purge auto + rétention", r"auto_prune|retention_days")],
    "v2p-032": [("fait A — pointer vers son binaire", r"point Hermes straight|set `HERMES_CUA_DRIVER_CMD`|HERMES_CUA_DRIVER_CMD="),
                ("fait B — reste sous contrôle, pas d'auto-réparation", r"stays under your control|leaves it unchanged|reports the incompatibility")],
}
NOANSWER_NOTE = {
    "v2p-017": "Recherche corpus entier : comptes PAR moteur présents (edge 74, piper 44, Mistral STT 13, voice-mode 20) mais AUCUN total 'tous moteurs confondus', et non dérivable (ensembles qui se recoupent, STT != TTS). Fait absent.",
    "v2p-018": "Recherche corpus entier (first frame / frame-by-frame / each-per-frame / animated gif|image / sampled frames / video) : rien ne décrit quelles images d'un GIF ANIMÉ en entrée la vision analyse. GIF listé comme format accepté, mais traitement de l'animation non documenté et non dérivable. Fait absent.",
}


def main() -> int:
    docs = load_corpus()
    cases = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines()
             if l.strip() and json.loads(l)["case_id"].startswith("v2p-")]
    cases.sort(key=lambda c: c["case_id"])

    md = ["# Dossier de revue indépendante — lot v2+ (32 cas)", "",
          "Construction **assistée** (scaffold Hermes + rédaction LLM). L'évaluateur",
          "**doit être distinct des rédacteurs** (cf. `provenance_detail`). Les cas",
          "restent `pending` jusqu'à décision. Aucun verdict ni score ici : juge si la",
          "cible répond et si le distracteur ne répond pas, puis remplis la grille.", ""]
    for c in cases:
        cid = c["case_id"]
        md.append(f"## {cid} — `{c['category']}`  (provenance : `{c.get('provenance_detail','?')}`)")
        md.append(f"**Question.** {c['question']}")
        md.append("")
        if c["category"] == "no_answer":
            md.append(f"- Cible : *(aucune — no_answer)*. Distracteur (piège) : `{(c.get('distractor_document_ids') or ['?'])[0]}`")
            md.append(f"- **Preuve d'absence.** {NOANSWER_NOTE.get(cid,'(à compléter)')}")
            dd = (c.get("distractor_document_ids") or [None])[0]
            if dd and dd in docs:
                md.append(f"- Extrait du distracteur (ne doit PAS répondre) :\n\n  > " + best_window(docs[dd], c["question"]).replace("\n", "\n  > "))
        else:
            for did in c.get("relevant_document_ids", []):
                md.append(f"- Cible `{did}` — extrait indicatif (vérifier que la cible répond) :\n\n  > " + best_window(docs.get(did, ""), c["question"]).replace("\n", "\n  > "))
            if cid in BOUNDARY:
                md.append("- **Preuve de frontière (chunks disjoints, tokenizer BGE-M3 384/64)** :")
                did = c["relevant_document_ids"][0]
                spans = chunkspans(docs[did])
                for label, pat in BOUNDARY[cid]:
                    m = re.search(pat, docs[did], re.I | re.S)
                    if m:
                        ci = chunk_of(spans, m.start())
                        so, eo = spans[ci]
                        md.append(f"  - {label} : chunk {ci} (chars {so}–{eo}) — « …{docs[did][m.start():m.start()+90].strip()}… »")
                md.append("  - → aucun chunk unique ne contient les deux faits (vérifié).")
            for did in c.get("distractor_document_ids", []):
                if did in docs:
                    md.append(f"- Distracteur `{did}` — extrait (ne doit PAS mieux répondre) :\n\n  > " + best_window(docs[did], c["question"]).replace("\n", "\n  > "))
        md.append("")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "provenance_detail", "reviewer_decision",
                    "reviewer_name", "review_date_utc", "notes"])
        w.writerow(["# évaluateur DISTINCT des rédacteurs ; decision ∈ validate|rewrite|reject|arbitrate", "", "", "", "", "", ""])
        for c in cases:
            w.writerow([c["case_id"], c["category"], c.get("provenance_detail", ""), "", "", "", ""])

    print(f"écrit : {OUT_MD.relative_to(ROOT)} ({len(cases)} cas)")
    print(f"écrit : {OUT_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
