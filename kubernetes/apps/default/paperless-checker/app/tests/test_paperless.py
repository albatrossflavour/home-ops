import inspect
import io
import json
import unittest
import urllib.error
import urllib.parse

from checker.paperless import PaperlessClient


class FakeOpener:
    """Records requests and answers from a {path-prefix: (status, body)} map."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        url = urllib.parse.urlsplit(req.full_url)
        for prefix, (status, body) in self.routes.items():
            if url.path.startswith(prefix):
                if status >= 400:
                    raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(b""))
                return io.BytesIO(json.dumps(body).encode())
        raise AssertionError(f"unexpected request {req.full_url}")


class PaperlessClientTest(unittest.TestCase):
    def test_no_delete_method(self):
        self.assertFalse(hasattr(PaperlessClient, "delete"))
        self.assertNotIn("DELETE", inspect.getsource(PaperlessClient))

    def test_neighbours_strips_trailing_date(self):
        opener = FakeOpener({"/api/documents/": (200, {"next": None, "results": [
            {"id": 7, "title": "self"}, {"id": 8, "title": "other"}]})})
        client = PaperlessClient("http://p", "t", opener=opener)
        got = client.neighbours({"id": 7, "title": "Transport for NSW Registration - ABC123 2026-10"})
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(opener.requests[0].full_url).query)
        self.assertEqual(query["query"], ["Transport for NSW Registration - ABC123"])
        self.assertEqual([d["id"] for d in got], [8])

    def test_document_404_returns_none(self):
        client = PaperlessClient("http://p", "t", opener=FakeOpener({"/api/documents/9/": (404, None)}))
        self.assertIsNone(client.document(9))


if __name__ == "__main__":
    unittest.main()
