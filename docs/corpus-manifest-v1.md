# Manifeste du corpus v1

Date d'observation : 2026-09-23 UTC.

## Corpus public de qualité

- Fichier : `data/generated/hermes_public_documents.jsonl`
- SHA-256 : `af0631abbffaab14b180abc4531497665a6104d6685328d6abbe53a565c53866`
- Nombre de documents : 461
- Langue observée : anglais
- Visibilité : `public`
- Tenant technique : `public`
- Source : `https://github.com/NousResearch/hermes-agent.git`
- Révision source : `b682a98ab8cb30c4f0561021e0ff9f41e5156526`
- Racine source : `website/docs`
- Commande de reconstruction : documentée dans `README.md` et exécutée par
  `scripts/build_public_corpus.py`.

Chaque `source_uri` du fichier généré contient la révision Git et le chemin du
document. Le checkout local `data/sources/hermes-agent` est sur la même
révision au moment de cette observation.

## Fixtures privées de sécurité

- Fichier : `data/fixtures/private_and_synthetic_documents.jsonl`
- SHA-256 : `8276caa3bcd86d1759b69e34120b804cae3460e8476986e80d079ce9bc65a19b`
- Nombre de documents : 4
- Langue observée : français
- Visibilité : `private`
- Tenants : `personal`, `alpha`, `beta`, `gamma`
- Provenance : documents synthétiques locaux identifiés par des URI
  `synthetic://...`.

Ces quatre documents servent aux tests de cloisonnement, de révocation et de
non-fuite. Ils ne constituent pas un corpus privé suffisamment riche pour une
conclusion de qualité générative. Une comparaison public/privé de la qualité
des réponses reste **BLOQUÉE** jusqu'à l'ajout d'un corpus privé réaliste,
licite, versionné et expurgé de secrets.

## Périmètres à ne pas confondre

1. **Qualité publique** : réponses sur les 461 documents publics.
2. **Sécurité privée synthétique** : tests ACL sur les quatre fixtures.
3. **Qualité privée réelle** : non disponible dans le corpus v1.

Les métriques de ces périmètres doivent être publiées séparément. Un succès
sur les fixtures synthétiques ne prouve ni la qualité sur de vrais documents
privés ni la sécurité d'une autorité ACL persistante déployée.
