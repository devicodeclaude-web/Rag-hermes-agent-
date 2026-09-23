from __future__ import annotations

import unittest

from hypothesis import given, settings, strategies as st

from rag_hermes.acl import AuthorizationContext
from rag_hermes.acl_reference import reference_allows
from rag_hermes.qdrant_filter import build_qdrant_filter
from rag_hermes.qdrant_filter_eval import payload_matches_filter


text = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=8,
)
optional_text = st.one_of(st.none(), text)
optional_list = st.one_of(st.none(), st.lists(text, max_size=4, unique=True))


@st.composite
def scenarios(draw):
    tenant = draw(text)
    user = draw(text)
    groups = tuple(draw(st.lists(text, max_size=3, unique=True)))
    clearance = draw(st.integers(min_value=0, max_value=4))
    context = AuthorizationContext(tenant, user, groups, clearance)
    payload = {
        "tenant_id": draw(st.one_of(st.none(), st.sampled_from([tenant, "public"]), text)),
        "visibility": draw(st.one_of(st.none(), st.sampled_from(["public", "private"]))),
        "owner_id": draw(optional_text),
        "allowed_user_ids": draw(optional_list),
        "allowed_group_ids": draw(optional_list),
        "classification": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=5))),
        "tombstone": draw(st.one_of(st.none(), st.booleans())),
    }
    return context, payload


class DifferentialAclTests(unittest.TestCase):
    @given(scenarios())
    @settings(max_examples=1000, derandomize=True, deadline=None)
    def test_qdrant_filter_never_returns_more_than_independent_reference(self, scenario):
        context, payload = scenario
        qdrant = {"candidate"} if payload_matches_filter(payload, build_qdrant_filter(context)) else set()
        reference = {"candidate"} if reference_allows(payload, context) else set()
        self.assertLessEqual(qdrant, reference)


if __name__ == "__main__":
    unittest.main()
