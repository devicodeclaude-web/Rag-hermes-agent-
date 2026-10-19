# Revue humaine du dataset v1 — VERDICT : rejeté pour réécriture

Statut : **rejected** (le jeu v1 ne peut pas servir de banc décisionnel).
Catégories conservées, questions à refaire.

## Défaut central : fuite de titre (title-leak)

Les 100 questions sont produites par 5 templates qui injectent le **titre du
document cible mot pour mot** dans la question. On mesure donc un match lexical
de titre, pas du retrieval sémantique. BGE-M3 + reranker gagnent trivialement ;
la vraie cible (un utilisateur qui ne connaît pas le titre exact) n'est pas testée.

Mesure objective (garde automatique) :

```bash
PYTHONPATH=. python3 scripts/check_title_leak.py --report-only
```

→ **61 fuites sur 80 cas répondables** (les 20 `no_answer` n'ont pas de cible).
Le titre du doc-cible apparaît tel quel dans la question.

## Diagnostic par catégorie

- `simple` (25) : toutes identiques, méta + title-leak. « What does section X
  explain » n'est pas une question d'utilisateur. Pouvoir discriminant nul.
- `paraphrase` (20) : le « in different words » porte sur la réponse, pas sur la
  requête ; le titre reste dans la question → aucune reformulation côté retrieval.
- `close_distractor` (20) : bonne intention (désambiguïser deux docs voisins)
  mais le titre dans la requête supprime toute confusion à tester.
- `chunk_boundary` (15) : bonne catégorie, mauvaise exécution — on demande le
  *nom* de la section (déjà dans la question) au lieu d'un *fait* à cheval entre
  deux chunks.
- `no_answer` (20) : bon ratio (20 %), mais les 20 réutilisent la même absurdité
  hors-domaine (« lunar calibration / telescope »). Ça ne teste pas le vrai
  risque : halluciner une réponse *plausible et in-domaine mais absente*.

## Corrections exigées

1. Garder les 5 catégories, jeter les 5 templates.
2. S'interdire le titre du doc-cible dans la requête → garde
   `scripts/check_title_leak.py` (0 fuite obligatoire avant commit).
3. Diversité : longueurs variées, vocabulaire utilisateur ≠ vocabulaire du doc
   (synonymes, acronymes), 5–10 questions multi-hop (réponse dans 2+ docs).
4. Scinder `no_answer` : ~5 hors-domaine, ~15 plausibles-mais-absentes.

### Exemples (mêmes docs, sans le titre)

- `simple` → « Comment ajouter le support first-class d'un nouveau provider LLM
  dans Hermes ? » → doit retrouver `adding-providers.md` sans le nommer.
- `close_distractor` → « Où Hermes décide-t-il quelles credentials et quel
  catalogue de modèles utiliser à l'exécution ? » → vise
  `provider-runtime.md` (Provider Runtime Resolution), **pas** `adding-providers.md`.
- `chunk_boundary` → « Qu'est-ce qui limite le nombre de subagents en parallèle
  dans la délégation Hermes ? » → réponse dans la partie implémentation
  (`delegation-patterns.md`), force un chunk non-initial.
- `no_answer` plausible → « Quel est le timeout de retry par défaut de
  l'adaptateur Telegram ? » (si non documenté) → teste abstention vs hallucination.

## Suite

Gabarit de réécriture : `data/review/dataset-v2-authoring-template.csv`
(20 slots, 4 par catégorie, cibles réelles, champ `question` à remplir).
Mode d'indépendance : les questions doivent être rédigées par un humain
(un agent ne prouve pas l'indépendance). La porte `check_title_leak.py` doit
passer à 0 fuite avant d'intégrer v2.
