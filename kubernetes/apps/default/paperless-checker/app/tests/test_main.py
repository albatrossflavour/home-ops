import datetime
import json
import os
import tempfile
import unittest
from zoneinfo import ZoneInfo

from checker.judge import UsageLimit
from checker.main import run
from checker.state import State

SYD = ZoneInfo("Australia/Sydney")
TAGS = {"paperless-gpt-auto": 1, "paperless-gpt-failed": 2, "needs-decision": 3, "Edward": 4, "Car": 5, "Home": 6}


class FakeClient:
    def __init__(self, n=1, content="Some text"):
        self.docs = {i: {"id": i, "title": f"Doc {i}", "tags": [5, 6], "document_type": 11, "correspondent": 20,
                         "owner": 9, "created": "2026-10-01", "content": content, "custom_fields": [],
                         "modified": f"2026-10-28T00:{i:02d}:00+11:00"} for i in range(1, n + 1)}
        self.patches, self.notes_added = [], []

    def lookup(self, kind):
        return {"tags": TAGS, "document_types": {"Form": 10, "Manual": 11}, "correspondents": {"1Password": 20},
                "users": {"tgreen": 9, "edward": 38}, "custom_fields": {"Amount": 7}}[kind]

    def ready_documents(self, since, exclude_tag_ids, limit):
        ready = sorted((d for d in self.docs.values() if d["modified"] > since and not set(d["tags"]) & set(exclude_tag_ids)),
                       key=lambda d: d["modified"])
        return [dict(d) for d in ready[:limit]]

    def document(self, doc_id):
        d = self.docs.get(doc_id)
        return dict(d) if d else None

    def neighbours(self, doc, n=5):
        return []

    def history(self, doc_id):
        return []

    def patch(self, doc_id, fields):
        self.patches.append((doc_id, fields))
        self.docs[doc_id].update(fields)
        return self.docs[doc_id]

    def add_note(self, doc_id, text):
        self.notes_added.append((doc_id, text))

    def create_correspondent(self, name):
        return 99

    def tagged(self, tag_id):
        return [dict(d) for d in self.docs.values() if tag_id in d["tags"]]

    def notes(self, doc_id):
        return [{"note": t} for i, t in self.notes_added if i == doc_id]


def proposal(changes=(), decisions=()):
    return {"changes": list(changes), "decisions": list(decisions)}


class Judge:
    def __init__(self, answers=None, raise_on=None):
        self.calls, self.answers, self.raise_on = 0, answers or {}, raise_on

    def __call__(self, prompt):
        self.calls += 1
        if self.raise_on == self.calls:
            raise UsageLimit("usage limit")
        return self.answers.get(self.calls, proposal([{"field": "document_type", "value": "Form",
                                                         "reason": "r", "evidence": ""}]))


class RunTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = State(os.path.join(self.dir.name, "state.json"))
        self.state.load()
        self.sent = []
        self.env = {"MAX_DOCS_PER_RUN": "20", "HAND_EDITORS": "tgreen,dani", "PERSON_USERS": json.dumps({"Edward": "edward"}),
                    "OWNER_DEFAULT": "tgreen", "PAPERLESS_PUBLIC_URL": "https://p", "RULES": "rules",
                    "CHANGES_LOG": os.path.join(self.dir.name, "changes.jsonl")}

    def tearDown(self):
        self.dir.cleanup()

    def go(self, client, judge, hour=3, **env):
        now = datetime.datetime(2026, 10, 29, hour, 5, tzinfo=SYD)
        return run(client, judge, self.state, dict(self.env, **env), now,
                   lambda html, subject: self.sent.append((subject, html)))

    def test_cap_and_oldest_first(self):
        client = FakeClient(25)
        self.assertEqual(self.go(client, Judge(), MAX_DOCS_PER_RUN="20"), 0)
        self.assertEqual([p[0] for p in client.patches], list(range(1, 21)))
        self.assertEqual(self.state.last_run, client.docs[20]["modified"])

    def test_usage_limit_keeps_done_docs(self):
        client = FakeClient(5)
        self.assertEqual(self.go(client, Judge(raise_on=3)), 2)
        self.assertEqual([p[0] for p in client.patches], [1, 2])
        saved = State(self.state.path)
        saved.load()
        self.assertEqual(saved.last_run, client.docs[2]["modified"])
        self.assertIn("1", saved.docs)
        self.assertIn("usage limit", saved.stopped)

    def test_judge_error_skips_doc_and_reports_it(self):
        from checker.judge import JudgeError
        client = FakeClient(3)
        judge = Judge()
        inner = judge.__call__

        def flaky(prompt):
            if judge.calls == 0:
                judge.calls += 1
                raise JudgeError("bad output")
            return inner(prompt)
        self.assertEqual(self.go(client, flaky), 1)
        self.assertEqual([p[0] for p in client.patches], [2, 3])
        with open(self.env["CHANGES_LOG"]) as f:
            rows = [json.loads(line) for line in f]
        self.assertEqual((rows[0]["doc"], rows[0]["field"]), (1, "check-failed"))

    def test_deleted_doc_skipped(self):
        client = FakeClient(2)
        client.document = lambda i: None if i == 1 else dict(client.docs[i])
        self.assertEqual(self.go(client, Judge()), 0)
        self.assertEqual([p[0] for p in client.patches], [2])

    def test_empty_content_skips_judge(self):
        judge = Judge()
        self.go(FakeClient(1, content="   "), judge)
        self.assertEqual(judge.calls, 0)

    def test_own_edit_not_rechecked(self):
        client = FakeClient(1)
        judge = Judge()
        self.go(client, judge)
        client.docs[1]["modified"] = "2026-10-28T09:00:00+11:00"  # our own PATCH bumped it
        self.go(client, judge)
        self.assertEqual(judge.calls, 1)

    def test_change_logged_and_noted(self):
        client = FakeClient(1)
        self.go(client, Judge())
        with open(self.env["CHANGES_LOG"]) as f:
            line = json.loads(f.readline())
        self.assertEqual((line["doc"], line["field"], line["old"], line["new"]), (1, "document_type", "Manual", "Form"))
        self.assertTrue(client.notes_added[0][1].startswith("checker: document_type"))

    def test_decision_not_reraised(self):
        client = FakeClient(1)
        decide = proposal(decisions=[{"key": "secret-in-ocr", "text": "A secret key is in the text"}])
        self.go(client, Judge({1: decide}))
        client.docs[1]["tags"].remove(3)  # Tony deals with it
        client.docs[1]["content"] = "changed text"
        self.go(client, Judge({1: decide}))
        decision_notes = [t for _, t in client.notes_added if t.startswith("checker decision")]
        self.assertEqual(len(decision_notes), 1)
        self.assertNotIn(3, client.docs[1]["tags"])

    def test_dry_run_changes_nothing(self):
        client = FakeClient(2)
        self.go(client, Judge(), DRY_RUN="1")
        self.assertEqual((client.patches, client.notes_added), ([], []))
        self.assertFalse(os.path.exists(self.state.path))

    def test_failed_tag_removed_when_checked(self):
        client = FakeClient(1)
        client.docs[1]["tags"] = [2, 5, 6]
        self.go(client, Judge({1: proposal()}))
        self.assertNotIn(2, client.docs[1]["tags"])

    def test_digest_once_after_six(self):
        client = FakeClient(1)
        self.go(client, Judge(), hour=5)
        self.assertEqual(self.sent, [])
        self.go(client, Judge(), hour=6)
        self.go(client, Judge(), hour=7)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Doc 1", self.sent[0][1])


if __name__ == "__main__":
    unittest.main()
