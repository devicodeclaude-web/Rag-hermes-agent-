#!/usr/bin/env python3
"""Genere le dossier de revue HUMAINE INDEPENDANTE des 2 cas deficit-2.

Cas concernes : v3na-169 et v3na-170 (les seuls cas du dataset ou l'auteur ==
le relecteur initial ; ils exigent donc un second relecteur humain DISTINCT).

Produit, SANS verdict ni score (le relecteur decide seul) :
- data/review/deficit2-review-package.md : par cas, question, provenance,
  preuve d'absence (recherche corpus) et extrait de CHAQUE distracteur (piege).
- data/review/deficit2-review-grid.csv : grille vide pour l'evaluateur, qui
  DOIT etre distinct du redacteur. Les cas restent en l'etat jusqu'a sa decision.

Usage : PYTHONPATH=. /root/work/venv/bin/python scripts/build_deficit2_review_package.py
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/benchmark/dataset-v2.jsonl"
CORPUS = ROOT / "data/generated/hermes_public_documents.jsonl"
OUT_MD = ROOT / "data/review/deficit2-review-package.md"
OUT_CSV = ROOT / "data/review/deficit2-review-grid.csv"

TARGET_IDS = ["v3na-169", "v3na-170"]

_STOP = set("avec pour dans quel quelle quels quelles comment est les des une est-ce que qui quoi mon ma mes son sa ses the and".split())


def load_corpus() -> dict[str, str]:
    d: dict[str, str] = {}
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            r = json.loads(line)
            d[r["document_id"]] = r["content"]
    return d


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


# Preuve d'absence re-verifiee au corpus (revue agent-independante 2026-10-31).
NOANSWER_NOTE = {
    "v3na-169": (
        "Recherche corpus entier (FIFO / order / ordre / priorite / tie-break / "
        "simultane / 'same time' / 'one after another' / 'execution order' / "
        "max_parallel) sur les 6 docs cron + fixtures : AUCUNE regle d'ordre, de "
        "priorite ou de departage pour des jobs dus a la meme minute. cron-internals.md "
        "(Tick Cycle) itere les jobs dus sans ordre specifie ; cron.md ne definit que "
        "cron.max_parallel_jobs (plafond de concurrence) ; cron-troubleshooting.md "
        "confirme l'execution SEQUENTIELLE ('one after another') mais ne dit jamais "
        "lequel passe en premier. Fait absent et non derivable."
    ),
    "v3na-170": (
        "Recherche corpus entier (char / caractere / length / longueur / limit / max / "
        "1-64 / title / titre / description / card / carte) sur tous les docs kanban + "
        "fixtures : AUCUNE limite de longueur sur le titre ou le body d'une carte. Les "
        "seuls plafonds sont des attracteurs sur AUTRE chose : slug de board (1-64), "
        "troncature d'affichage (~3800), resume d'evenement (400). Les champs de carte "
        "sont 'title' / 'body', sans plafond de caracteres. Fait absent."
    ),
}


def main() -> int:
    docs = load_corpus()
    by_id = {}
    for l in DATASET.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            if r["case_id"] in TARGET_IDS:
                by_id[r["case_id"]] = r
    cases = [by_id[cid] for cid in TARGET_IDS if cid in by_id]
    missing = [cid for cid in TARGET_IDS if cid not in by_id]
    if missing:
        raise SystemExit(f"cas introuvables dans le dataset : {missing}")

    md = [
        "# Dossier de revue HUMAINE INDEPENDANTE — cas deficit-2 (2 cas)",
        "",
        "Ces deux cas `no_answer` ont ete REDIGES par devicodeclaude-web puis valides",
        "par lui-meme (auteur == relecteur initial). Une revue agent-independante les a",
        "confirmes, mais le critere complet exige un **relecteur HUMAIN distinct du",
        "redacteur**. Juge, pour chaque cas : (1) la question est-elle plausible et",
        "in-domain ? (2) le fait demande est-il reellement ABSENT du corpus (donc",
        "`no_answer` justifie) ? (3) les distracteurs sont-ils de vrais pieges qui ne",
        "repondent PAS ? Puis remplis la grille (validate / rewrite / reject). Aucune",
        "reponse attendue ni score n'est montre ici.",
        "",
    ]
    for c in cases:
        cid = c["case_id"]
        md.append(f"## {cid} — `{c['category']}`  (provenance : `{c.get('provenance_detail','?')}`)")
        md.append(f"**Question.** {c['question']}")
        md.append("")
        md.append("- Cible : *(aucune — no_answer ; `relevant_document_ids` doit rester vide)*")
        md.append(f"- **Preuve d'absence.** {NOANSWER_NOTE.get(cid,'(a completer)')}")
        for dd in (c.get("distractor_document_ids") or []):
            if dd in docs:
                md.append(
                    f"- Distracteur (piege) `{dd}` — extrait (ne doit PAS repondre a la question) :\n\n  > "
                    + best_window(docs[dd], c["question"]).replace("\n", "\n  > ")
                )
        md.append("")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "category", "provenance_detail", "reviewer_decision",
                    "reviewer_name", "review_date_utc", "notes"])
        w.writerow(["# relecteur DISTINCT du redacteur ; decision in validate|rewrite|reject", "", "", "", "", "", ""])
        for c in cases:
            w.writerow([c["case_id"], c["category"], c.get("provenance_detail", ""), "", "", "", ""])

    print(f"ecrit : {OUT_MD.relative_to(ROOT)} ({len(cases)} cas)")
    print(f"ecrit : {OUT_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
