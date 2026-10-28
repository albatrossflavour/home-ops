import unittest

from checker.digest import build_digest, subject

BASE = "https://p.example"


def change(doc, field, old, new, title="Doc"):
    return {"ts": "2026-10-28T01:00:00Z", "doc": doc, "title": title, "field": field,
            "old": old, "new": new, "reason": "because"}


TALLY = {"checked": 3, "changed": 1, "fields": {"document_type": 1}}


class DigestTest(unittest.TestCase):
    def test_nothing_returns_none(self):
        self.assertIsNone(build_digest([], [], TALLY, None, BASE))

    def test_created_changes_listed_first(self):
        html = build_digest([change(1, "title", "a", "b", "First"), change(2, "created", "2026-01-01", "2026-02-01", "Second")],
                            [], TALLY, None, BASE)
        self.assertLess(html.index("Second"), html.index("First"))
        self.assertIn(f'href="{BASE}/documents/2/details"', html)

    def test_html_escapes_titles(self):
        html = build_digest([change(1, "title", "a", "b", "<script>x</script>")], [], TALLY, None, BASE)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_stop_notice_shown(self):
        html = build_digest([], [], TALLY, "usage limit reached", BASE)
        self.assertIn("usage limit reached", html)

    def test_decisions_listed(self):
        html = build_digest([], [{"doc": 5, "title": "Kit", "text": "Secret key in text"}], TALLY, None, BASE)
        self.assertIn("Secret key in text", html)
        self.assertIn("shadow period", html.lower())

    def test_subject(self):
        self.assertEqual(subject([change(1, "title", "a", "b"), change(1, "tags_add", None, "X")], [{"doc": 2}]),
                         "Paperless checker: 1 changed, 1 decisions")


if __name__ == "__main__":
    unittest.main()
