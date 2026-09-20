import json
import tempfile
import unittest
from pathlib import Path

from rag_hermes.dataset import documents_from_markdown, load_documents, load_questions


class DatasetTests(unittest.TestCase):
    def test_jsonl_loads_document_and_question_acl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "documents.jsonl"
            questions = root / "questions.jsonl"
            docs.write_text(json.dumps({
                "document_id": "d1", "content": "texte", "tenant_id": "a",
                "visibility": "private", "owner_id": "alice", "allowed_groups": ["admins"],
                "allowed_users": [], "classification": 2, "doc_version": 1,
                "source_uri": "vault://d1"
            }) + "\n", encoding="utf-8")
            questions.write_text(json.dumps({
                "case_id": "q1", "question": "texte ?", "tenant_id": "a",
                "user_id": "alice", "groups": ["admins"], "clearance": 2,
                "relevant_document_ids": ["d1"], "should_abstain": False
            }) + "\n", encoding="utf-8")

            loaded_docs = load_documents(docs)
            loaded_questions = load_questions(questions)
            self.assertEqual(loaded_docs[0].tenant_id, "a")
            self.assertEqual(loaded_questions[0].context.groups, ("admins",))
            self.assertEqual(loaded_questions[0].relevant_document_ids, ("d1",))

    def test_blank_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.jsonl"
            path.write_text("\n", encoding="utf-8")
            self.assertEqual(load_documents(path), [])

    def test_markdown_corpus_is_versioned_by_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide").mkdir()
            (root / "guide" / "install.md").write_text("# Installation\nTermux", encoding="utf-8")
            (root / "guide" / "models.mdx").write_text("# Modèles\nProviders", encoding="utf-8")
            documents = documents_from_markdown(root, commit="c" * 40)
            self.assertEqual(len(documents), 2)
            self.assertEqual(documents[0].tenant_id, "public")
            self.assertEqual(
                documents[0].source_uri,
                "git+https://github.com/NousResearch/hermes-agent.git@"
                + "c" * 40
                + "#website/docs/guide/install.md",
            )
            self.assertEqual(documents[0].document_id, "hermes-agent:guide/install.md")


if __name__ == "__main__":
    unittest.main()
