"""Contrat partagé des scores de reranker (V1, G1 et runner de campagne).

L'audit externe CODE-01 a mis en évidence une divergence : `g1_reranking`
vérifiait `math.isfinite` sur les scores rendus par le cross-encodeur, le
chemin service V1 non — il triait directement sur `float(score)`. Un score NaN
rend la comparaison de tri non transitive (l'ordre des preuves devient
arbitraire selon l'implémentation du tri) et ±inf épingle un candidat en tête
indépendamment de sa pertinence. Les deux chemins passent désormais par la
MÊME fonction, pour qu'ils ne puissent plus redivorcer en silence.
"""

from __future__ import annotations

from itertools import islice
from numbers import Real
import math
from typing import Any


class RerankerScoreError(Exception):
    """Contrat de score violé par un reranker injecté.

    Volontairement HORS de la hiérarchie `ValueError` : chaque appelant la
    traduit dans son propre vocabulaire d'erreur (ValueError pour les chemins
    d'évaluation, `GenerationError` pour le service HTTP qui doit rendre un
    5xx et non un 400).
    """


def ensure_finite_scores(values: Any, expected_count: int) -> list[float]:
    """Exige exactement `expected_count` scores réels FINIS et les renvoie.

    - Un score scalaire unique est accepté (certains rerankers renvoient un
      nombre quand une seule paire est soumise).
    - La matérialisation est bornée à `expected_count + 1` éléments : un
      générateur de scores infini doit échouer, jamais faire boucler une
      requête.
    - `bool` est refusé bien qu'il soit un `int` : `True` se classerait comme
      1.0 et masquerait un reranker cassé.
    - Les chaînes sont refusées même si `float("0.9")` fonctionnerait : un
      score numérique rendu en texte n'est pas un contrat de scoring valide.
    """
    if type(expected_count) is not int or expected_count < 0:
        raise ValueError("expected_count doit être un entier >= 0")
    if isinstance(values, (str, bytes, bytearray)):
        raise RerankerScoreError("les scores ne peuvent pas être une chaîne")
    if isinstance(values, Real) and not isinstance(values, bool):
        materialized: list[Any] = [values]
    else:
        try:
            materialized = list(islice(values, expected_count + 1))
        except TypeError as exc:
            raise RerankerScoreError(
                "les scores doivent être un nombre ou un itérable de nombres"
            ) from exc
    if len(materialized) != expected_count:
        raise RerankerScoreError(
            f"{expected_count} score(s) attendu(s), {len(materialized)} reçu(s)"
        )
    scores: list[float] = []
    for value in materialized:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise RerankerScoreError(
                "chaque score doit être un nombre réel (ni booléen ni chaîne)"
            )
        try:
            score = float(value)
        except (OverflowError, TypeError, ValueError) as exc:
            raise RerankerScoreError(
                "un score n'est pas convertible en flottant"
            ) from exc
        # Contrôle la valeur RÉELLEMENT publiée, pas l'objet d'origine : une
        # sous-classe de Real peut redéfinir __float__.
        if not math.isfinite(score):
            raise RerankerScoreError("un score n'est pas fini (NaN ou ±inf)")
        scores.append(score)
    return scores
