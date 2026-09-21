import unittest
from datetime import datetime, timezone

from rag_hermes.pod_watchdog import (
    decide_watchdog_action,
    new_pod_due_for_deletion,
    pods_due_for_deletion,
    select_guarded_pod,
    select_new_guarded_pod,
)


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

    def test_live_cli_shape_without_created_at_selects_only_new_exact_name(self):
        pods = [
            {
                "id": "pod-new",
                "name": self.pod["name"],
                "desiredStatus": "RUNNING",
                "runtimeStatus": "running",
            },
            {"id": "old", "name": "another-pod", "desiredStatus": "RUNNING"},
        ]
        selected = select_new_guarded_pod(
            pods,
            self.pod["name"],
            preexisting_ids={"pod-preexisting"},
        )
        self.assertEqual(selected["id"], "pod-new")

    def test_new_selector_fails_closed_if_exact_name_preexisted(self):
        with self.assertRaisesRegex(RuntimeError, "pre-existing"):
            select_new_guarded_pod(
                [{"id": "pod-preexisting", "name": self.pod["name"]}],
                self.pod["name"],
                preexisting_ids={"pod-preexisting"},
            )

    def test_ambiguous_exact_matches_fail_closed(self):
        duplicate = dict(self.pod, id="pod-duplicate")
        with self.assertRaisesRegex(RuntimeError, "multiple pods"):
            select_guarded_pod([self.pod, duplicate], self.pod["name"], self.created_after)

    def test_live_pod_at_deadline_requests_delete(self):
        live_pod = {"id": "pod-new", "name": self.pod["name"]}
        action, pod_id, observed_id = decide_watchdog_action(
            [live_pod], self.pod["name"], set(), None, self.deadline, self.deadline
        )
        self.assertEqual((action, pod_id, observed_id), ("delete", "pod-new", "pod-new"))

    def test_never_observed_at_deadline_fails_closed(self):
        action, pod_id, observed_id = decide_watchdog_action(
            [], self.pod["name"], set(), None, self.deadline, self.deadline
        )
        self.assertEqual((action, pod_id, observed_id), ("never_observed", None, None))

    def test_new_live_shape_is_due_at_deadline_without_created_at(self):
        live_pod = {
            "id": "pod-new",
            "name": self.pod["name"],
            "desiredStatus": "RUNNING",
        }
        self.assertEqual(
            new_pod_due_for_deletion(
                [live_pod],
                self.pod["name"],
                preexisting_ids=set(),
                deadline=self.deadline,
                now=self.deadline,
            ),
            ["pod-new"],
        )

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
