# Réconciliation des deux audits du smoke GPU BGE-M3

## Statut de preuve

Le run du 20 septembre 2026 valide uniquement :

- le provisionnement et l’arrêt propre d’une RTX 4090 RunPod ;
- la compatibilité réelle PyTorch 2.8 / CUDA 12.8 / BGE-M3 ;
- le téléchargement aux révisions Hugging Face verrouillées et la vérification des artefacts listés ;
- la production dense+sparse sur 2 945 chunks ;
- le refus explicite des paires dépassant 512 tokens ;
- la récupération et le hachage du rapport ;
- le filtrage ACL Python en mémoire utilisé par ce runner.

Il ne valide pas encore :

- la qualité générale du retrieval ou du reranker ;
- la sécurité ACL dans Qdrant pour les embeddings GPU ;
- une absence de fuite du système multi-tenant complet ;
- une politique d’abstention calibrée ;
- la robustesse sur des questions indépendantes du corpus.

## Explication exacte du recall post-reranking à 0,667

Le calcul porte seulement sur les six questions répondables, pas sur les dix questions totales.

| Question | Document pertinent retrouvé après reranking | Contribution recall |
|---|---:|---:|
| `public-termux` | non — aucune paire admissible | 0 |
| `public-configuration` | non — `integrations/providers.md` retourné à la place | 0 |
| `private-personal` | oui, rang 1 | 1 |
| `alpha-own-secret` | oui, rang 1 | 1 |
| `beta-own-secret` | oui, rang 1 | 1 |
| `gamma-own-secret` | oui, rang 1 | 1 |

Donc `recall@10 = (0 + 0 + 1 + 1 + 1 + 1) / 6 = 4/6 = 0,6667`. Le MRR est identique parce que chacun des quatre succès est au rang 1. Ce résultat n’évalue pas proprement le reranker : 190 des 200 paires candidates ont été rejetées avant scoring.

## Déviation confirmée

La spécification demandait un découpage en tokens. Le runner a réutilisé `chunk_document(..., max_tokens=420)`, dont l’implémentation découpe en réalité avec `str.split()` et compte des mots. Il s’agit d’une déviation de spécification, pas d’une découverte expérimentale.

## Contrat de chunking retenu

Le tokenizer exact de `BAAI/bge-reranker-v2-m3` à la révision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` gouverne le découpage :

- question : plafond contractuel de 96 tokens ;
- passage : cible maximale de 384 tokens ;
- overlap : 64 tokens ;
- paire finale : vérification exacte avec `add_special_tokens=True` et `truncation=False` ;
- limite absolue : 512 tokens ;
- toute paire au-dessus de 512 invalide le smoke ; elle n’est jamais tronquée.

La valeur 384 est une cible de chunk. La vérification de la paire complète reste l’autorité, car le nombre de tokens spéciaux dépend du tokenizer et de sa révision.

Chaque chunk tokenisé doit conserver : `chunk_id`, `document_id`, `section`, `start_offset`, `end_offset`, `token_count`, `tokenizer_name`, `tokenizer_revision`, `content_hash`, ainsi que le payload ACL existant.

Le découpage doit préserver autant que possible les titres avec leur paragraphe, les blocs de code, les commandes avec leur sortie et les tableaux avec leurs en-têtes.

## Ordre d’exécution retenu

1. Écrire les tests rouges du contrat tokenisé et de la limite de paire.
2. Implémenter le chunking tokenizer-aware en 384 tokens avec overlap 64.
3. Exécuter l’intégration ACL contre Qdrant 1.19.0 réel avec vecteurs identiques de test ; cela ne dépend pas du nouveau découpage.
4. Préparer l’exécution distante sous utilisateur non-root et la garde durée/budget.
5. Reconstruire le corpus et vérifier localement les métadonnées de chaque chunk.
6. Relancer le smoke GPU et exiger `rejected_pairs = 0`, `truncated_pairs = 0`.
7. Publier les métriques détaillées par question avant et après reranking sur le même ensemble.
8. Persister les embeddings réels dans Qdrant seulement après validation du nouveau découpage.
9. Porter l’évaluation à 100 questions dont au moins 30 écrites manuellement sans regarder les chunks.
10. Conserver la porte finale existante de 300 questions et au moins 20 % de revue humaine.

## Sécurité opérationnelle retenue

Avant tout nouveau Pod :

- utilisateur de travail dédié non-root dans le conteneur ;
- clé privée locale en mode `600` ;
- clé protégée par passphrase et chargée dans un agent, ou mécanisme éphémère équivalent documenté ;
- clé/API RunPod au périmètre minimal lorsqu’une clé API est utilisée ;
- plafond explicite de durée et de coût calculé avant création ;
- garde de terminaison indépendante du processus de benchmark ;
- récupération du rapport avant terminaison ;
- vérification finale que la liste des Pods est vide.

## Critères du prochain smoke

- `rejected_pairs = 0` ;
- `truncated_pairs = 0` ;
- détail par question avec pertinents attendus, candidats avant reranking, résultats après reranking, rang et motif d’abstention ;
- Recall@20 pré-reranking mesuré comme signal de smoke uniquement ;
- Recall@10 et MRR post-reranking calculés sur le même ensemble ;
- aucune régression post-reranking sur ce smoke ;
- ACL Qdrant réel validée séparément avec fuite absolue égale à zéro ;
- aucune revendication de qualité générale avant les jeux de 100 puis 300 questions.
