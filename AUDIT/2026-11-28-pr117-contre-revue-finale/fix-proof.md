# Correction distincte de la contre-revue #117 — preuve locale

Branche : `fix/issue71-document-lease-fork`, basée sur `ffef872628c925560c9024168ac82b7df8702463`.

RED (tests écrits avant correctif) :
- `test_forked_idle_child_does_not_preserve_crashed_holders_lock` : `DocumentWriteLockTimeout` après crash du détenteur avec enfant inactif vivant ; démontre la fuite du descripteur `flock`.
- `test_locked_core_rejects_a_lease_from_another_repository` : `AssertionError: RuntimeError not raised` ; un dépôt B sans son propre bail peut muter sous le bail A d'un autre répertoire.
- `test_fork_child_cannot_inherit_the_repository_lease_assertion` : `b'inherited' != b'refused'` après fork sous bail.

GREEN : tests ciblés `tests.test_qdrant_write_lock` et les deux nouveaux tests de dépôt : 11 OK. Suite complète CPU locale : `PYTHONPATH=. /root/work/venv/bin/python -m unittest discover -s tests -q` → 1439 OK, 62 ignorés (Qdrant réel absent). Les sorties de fixtures invalides sont attendues par leurs tests ; aucun test en échec. Tests Qdrant réels et CI distants à vérifier sur le SHA final de cette branche, et contre-revue indépendante du SHA final avant toute fusion.

Correction : suivre par jeton tous les descripteurs documentaires depuis leur ouverture jusqu'à leur fermeture, fermer les copies héritées dans l'enfant via `os.register_at_fork`, sans `LOCK_UN` de la description partagée ; refuser de dérouler une sortie héritée sur un numéro de descripteur réutilisé. L'assertion des cœurs privés est maintenant propre à l'instance du dépôt, et la clé TLS héritée est effacée dans l'enfant. Ce durcissement ne change pas les permissions Qdrant, le registre, le benchmark ou l'exposition du service.

Limites : les baux demeurent coopérants, mono-hôte et consultatifs ; plusieurs instances ayant des chemins de verrou différents ne sont pas coordonnées. La classe `CanonicalMaskIndexError` peut encore envelopper une erreur canonique après publication : aucun futur outil de réconciliation ne doit décider à partir de ce seul type. Aucune réconciliation automatisée n'est livrée par cette PR.
