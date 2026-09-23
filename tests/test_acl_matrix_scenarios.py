import random
import unittest

from rag_hermes.acl_matrix import CATEGORIES, build_scenario


class AclMatrixScenarioTests(unittest.TestCase):
    def test_matrix_has_every_required_category(self):
        self.assertEqual(
            set(CATEGORIES),
            {
                "cross_tenant",
                "groups",
                "named_users",
                "clearance_insufficient",
                "clearance_sufficient",
                "acl_missing_or_null",
                "revoked_right",
                "stale_acl_version",
                "public_visibility",
            },
        )

    def test_revoked_and_stale_cases_are_allowed_by_index_but_denied_by_authority(self):
        rng = random.Random(20260923)
        for category in ("revoked_right", "stale_acl_version"):
            scenario = build_scenario(category, 0, rng)
            self.assertTrue(scenario.index_reference_allows)
            self.assertFalse(scenario.authority_allows)

    def test_group_and_named_user_categories_include_allow_and_deny_cases(self):
        rng = random.Random(20260923)
        for category in ("groups", "named_users"):
            outcomes = {
                build_scenario(category, index, rng).authority_allows
                for index in range(4)
            }
            self.assertEqual(outcomes, {False, True})


if __name__ == "__main__":
    unittest.main()
