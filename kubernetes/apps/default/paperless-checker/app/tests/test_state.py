import json
import os
import tempfile
import unittest
from unittest import mock

from checker.state import State


class StateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "state.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_roundtrip(self):
        s = State(self.path)
        s.load()
        self.assertEqual(s.doc(5)["decisions"], [])
        self.assertEqual(s.doc(5)["set_values"], {})
        s.last_run = "2026-10-28T00:00:00Z"
        self.assertTrue(s.fresh)
        s.mark_checked(5, "c", "f", {"title": "T"}, ["secret-in-ocr"])
        s.save()
        t = State(self.path)
        t.load()
        self.assertEqual(t.last_run, "2026-10-28T00:00:00Z")
        self.assertFalse(t.fresh)
        self.assertEqual(t.doc(5), {"content_hash": "c", "fields_hash": "f",
                                    "set_values": {"title": "T"}, "decisions": ["secret-in-ocr"]})

    def test_save_is_atomic(self):
        s = State(self.path)
        s.load()
        s.last_run = "first"
        s.save()
        s.last_run = "second"
        with mock.patch("checker.state.json.dump", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                s.save()
        with open(self.path) as f:
            self.assertEqual(json.load(f)["last_run"], "first")
        self.assertEqual(os.listdir(self.dir.name), ["state.json"])


if __name__ == "__main__":
    unittest.main()
