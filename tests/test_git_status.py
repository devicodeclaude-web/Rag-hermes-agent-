from __future__ import annotations

import unittest

from rag_hermes.git_status import working_tree_dirty_excluding


class WorkingTreeDirtyExcludingTests(unittest.TestCase):
    def test_clean_tree_is_not_dirty(self):
        self.assertFalse(working_tree_dirty_excluding("", excluded=("data/results/report.json",)))

    def test_only_excluded_outputs_changed_is_not_dirty(self):
        porcelain = (
            " D data/results/report.json\n"
            " D data/results/report.sha256\n"
        )
        self.assertFalse(
            working_tree_dirty_excluding(
                porcelain,
                excluded=(
                    "data/results/report.json",
                    "data/results/report.sha256",
                ),
            )
        )

    def test_unrelated_modified_file_is_dirty(self):
        porcelain = (
            " D data/results/report.json\n"
            " M rag_hermes/retrieval.py\n"
        )
        self.assertTrue(
            working_tree_dirty_excluding(
                porcelain, excluded=("data/results/report.json",)
            )
        )

    def test_untracked_file_outside_excluded_is_dirty(self):
        porcelain = "?? AUDIT/preuves/new/\n"
        self.assertTrue(
            working_tree_dirty_excluding(
                porcelain, excluded=("data/results/report.json",)
            )
        )

    def test_rename_is_dirty_unless_both_endpoints_excluded(self):
        # porcelain v1 rename: "R  old -> new". A rename touches two paths; it
        # is ignorable only if BOTH endpoints are excluded outputs.
        porcelain = "R  data/results/old.json -> data/results/report.json\n"
        self.assertTrue(
            working_tree_dirty_excluding(
                porcelain, excluded=("data/results/report.json",)
            )
        )
        self.assertFalse(
            working_tree_dirty_excluding(
                porcelain,
                excluded=(
                    "data/results/old.json",
                    "data/results/report.json",
                ),
            )
        )


    def test_blank_lines_are_ignored(self):
        self.assertFalse(
            working_tree_dirty_excluding(
                "\n  \n", excluded=()
            )
        )


if __name__ == "__main__":
    unittest.main()
