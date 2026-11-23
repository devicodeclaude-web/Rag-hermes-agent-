"""Diagnostic hors ligne SEC-02 : jamais une réparation ni un feu vert de service."""
from __future__ import annotations

import hashlib
from dataclasses import replace
import errno
from io import StringIO
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from rag_hermes.canonical_registry import CanonicalDocumentRegistry, CanonicalStoreError
from rag_hermes.canonical_reconciliation import (
    CanonicalIndexDivergence, audit_canonical_copy_index,
    plan_canonical_index_reconciliation, render_divergence_report,
)
from rag_hermes.index_integrity import IndexSnapshotReport
from rag_hermes.ingestion import Document, chunk_document
from rag_hermes.qdrant_identity import mint_collection_token
from rag_hermes.qdrant_store import chunk_to_point


def _document(*, version: int = 1, users: tuple[str, ...] = ("bob",)) -> Document:
    return Document(
        document_id="doc-1", content="texte confidentiel de contrôle",
        tenant_id="alpha", visibility="private", owner_id="alice",
        allowed_groups=(), allowed_users=users, classification=1,
        doc_version=1, acl_version=version, source_uri="file:///doc-1",
    )


class _PagedAuditClient:
    def __init__(self, points):
        self.points = points
        self.calls = []

    def scroll_page(self, collection, *, limit, offset=None):
        self.calls.append((collection, limit, offset))
        start = 0 if offset is None else offset
        end = start + limit
        return self.points[start:end], (end if end < len(self.points) else None)


class CanonicalReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)
        self.registry = CanonicalDocumentRegistry(self.store)
        self.registry.register(_document())
        self.anchor_digest = hashlib.sha256(self.registry.anchor_path.read_bytes()).hexdigest()
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in chunk_document(_document())]
        self.client = _PagedAuditClient(self.points)

    def audit(self, **kwargs):
        return audit_canonical_copy_index(
            self.store, anchor_sha256=self.anchor_digest,
            client=self.client, collection="chunks", chunker=chunk_document,
            page_size=1, **kwargs,
        )

    def test_matching_copy_is_audited_read_only(self):
        before = {p.name: p.read_bytes() for p in self.store.iterdir()}
        report = self.audit()
        self.assertIsInstance(report, IndexSnapshotReport)
        self.assertEqual(report.point_count, len(self.points))
        self.assertEqual({p.name: p.read_bytes() for p in self.store.iterdir()}, before)
        self.assertEqual(self.client.calls, [("chunks", 1, None)])

    def test_missing_indexed_point_is_refused_not_called_repaired(self):
        self.client.points = []
        with self.assertRaisesRegex(ValueError, "missing canonical indexed points"):
            self.audit()
        self.assertEqual(self.client.calls, [("chunks", 1, None)])

    def test_anchor_pin_mismatch_refuses_before_qdrant(self):
        self.anchor_digest = "0" * 64
        with self.assertRaisesRegex(ValueError, "anchor.*digest"):
            self.audit()
        self.assertEqual(self.client.calls, [])

    def test_missing_lock_is_not_recreated(self):
        (self.store / "canonical_transaction.lock").unlink()
        with self.assertRaises(FileNotFoundError):
            self.audit()
        self.assertFalse((self.store / "canonical_transaction.lock").exists())
        self.assertEqual(self.client.calls, [])

    def test_audit_never_opens_the_copy_for_writing(self):
        """Pins the doc claim: usable on read-only media, creates nothing."""
        real_open = os.open
        refused = []
        def readonly_open(path, flags, *args, **kwargs):
            if flags & (os.O_ACCMODE | os.O_CREAT) != os.O_RDONLY:
                refused.append(path)
                raise OSError(errno.EROFS, "read-only media")
            return real_open(path, flags, *args, **kwargs)
        with patch("rag_hermes.canonical_registry.os.open", readonly_open):
            self.assertEqual(self.audit().point_count, 1)
        self.assertEqual(refused, [])
        self.assertEqual(
            sorted(p.name for p in self.store.iterdir()),
            ["canonical_anchor.json", "canonical_documents.jsonl",
             "canonical_transaction.lock"],
        )

    def test_revised_acl_with_stale_index_is_detected(self):
        self.registry.register(_document(version=2, users=()))
        self.anchor_digest = hashlib.sha256(self.registry.anchor_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "indexed payload conflicts"):
            self.audit()

    def test_unanchored_copy_is_refused_before_qdrant(self):
        self.registry.anchor_path.unlink()
        with self.assertRaisesRegex(Exception, "anchor"):
            self.audit()
        self.assertEqual(self.client.calls, [])

    def test_a_document_without_chunks_cannot_disappear_from_the_audit(self):
        self.registry.register(replace(_document(), document_id="doc-empty", content="   "))
        self.anchor_digest = hashlib.sha256(self.registry.anchor_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "canonical document produced no chunks"):
            self.audit()
        self.assertEqual(self.client.calls, [])

    def test_copy_changed_during_scroll_never_returns_a_report(self):
        original = self.client.scroll_page
        def mutate(collection, *, limit, offset=None):
            page = original(collection, limit=limit, offset=offset)
            self.registry.anchor_path.unlink()
            return page
        self.client.scroll_page = mutate
        with self.assertRaises(FileNotFoundError):
            self.audit()
        self.assertEqual(self.client.calls, [("chunks", 1, None)])

    def test_cli_requires_read_only_token_before_network(self):
        from scripts import audit_canonical_copy as command
        args = ["audit_canonical_copy.py", "--copy", str(self.store),
                "--anchor-sha256", self.anchor_digest, "--qdrant-url", "http://localhost:6333",
                "--collection", "chunks", "--tokenizer-lock", "lock.json",
                "--tokenizer-file", "tokenizer.json"]
        with (patch("sys.argv", args), patch.dict(os.environ, {}, clear=True),
              patch.object(command, "QdrantAuditClient") as audit_client,
              patch("sys.stdout", new_callable=StringIO) as output):
            self.assertNotEqual(command.main(), 0)
        audit_client.assert_not_called()
        self.assertIn("REFUS", output.getvalue())


