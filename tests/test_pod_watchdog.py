import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

from rag_hermes.pod_watchdog import (
    decide_watchdog_action,
    fallback_after_list_error,
    new_pod_due_for_deletion,
    parse_pod_list_payload,
    pods_due_for_deletion,
    publish_ready_marker,
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

    def test_observed_pod_missing_once_does_not_confirm_absence_before_delete(self):
        action, pod_id, observed_id = decide_watchdog_action(
            [], self.pod["name"], set(), "pod-new", self.deadline,
            datetime(2026, 9, 20, 14, 10, tzinfo=timezone.utc),
            deletion_requested=False,
        )
        self.assertEqual((action, pod_id, observed_id), ("wait", None, "pod-new"))

    def test_absence_after_delete_requires_repeated_confirmations(self):
        first = decide_watchdog_action(
            [], self.pod["name"], set(), "pod-new", self.deadline,
            self.deadline,
            deletion_requested=True,
            absence_confirmations=0,
        )
        second = decide_watchdog_action(
            [], self.pod["name"], set(), "pod-new", self.deadline,
            self.deadline,
            deletion_requested=True,
            absence_confirmations=1,
        )
        self.assertEqual(first, ("confirm_absence", None, "pod-new"))
        self.assertEqual(second, ("confirmed_absent", None, "pod-new"))

    def test_observed_pod_missing_at_deadline_requests_delete_by_observed_id(self):
        action, pod_id, observed_id = decide_watchdog_action(
            [], self.pod["name"], set(), "pod-new", self.deadline,
            self.deadline,
            deletion_requested=False,
        )
        self.assertEqual(
            (action, pod_id, observed_id),
            ("delete", "pod-new", "pod-new"),
        )

    def test_successful_delete_request_is_retried_while_pod_remains_listed(self):
        live_pod = {"id": "pod-new", "name": self.pod["name"]}
        action, pod_id, observed_id = decide_watchdog_action(
            [live_pod], self.pod["name"], set(), "pod-new", self.deadline,
            self.deadline,
            deletion_requested=True,
        )
        self.assertEqual((action, pod_id, observed_id), ("delete", "pod-new", "pod-new"))

    def test_delete_retries_are_bounded_before_provider_deadline(self):
        provider_deadline = datetime(2026, 9, 20, 14, 35, tzinfo=timezone.utc)
        action = decide_watchdog_action(
            [{"id": "pod-new", "name": self.pod["name"]}],
            self.pod["name"],
            set(),
            "pod-new",
            self.deadline,
            self.deadline,
            delete_attempts=3,
            max_delete_attempts=3,
            provider_deadline=provider_deadline,
        )
        terminal = decide_watchdog_action(
            [{"id": "pod-new", "name": self.pod["name"]}],
            self.pod["name"],
            set(),
            "pod-new",
            self.deadline,
            provider_deadline,
            delete_attempts=3,
            max_delete_attempts=3,
            provider_deadline=provider_deadline,
        )
        self.assertEqual(action, ("monitor_after_delete_retries", None, "pod-new"))
        self.assertEqual(
            terminal,
            ("unconfirmed_at_provider_deadline", None, "pod-new"),
        )

    def test_never_observed_requires_repeated_omissions_until_provider_deadline(self):
        provider_deadline = datetime(2026, 9, 20, 14, 35, tzinfo=timezone.utc)
        first = decide_watchdog_action(
            [], self.pod["name"], set(), None, self.deadline, self.deadline,
            absence_confirmations=0,
            provider_deadline=provider_deadline,
        )
        final = decide_watchdog_action(
            [], self.pod["name"], set(), None, self.deadline, provider_deadline,
            absence_confirmations=1,
            provider_deadline=provider_deadline,
        )
        self.assertEqual(first, ("confirm_unobserved", None, None))
        self.assertEqual(final, ("never_observed", None, None))

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

    def test_pod_list_parser_accepts_only_documented_list_shapes(self):
        pods = [{"id": "p1", "name": "guarded"}]
        self.assertEqual(parse_pod_list_payload(pods), pods)
        self.assertEqual(parse_pod_list_payload({"pods": pods}), pods)
        self.assertEqual(parse_pod_list_payload({"data": pods}), pods)
        self.assertEqual(parse_pod_list_payload([]), [])
        self.assertEqual(parse_pod_list_payload({"pods": []}), [])

    def test_error_envelope_is_rejected_without_incrementing_absence(self):
        absence_confirmations = 0
        try:
            pods = parse_pod_list_payload(
                {"pods": [], "error": "unauthorized"}
            )
            action, _pod_id, _observed_id = decide_watchdog_action(
                pods,
                self.pod["name"],
                set(),
                "pod-new",
                self.deadline,
                self.deadline,
                deletion_requested=True,
                absence_confirmations=absence_confirmations,
            )
            if action == "confirm_absence":
                absence_confirmations += 1
        except ValueError:
            pass

        self.assertEqual(absence_confirmations, 0)

    def test_pod_list_parser_rejects_failure_status_envelope(self):
        with self.assertRaisesRegex(ValueError, "status"):
            parse_pod_list_payload({"pods": [], "status": "failed"})

    def test_pod_list_parser_rejects_malformed_empty_lookalikes(self):
        malformed = [
            None,
            {},
            {"unexpected": []},
            {"pods": None},
            {"data": {}},
            [None],
            [{}],
            [{"id": "p1"}],
            [{"name": "guarded"}],
            [{"id": "", "name": "guarded"}],
            [{"id": "p1", "name": ""}],
            [{"id": 1, "name": "guarded"}],
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "malformed pod list response"):
                    parse_pod_list_payload(payload)

    def test_pod_list_parser_rejects_unexpected_envelope_keys(self):
        for payload in (
            {"pods": [], "meta": {}},
            {"data": [], "status": "success"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "exactly"):
                    parse_pod_list_payload(payload)

    def test_pod_list_parser_rejects_ambiguous_envelope(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            parse_pod_list_payload({"pods": [], "data": []})

    def test_list_failure_at_deadline_deletes_already_observed_id(self):
        action, pod_id = fallback_after_list_error(
            "pod-new", self.deadline, self.deadline
        )
        self.assertEqual((action, pod_id), ("delete", "pod-new"))

    def test_list_failure_at_deadline_without_observed_id_fails_closed(self):
        action, pod_id = fallback_after_list_error(None, self.deadline, self.deadline)
        self.assertEqual((action, pod_id), ("fatal_unobserved", None))

    def test_watchdog_cli_tracks_provider_deadline_and_bounded_state(self):
        script = Path("scripts/pod_watchdog.py").read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--provider-deadline", required=True)', script)
        self.assertIn('parser.add_argument("--max-delete-attempts", type=int, default=3)', script)
        self.assertIn("absence_confirmations=absence_confirmations", script)
        self.assertIn("delete_attempts=delete_attempts", script)
        self.assertIn('elif action == "unconfirmed_at_provider_deadline":', script)

    def test_ready_marker_is_machine_readable_and_refuses_stale_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "armed.json"
            payload = {"event": "watchdog_armed", "name": self.pod["name"]}
            publish_ready_marker(path, payload)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
            with self.assertRaisesRegex(FileExistsError, "ready marker already exists"):
                publish_ready_marker(path, payload)

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
