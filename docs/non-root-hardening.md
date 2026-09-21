# Durcissement non-root dans le PRoot Termux — portée réelle et limite

## Ce qui est fait et prouvé

- Module `rag_hermes/local_hardening.py` (réutilise la politique anti-root de
  `pod_security.py`) : crée un utilisateur local non privilégié et exécute le
  workload sous cet utilisateur via `runuser`.
- Preuve d'exécution réelle : les 78 tests du harnais tournent sous
  `uid=10177(hermesrag)`, pas sous root. Le workload RAG **n'exige pas** de
  privilèges root.
- `scripts/run_local_non_root.py` provisionne l'utilisateur et lance une
  commande sous lui.

## Limite fondamentale de l'environnement (mesurée, non contournable ici)

⚠️ **Le PRoot Termux n'applique PAS l'isolation par UID au niveau du système de
fichiers.** Preuve reproductible :

```
printf 'secret-root-only\n' > /tmp/root_600_test
chmod 600 /tmp/root_600_test          # 600 root:root
runuser -u hermesrag -- bash -lc 'cat /tmp/root_600_test'
# => affiche "secret-root-only"  (un vrai Linux renverrait Permission denied)
```

Conséquence : passer `/root/.ssh`, `/root/.runpod`, `/root/.hermes` en `700` ne
suffit PAS à empêcher un process non-root du PRoot de les lire. Le mapping d'UID
de PRoot laisse le workload accéder au filesystem sous-jacent.

## Portée réelle du durcissement

- **Apporte** : défense en profondeur contre le code qui *vérifie* l'UID
  (refus d'exécution en root, `pod_security` sur le pod distant où l'isolation
  est réelle), et bonne hygiène (le workload ne tourne pas en root par défaut).
- **N'apporte PAS** dans ce PRoot : une barrière filesystem réelle entre
  hermesrag et /root. Les secrets doivent donc être traités comme accessibles à
  tout process du PRoot.

## Mitigation réelle recommandée

Puisque l'isolation FS n'est pas fiable dans le PRoot :
1. **Ne jamais laisser de secret persistant sur disque** dans le PRoot — clé API
   RunPod en variable d'environnement éphémère, révoquée après usage (déjà fait).
2. Les clés SSH privées : supprimées après usage (déjà fait).
3. Pour une isolation FS réelle, exécuter le harnais **sur le pod distant** (où
   `pod_security.build_non_root_bootstrap` s'applique sur un vrai noyau Linux),
   pas dans le PRoot Termux.
