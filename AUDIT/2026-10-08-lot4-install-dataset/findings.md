# Lot 4 — installation & dataset : état réel à HEAD (2026-10-08)

Objectif : satisfaire les conditions des lots historiques restés BLOQUÉS
(lot_1 install/lock, lot_3 historique dataset). Résultat : les deux conditions
sont gatées sur des étapes qu'un agent ne peut pas franchir seul. État vérifié
par exécution réelle cette session ; rien n'a été fabriqué.

## Condition A — installation / lock (`verify_lock_install.py`)

- Le script crée un venv, installe `requirements-gpu.lock.txt` puis
  `requirements-audit.lock.txt` en `--require-hashes`, et lance `run_ci_strict.py`.
- Le lock GPU embarque torch / FlagEmbedding / accelerate / datasets ; la preuve
  du **runtime CUDA** exige un GPU.
- Preuve historique : `AUDIT/preuves/lock-install.txt` (commit `ad1bc3c`, 2026-09-23,
  exit 1, Termux android arm64, py3.14) ; `LOT-STATUS.json` lot_1 = BLOQUÉ,
  « CUDA runtime remains unproved ».
- Cette session : NON exécuté. GPU payant requis ; aucun résultat ne peut être
  transposé d'un autre matériel (règle). → À AUTORISER explicitement.

## Condition B — dataset v1 (`validate_dataset_v1.py`)

Exécuté cette session à HEAD (`cc041e7`), stdlib pur, CPU :
- Structure VALIDE : 100 cas, catégories {simple 25, paraphrase 20,
  close_distractor 20, no_answer 20, chunk_boundary 15}, `acl_probes` 0,
  distracteurs `bm25_stdlib_not_bge_m3`. `dataset_sha256` =
  `2912de8ee4c20030440e89c6d9d140568ab105547dfe9676b5aca1b1aa58439d`.
- `decision_reference_status` : **100/100 `pending_human_validation`**.
- `human_validated_or_arbitrated` = 0 → **exit 2** (gate par conception).
- Matériel de revue prêt : `data/review/dataset-v1-initial-20.csv` (20 cas,
  colonnes `reviewer_decision`/`corrected_relevant_document_ids`/`reviewer_name`
  vides).

Exigences protocole (`docs/acceptance-criteria.md`, `<dataset>`) non satisfaites :
- contrôle manuel initial de 20 cas, puis validation/arbitrage humain des 100 ;
- ≥ 20 % des sorties revues par un humain ;
- « une session neuve ou un autre agent ne suffit pas à prouver l'indépendance ».

→ Je ne peux PAS basculer `pending_human_validation` → `validated` : ce serait
fabriquer une validation humaine, interdit par le protocole et le script.

## Ce qui reste (hors portée agent)

1. GPU : run d'installation du lock + preuve CUDA runtime + `run_ci_strict` sur
   la classe matérielle cible. Estimation grossière sur GPU loué (4090/A40) :
   ~15–30 min, << 1 $ ; garde-fous `pod_budget.py`/`pod_watchdog.py` déjà présents.
2. Humain : contrôle des 20 cas initiaux puis validation/arbitrage des 100
   (toi, ou un relecteur humain). Je peux préparer un paquet de revue enrichi
   (question + passages proposés + distracteurs en texte) pour faciliter, sans
   rien marquer comme validé.

## Rejouer la vérification CPU

```
PYTHONPATH=. python3 scripts/validate_dataset_v1.py   # exit 2 attendu tant que humain=0
```
