# Faisabilité d’une campagne BGE-M3 sur RunPod Serverless

Date de vérification : 2026-10-18

## Verdict

**PARTIAL — ne pas déployer en l’état.**

RunPod Serverless fournit des limites côté fournisseur (`executionTimeout`, TTL du
job et `workersMin=0`) qui répondent mieux au risque d’un Pod restant facturé.
Cependant, la campagne humaine de 154 cas n’a encore ni image Serverless, ni
handler, ni mesure de durée réelle. Le plafond financier de 0,50 USD n’est pas
compatible avec une fenêtre A40 de 30 minutes au tarif vérifié.

Aucun endpoint, worker, Pod ou autre ressource payante n’a été créé pendant cette
étude.

## Faits vérifiés

- `runpodctl 3.0.1` ne propose pas `pod create --terminate-after`.
- L’API/MCP de création de Pod inspectée ne fournit pas non plus d’expiration
  automatique du Pod.
- La porte 3 du runbook Pod reste donc fermée.
- RunPod Serverless expose :
  - `workersMin=0` ;
  - un timeout d’exécution ;
  - une politique TTL couvrant file d’attente et exécution ;
  - le retour automatique à zéro worker après inactivité.
- Tarif Serverless vérifié pour le groupe A40/A6000 48 Gio : 0,00034 USD/s.

## Budget

| Fenêtre facturable | Coût au tarif vérifié |
|---:|---:|
| 20 minutes | 0,4080 USD |
| 24 minutes | 0,4896 USD |
| 30 minutes | 0,6120 USD |

Le plafond théorique correspondant à 0,50 USD est d’environ 1 470,6 secondes,
soit 24 min 30 s. Ce calcul ne constitue pas un plafond monétaire fournisseur :
il faut encore tenir compte du chargement en VRAM, de l’arrêt du worker, d’un
éventuel changement de tarif et de toute nouvelle tentative. RunPod n’expose pas
de plafond monétaire par job.

## Éléments conservables

Une architecture Serverless queue-based pourrait conserver :

- le dataset humain de 154 cas ;
- le corpus et ses empreintes ;
- les verrous de modèles et leurs révisions Hugging Face ;
- le split déterministe calibration 81 / holdout 73 ;
- le checkout Git propre et la révision auditée ;
- le reçu autonome `gpu_execution_receipt.v2` ;
- les contrôles JSON, chemins, publication atomique et provenance existants.

## Architecture minimale à valider

1. Image `linux/amd64` fondée sur une image CUDA/PyTorch épinglée.
2. Checkout Git propre complet, `.git` inclus, sous `/opt/ragbench`.
3. Worker queue-based qui :
   - valide le commit attendu ;
   - lance `scripts/run_bge_gpu_campaign.py` ;
   - recharge le reçu avec `load_consumable_receipt_v2` ;
   - renvoie ce reçu comme résultat du job.
4. Endpoint avec un seul worker maximum, `workersMin=0`, idle minimal et limites
   fournisseur explicites.
5. Invocation asynchrone `/run`, polling borné jusqu’à un état terminal, puis
   persistance et validation immédiates du résultat avant suppression vérifiée de
   l’endpoint et du template.

## Blocages avant toute dépense

- Le lock d’environnement CUDA/PyTorch doit être régénéré et vérifié sur la cible
  Serverless ; le lock actuel n’est pas une preuve d’image reproductible.
- Les deux modèles verrouillés représentent environ 4,576 Go ; leur stratégie de
  cache doit être testée sans téléchargement ou duplication imprévue.
- La campagne complète n’a jamais été chronométrée ; rien ne prouve qu’elle tient
  dans une fenêtre prudente inférieure à 24 minutes.
- Le manifeste exige exactement une `NVIDIA A40` et au moins 40 Gio. Les pools
  Serverless peuvent aussi attribuer une A6000 ; le contrôle matériel doit rester
  fail-closed.
- L’image ne peut pas encore être construite localement : Docker, Podman et `uv`
  ne sont pas présents dans l’environnement actuel.
- Le résultat doit rester sous la limite de sortie de `/run` et être sauvegardé
  avant expiration de sa rétention.
- Aucun mécanisme ne garantit actuellement un plafond monétaire strict de
  0,50 USD pour cette campagne.

## Décision

Ne pas créer de template, endpoint, worker ou job Serverless tant que **tous** les
prérequis techniques cumulatifs suivants ne sont pas fermés et audités :

- image et handler reproductibles construits et testés sans GPU payant ;
- environnement CUDA/PyTorch verrouillé sur la cible ;
- cache des modèles, matériel exact, taille du résultat et récupération après
  polling validés ;
- durée de campagne suffisamment bornée par une preuve non payante ou par une
  expérience séparée disposant de sa propre autorisation de dépense ;
- nettoyage de l’endpoint et du template vérifiable et fail-closed.

Il faut ensuite choisir **et auditer** une solution budgétaire : réduire la fenêtre
d’exécution, relever le plafond, sélectionner un GPU moins coûteux avec un
manifeste honnêtement modifié, ou obtenir un plafond monétaire/une expiration
RunPod couvrant toute la durée facturable.

Même si tous ces prérequis sont satisfaits, ils ne constituent pas une autorisation
de dépense. Toute création de ressource ou expérience payante exige une
autorisation utilisateur séparée, explicite, indiquant son plafond total.
