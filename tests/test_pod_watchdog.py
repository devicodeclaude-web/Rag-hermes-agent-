import unittest
from datetime import datetime, timezone

from rag_hermes.pod_watchdog import pods_due_for_deletion, select_guarded_pod


class PodWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.created_after = datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc)
        self.deadline = datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc)
        self.pod = {
            "id": "pod-new",
            "name": "rag-bge-m3-guarded-20260920",
            "createdAt": "2026-09-20T14:05:00Z",
        }

    def test_selects_only_exact_name_created_in_campaign(self):
        pods = [
            {"id": "old", "name": self.pod["name"], "createdAt": "2026-09-19T14:05:00Z"},
            {"id": "other", "name": "another-pod", "createdAt": "2026-09-20T14:06:00Z"},
            self.pod,
        ]
        selected = select_guarded_pod(pods, self.pod["name"], self.created_after)
        self.assertEqual(selected["id"], "pod-new")

    def test_ambiguous_exact_matches_fail_closed(self):
        duplicate = dict(self.pod, id="pod-duplicate")
        with self.assertRaisesRegex(RuntimeError, "multiple pods"):
            select_guarded_pod([self.pod, duplicate], self.pod["name"], self.created_after)

    def test_pod_is_due_only_at_or_after_deadline(self):
        before = datetime(2026, 9, 20, 14, 29, 59, tzinfo=timezone.utc)
        at_deadline = self.deadline
        self.assertEqual(
            pods_due_for_deletion([self.pod], self.pod["name"], self.created_after, self.deadline, before),
            [],
        )
        self.assertEqual(
            pods_due_for_deletion([self.pod], self.pod["name"], self.created_after, self.deadline, at_deadline),
            ["pod-new"],
        )


if __name__ == "__main__":
    unittest.main()