class ReconciliationPlanTests(unittest.TestCase):
    """Enumerate divergences for a human repair; never a pass and never a write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name)
        self.registry = CanonicalDocumentRegistry(self.store)
        self.registry.register(_document())
        self.anchor_digest = hashlib.sha256(self.registry.anchor_path.read_bytes()).hexdigest()
        self.points = [chunk_to_point(chunk, [1.0]) for chunk in chunk_document(_document())]
        self.client = _PagedAuditClient(list(self.points))

    def plan(self, **kwargs):
        return plan_canonical_index_reconciliation(
            self.store, anchor_sha256=self.anchor_digest,
            client=self.client, collection="chunks", chunker=chunk_document,
            page_size=1, **kwargs,
        )

    def test_a_matching_index_yields_an_empty_plan_that_is_not_an_audit_report(self):
        plan = self.plan()
        self.assertNotIsInstance(plan, IndexSnapshotReport)
        self.assertTrue(plan.is_clean)
        self.assertEqual(plan.expected_point_count, len(self.points))
        self.assertEqual(plan.missing_point_ids, ())
        self.assertEqual(plan.unexpected_point_ids, ())
        self.assertEqual(plan.divergent_points, ())

    def test_a_point_absent_from_the_index_is_listed_as_missing(self):
        self.client.points = []
        plan = self.plan()
        self.assertFalse(plan.is_clean)
        self.assertEqual(plan.missing_point_ids, (self.points[0]["id"],))
        self.assertEqual(plan.observed_point_count, 0)
        self.assertEqual(plan.unexpected_point_ids, ())

    def test_a_point_the_copy_does_not_describe_is_listed_as_unexpected(self):
        stranger = {"id": "00000000-0000-4000-8000-000000000001",
                    "payload": {"tenant_id": "beta"}}
        self.client.points = list(self.points) + [stranger]
        plan = self.plan()
        self.assertFalse(plan.is_clean)
        self.assertEqual(plan.unexpected_point_ids, (stranger["id"],))
        self.assertEqual(plan.missing_point_ids, ())
        self.assertEqual(plan.observed_point_count, len(self.points) + 1)

    def test_a_payload_altered_at_a_known_id_lists_field_names_only(self):
        """The plan must name WHICH fields diverge without copying any value."""
        altered = dict(self.points[0])
        altered["payload"] = {**altered["payload"], "acl_version": 99,
                              "text": "texte falsifié par l'index"}
        self.client.points = [altered]
        plan = self.plan()
        self.assertFalse(plan.is_clean)
        self.assertEqual(plan.missing_point_ids, ())
        self.assertEqual(plan.unexpected_point_ids, ())
        self.assertEqual(plan.divergent_points,
                         ((self.points[0]["id"], ("acl_version", "text")),))
        rendered = repr(plan)
        for secret in ("texte confidentiel de contrôle", "texte falsifié par l'index",
                       "alice", "bob", "99"):
            self.assertNotIn(secret, rendered)

    def test_a_divergence_larger_than_the_budget_fails_closed(self):
        strangers = [
            {"id": f"00000000-0000-4000-8000-{index:012d}", "payload": {"tenant_id": "beta"}}
            for index in range(5)
        ]
        self.client.points = list(self.points) + strangers
        with self.assertRaisesRegex(ValueError, "exceeds the reconciliation plan budget"):
            self.plan(surplus_budget=3)
        # The budget stops the scroll instead of growing unbounded.
        self.assertLessEqual(len(self.client.calls), 5)
        self.assertEqual(self.plan(surplus_budget=5).unexpected_point_ids,
                         tuple(stranger["id"] for stranger in strangers))

    def test_a_malformed_budget_is_refused_before_touching_the_copy(self):
        for budget in (-1, True, 1.5, "10", 100_001):
            with self.subTest(budget=budget):
                with self.assertRaisesRegex(ValueError, "surplus_budget"):
                    self.plan(surplus_budget=budget)
        self.assertEqual(self.client.calls, [])

    def test_an_integer_point_id_is_enumerated_not_a_blanket_refusal(self):
        """Qdrant accepts integer ids: a third-party writer must not blind the plan."""
        self.client.points = list(self.points) + [
            {"id": 4242, "payload": {"tenant_id": "beta"}},
        ]
        plan = self.plan()
        self.assertEqual(plan.unexpected_point_ids, ("4242",))
        self.assertEqual(plan.missing_point_ids, ())
        self.assertEqual(plan.divergent_points, ())

    def test_a_boolean_point_id_is_still_refused(self):
        # isinstance(True, int) is true: the int path must not accept a bool.
        self.client.points = [{"id": True, "payload": {}}]
        with self.assertRaisesRegex(ValueError, "invalid indexed point id"):
            self.plan()

    def test_an_unencodable_payload_fails_like_the_audit_not_with_a_type_error(self):
        altered = dict(self.points[0])
        altered["payload"] = {**altered["payload"], "acl_version": {1, 2}}
        self.client.points = [altered]
        with self.assertRaisesRegex(ValueError, "invalid indexed payload encoding"):
            self.plan()

    def test_an_acl_field_removed_from_the_index_is_reported_as_divergent(self):
        """A widened ACL in the index often means a MISSING restriction field."""
        altered = dict(self.points[0])
        payload = {key: value for key, value in altered["payload"].items()
                   if key != "allowed_user_ids"}
        altered["payload"] = payload
        self.client.points = [altered]
        plan = self.plan()
        self.assertEqual(plan.divergent_points,
                         ((self.points[0]["id"], ("allowed_user_ids",)),))

    def test_a_field_only_the_index_carries_is_reported_as_divergent(self):
        altered = dict(self.points[0])
        altered["payload"] = {**altered["payload"], "champ_surnumeraire": 1}
        self.client.points = [altered]
        plan = self.plan()
        self.assertEqual(plan.divergent_points,
                         ((self.points[0]["id"], ("champ_surnumeraire",)),))

    def test_a_duplicated_indexed_id_fails_closed(self):
        self.client.points = list(self.points) + list(self.points)
        with self.assertRaisesRegex(ValueError, "duplicate indexed point id"):
            self.plan()

    def test_a_chunker_producing_two_identical_points_fails_closed(self):
        doubled = lambda document: list(chunk_document(document)) * 2
        with self.assertRaisesRegex(ValueError, "duplicate canonical point id"):
            plan_canonical_index_reconciliation(
                self.store, anchor_sha256=self.anchor_digest, client=self.client,
                collection="chunks", chunker=doubled, page_size=1,
            )

    def test_a_point_that_is_not_a_mapping_or_lacks_a_payload_fails_closed(self):
        for broken, message in ((["not-a-dict"], "invalid indexed point id"),
                                ([{"id": "x"}], "invalid indexed payload"),
                                ([{"id": {}, "payload": {}}], "invalid indexed point id")):
            with self.subTest(broken=broken):
                self.client.points = broken
                with self.assertRaisesRegex(ValueError, message):
                    self.plan()

    def test_a_malformed_or_repeated_cursor_fails_closed(self):
        class _BadCursorClient:
            def __init__(self, cursor):
                self.cursor = cursor
                self.calls = []

            def scroll_page(self, collection, *, limit, offset=None):
                self.calls.append(offset)
                return [{"id": "a", "payload": {}}], self.cursor

        for cursor in (True, 1.5, [], "same"):
            with self.subTest(cursor=cursor):
                self.client = _BadCursorClient(cursor)
                with self.assertRaisesRegex(
                    ValueError, "invalid or repeated Qdrant scroll cursor"
                ):
                    self.plan()

    def test_a_page_longer_than_the_limit_fails_closed(self):
        class _OversizedClient:
            calls: list = []

            def scroll_page(self, collection, *, limit, offset=None):
                return [{"id": "a", "payload": {}}, {"id": "b", "payload": {}}], None

        self.client = _OversizedClient()
        with self.assertRaisesRegex(ValueError, "invalid Qdrant scroll page"):
            self.plan()

    def test_a_missing_collection_or_unbounded_page_size_is_refused(self):
        for kwargs, message in (({"collection": ""}, "collection and bounded page_size"),
                                ({"page_size": 0}, "collection and bounded page_size"),
                                ({"page_size": 1001}, "collection and bounded page_size"),
                                ({"page_size": True}, "collection and bounded page_size")):
            with self.subTest(kwargs=kwargs):
                call = {"anchor_sha256": self.anchor_digest, "client": self.client,
                        "collection": "chunks", "chunker": chunk_document,
                        "page_size": 1, **kwargs}
                with self.assertRaisesRegex(ValueError, message):
                    plan_canonical_index_reconciliation(self.store, **call)

    def test_the_plan_path_refuses_an_unapproved_anchor_before_any_scroll(self):
        self.anchor_digest = "0" * 64
        with self.assertRaisesRegex(ValueError, "anchor.*digest"):
            self.plan()
        self.assertEqual(self.client.calls, [])

    def test_an_anchor_claiming_zero_records_is_refused_before_any_scroll(self):
        # A zeroed anchor must not read as "no anchor at all".
        self.registry.anchor_path.write_text(
            '{"documents":{},"digest":"%s","records":0}'
            % hashlib.sha256(b"").hexdigest()
        )
        self.anchor_digest = hashlib.sha256(
            self.registry.anchor_path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(CanonicalStoreError, "nonempty canonical anchor"):
            self.plan()
        self.assertEqual(self.client.calls, [])

    def test_the_copy_directory_swapped_under_the_open_descriptor_yields_no_plan(self):
        # The decoy carries the SAME bytes, so anchor and replay still verify:
        # only the inode of the directory differs, which is what the check is
        # for. A decoy with different content is caught earlier, by the replay.
        decoy = Path(self.tmp.name + "-decoy")
        shutil.copytree(self.store, decoy)
        self.addCleanup(lambda: decoy.exists() and shutil.rmtree(decoy))
        moved = Path(self.tmp.name + "-moved")
        self.addCleanup(lambda: moved.exists() and shutil.rmtree(moved))
        original = self.client.scroll_page

        def swap(collection, *, limit, offset=None):
            page = original(collection, limit=limit, offset=offset)
            if self.store.exists():
                self.store.rename(moved)
                decoy.rename(self.store)
            return page

        self.client.scroll_page = swap
        with self.assertRaisesRegex(CanonicalStoreError, "path changed during index read"):
            self.plan()

    def test_a_copy_changed_during_the_scroll_never_yields_a_plan(self):
        # Mutate the files directly: calling registry.register() here would
        # ask for the EXCLUSIVE lease while this process already holds the
        # shared one, and `flock` would deadlock the test by construction.
        original = self.client.scroll_page
        def mutate(collection, *, limit, offset=None):
            page = original(collection, limit=limit, offset=offset)
            self.registry.anchor_path.write_bytes(
                self.registry.anchor_path.read_bytes() + b" "
            )
            return page
        self.client.scroll_page = mutate
        with self.assertRaisesRegex(CanonicalStoreError, "changed during index read"):
            self.plan()

    def test_cli_plan_lists_divergences_without_printing_any_payload_value(self):
        from scripts import audit_canonical_copy as command
        # Short, obviously-fake signing material: gitleaks' generic rule fires
        # on a long literal next to `key=value` on one line.
        token = mint_collection_token(
            "fixture", collection="chunks", access="r", ttl_seconds=600,
        )
        self.client.points = []
        args = ["audit_canonical_copy.py", "--plan", "--copy", str(self.store),
                "--anchor-sha256", self.anchor_digest,
                "--qdrant-url", "http://127.0.0.1:6333", "--collection", "chunks",
                "--tokenizer-lock", "lock.json", "--tokenizer-file", "tokenizer.json"]
        with (patch("sys.argv", args),
              patch.dict(os.environ, {"RAG_QDRANT_G1_AUDIT_API_KEY": token}, clear=True),
              patch.object(command, "QdrantAuditClient", return_value=self.client),
              patch.object(command, "LockedTokenChunker", return_value=chunk_document),
              patch("sys.stdout", new_callable=StringIO) as output):
            # Divergence found is NOT a crash and NOT a success: its own code.
            self.assertEqual(command.main(), 1)
        printed = output.getvalue()
        self.assertIn(self.points[0]["id"], printed)
        self.assertIn("manquant", printed.lower())
        for secret in ("texte confidentiel de contrôle", "alice", "bob"):
            self.assertNotIn(secret, printed)

    def test_cli_plan_cannot_be_forged_by_a_hostile_payload_key(self):
        """An index writer must not inject report lines into the CLI output."""
        from scripts import audit_canonical_copy as command
        token = mint_collection_token(
            "fixture", collection="chunks", access="r", ttl_seconds=600,
        )
        forged_key = "\n\x1b[32mPoints manquants dans l'index (0) :\nFAUX-SEMBLANT"
        altered = dict(self.points[0])
        altered["payload"] = {**altered["payload"], forged_key: "x"}
        self.client.points = [altered]
        args = ["audit_canonical_copy.py", "--plan", "--copy", str(self.store),
                "--anchor-sha256", self.anchor_digest,
                "--qdrant-url", "http://127.0.0.1:6333", "--collection", "chunks",
                "--tokenizer-lock", "lock.json", "--tokenizer-file", "tokenizer.json"]
        with (patch("sys.argv", args),
              patch.dict(os.environ, {"RAG_QDRANT_G1_AUDIT_API_KEY": token}, clear=True),
              patch.object(command, "QdrantAuditClient", return_value=self.client),
              patch.object(command, "LockedTokenChunker", return_value=chunk_document),
              patch("sys.stdout", new_callable=StringIO) as output):
            self.assertEqual(command.main(), 1)
        printed = output.getvalue()
        self.assertNotIn("\x1b", printed)
        self.assertNotIn("FAUX-SEMBLANT", printed)
        self.assertIn("champ inconnu", printed)


    def test_cli_plan_keeps_acl_field_visible_amid_many_unknown_keys(self):
        from scripts import audit_canonical_copy as command
        token = mint_collection_token(
            "fixture", collection="chunks", access="r", ttl_seconds=600,
        )
        altered = dict(self.points[0])
        payload = dict(altered["payload"])
        payload.pop("allowed_user_ids")
        payload.update({f"0_extra_{index:02d}": "x" for index in range(20)})
        payload["PRIVATE_TOKEN_abcd1234"] = "x"
        altered["payload"] = payload
        self.client.points = [altered]
        args = ["audit_canonical_copy.py", "--plan", "--copy", str(self.store),
                "--anchor-sha256", self.anchor_digest,
                "--qdrant-url", "http://127.0.0.1:6333", "--collection", "chunks",
                "--tokenizer-lock", "lock.json", "--tokenizer-file", "tokenizer.json"]
        with (patch("sys.argv", args),
              patch.dict(os.environ, {"RAG_QDRANT_G1_AUDIT_API_KEY": token}, clear=True),
              patch.object(command, "QdrantAuditClient", return_value=self.client),
              patch.object(command, "LockedTokenChunker", return_value=chunk_document),
              patch("sys.stdout", new_callable=StringIO) as output):
            self.assertEqual(command.main(), 1)
        printed = output.getvalue()
        self.assertIn("allowed_user_ids", printed)
        self.assertIn("21 champs inconnus", printed)
        self.assertNotIn("PRIVATE_TOKEN_abcd1234", printed)
        self.assertNotIn("0_extra_", printed)

class DivergenceRenderingTests(unittest.TestCase):
    """Index-controlled labels must never forge report lines on an operator's screen."""

    def hostile_plan(self, field: str) -> CanonicalIndexDivergence:
        return CanonicalIndexDivergence(
            expected_point_count=1, observed_point_count=1,
            missing_point_ids=(), unexpected_point_ids=(),
            divergent_points=((f"id\n\x1b[32m-faux", (field,)),),
        )

    def test_a_field_name_cannot_inject_lines_or_escapes(self):
        forged = "\n\x1b[32mPoints manquants dans l'index (0) :\nFAUX-SEMBLANT"
        lines = render_divergence_report(self.hostile_plan(forged))
        rendered = "\n".join(lines)
        self.assertNotIn("\x1b", rendered)
        self.assertNotIn("FAUX-SEMBLANT", rendered)
        # Header + three sections + the single entry: a payload key must not
        # be able to add a line, whatever it contains.
        self.assertEqual(len(lines), 5)
        self.assertTrue(all("\n" not in line for line in lines))
        self.assertIn("non imprimable", rendered)

    def test_an_overlong_field_name_is_replaced_not_truncated_into_nonsense(self):
        lines = render_divergence_report(self.hostile_plan("a" * 200))
        rendered = "\n".join(lines)
        self.assertNotIn("a" * 65, rendered)
        self.assertIn("non imprimable", rendered)

    def test_ordinary_names_and_ids_are_shown_verbatim(self):
        plan = CanonicalIndexDivergence(
            expected_point_count=2, observed_point_count=2,
            missing_point_ids=("11111111-1111-4111-8111-111111111111",),
            unexpected_point_ids=("22222222-2222-4222-8222-222222222222",),
            divergent_points=(("33333333-3333-4333-8333-333333333333",
                               ("acl_version", "allowed_user_ids")),),
        )
        rendered = "\n".join(render_divergence_report(plan))
        self.assertIn("11111111-1111-4111-8111-111111111111", rendered)
        self.assertIn("22222222-2222-4222-8222-222222222222", rendered)
        self.assertIn("acl_version, allowed_user_ids", rendered)
        self.assertNotIn("non imprimable", rendered)

    def test_unknown_fields_are_counted_without_printing_their_names(self):
        fields = tuple(f"0_extra_{index:03d}" for index in range(100)) + (
            "allowed_user_ids", "PRIVATE_TOKEN_abcd1234",
        )
        plan = CanonicalIndexDivergence(
            expected_point_count=1, observed_point_count=1,
            missing_point_ids=(), unexpected_point_ids=(),
            divergent_points=(("11111111-1111-4111-8111-111111111111", fields),),
        )
        lines = render_divergence_report(plan, max_entries=3)
        self.assertEqual(len(lines), 5)
        self.assertIn("allowed_user_ids", lines[-1])
        self.assertIn("101 champs inconnus", lines[-1])
        self.assertNotIn("0_extra", lines[-1])
        self.assertNotIn("PRIVATE_TOKEN", lines[-1])
        self.assertLess(len(lines[-1]), 300)

    def test_all_canonical_payload_fields_remain_visible(self):
        from rag_hermes import canonical_reconciliation as reconciliation
        canonical_fields = tuple(sorted(chunk_to_point(
            chunk_document(_document())[0], [1.0]
        )["payload"]))
        # Both directions: a retired field must not stay on the print
        # allowlist either, or an unknown Qdrant key could leak into logs.
        self.assertEqual(set(canonical_fields), reconciliation._CANONICAL_PAYLOAD_FIELDS)
        plan = CanonicalIndexDivergence(
            expected_point_count=1, observed_point_count=1,
            missing_point_ids=(), unexpected_point_ids=(),
            divergent_points=(("11111111-1111-4111-8111-111111111111", canonical_fields),),
        )
        printed = render_divergence_report(plan, max_entries=1)[-1]
        shown_fields = printed.split(" : ", 1)[1].split(", ")
        self.assertEqual(shown_fields, list(canonical_fields))
        self.assertLess(len(printed), 600)

    def test_the_number_of_printed_lines_is_bounded(self):
        many = tuple(f"00000000-0000-4000-8000-{index:012d}" for index in range(500))
        plan = CanonicalIndexDivergence(
            expected_point_count=0, observed_point_count=500,
            missing_point_ids=(), unexpected_point_ids=many, divergent_points=(),
        )
        lines = render_divergence_report(plan, max_entries=10)
        self.assertLess(len(lines), 40)
        self.assertIn("490", "\n".join(lines))
