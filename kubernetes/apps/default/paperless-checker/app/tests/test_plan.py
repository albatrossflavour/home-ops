import datetime
import unittest

from checker.plan import locked_fields, plan_changes

NAMES = {
    "tags": {"Edward": 1, "Car": 2, "hit-by-a-bus-plan": 3, "needs-decision": 4,
             "paperless-gpt-auto": 5, "Home": 6},
    "document_types": {"Form": 10, "Manual": 11},
    "correspondents": {"1Password": 20},
    "users": {"tgreen": 4, "edward": 38},
}
TODAY = datetime.date(2026, 10, 28)


def doc(**kw):
    d = {"id": 1, "title": "T", "tags": [2, 6], "document_type": 11, "correspondent": 20, "owner": 4,
         "created": "2026-10-01", "content": "Issued 18/10/2026. Total $30.00", "custom_fields": []}
    d.update(kw)
    return d


def ch(field, value, reason="r", evidence=""):
    return {"field": field, "value": value, "reason": reason, "evidence": evidence}


def plan(d, changes=(), decisions=(), locked=None, raised=()):
    return plan_changes(d, {"changes": list(changes), "decisions": list(decisions)}, names=NAMES,
                        locked=locked or {}, raised=set(raised), person_users={"Edward": 38},
                        owner_default_id=4, amount_field_id=7, needs_decision_id=4, today=TODAY)


class PlanTest(unittest.TestCase):
    def test_locked_field_dropped(self):
        patch, changes, decisions = plan(doc(), [ch("title", "New")], locked={"title": "checker"})
        self.assertEqual((patch, changes, decisions), ({}, [], []))

    def test_hand_locked_field_becomes_decision(self):
        patch, _, decisions = plan(doc(), [ch("document_type", "Form")], locked={"document_type": "hand"})
        self.assertNotIn("document_type", patch)
        self.assertEqual(decisions[0]["key"], "hand-edit-document_type")
        self.assertEqual(sorted(patch["tags"]), [2, 4, 6])

    def test_unknown_names_dropped(self):
        patch, changes, _ = plan(doc(), [ch("tags_add", ["Nope"]), ch("document_type", "Nope")])
        self.assertEqual((patch, changes), ({}, []))

    def test_system_tags_not_accepted(self):
        patch, _, _ = plan(doc(), [ch("tags_add", ["paperless-gpt-auto", "needs-decision"])])
        self.assertEqual(patch, {})

    def test_needs_decision_tag_only_removed_by_people(self):
        patch, _, _ = plan(doc(tags=[2, 4, 6]), [ch("tags_remove", ["needs-decision"])])
        self.assertEqual(patch, {})

    def test_new_correspondent_marked_for_creation(self):
        patch, _, _ = plan(doc(), [ch("correspondent", "Service NSW")])
        self.assertEqual(patch["correspondent"], {"create_correspondent": "Service NSW"})

    def test_refuses_removing_every_tag(self):
        patch, changes, decisions = plan(doc(), [ch("tags_remove", ["Car", "Home"]), ch("title", "X")])
        self.assertEqual(changes, [])
        self.assertEqual(patch, {"tags": [2, 4, 6]})
        self.assertEqual([d["key"] for d in decisions], ["checker-refused"])

    def test_created_needs_evidence_in_content(self):
        ok, _, _ = plan(doc(), [ch("created", "2026-10-18", evidence="18/10/2026")])
        self.assertEqual(ok, {"created": "2026-10-18"})
        bad, _, _ = plan(doc(), [ch("created", "2026-10-18", evidence="10/12/1999")])
        self.assertEqual(bad, {})

    def test_created_range(self):
        for value in ("1990-12-31", "2026-10-29", "not-a-date"):
            p, _, _ = plan(doc(content="date " + value), [ch("created", value, evidence=value)])
            self.assertEqual(p, {}, value)

    def test_removing_person_tag_resets_owner(self):
        patch, _, _ = plan(doc(tags=[1, 2], owner=38), [ch("tags_remove", ["Edward"])])
        self.assertEqual(patch, {"tags": [2], "owner": 4})

    def test_adding_person_tag_leaves_owner_to_workflow(self):
        patch, _, _ = plan(doc(), [ch("tags_add", ["Edward"])])
        self.assertEqual(patch, {"tags": [1, 2, 6]})

    def test_amount_format(self):
        p, _, _ = plan(doc(custom_fields=[{"field": 5, "value": "x"}]), [ch("amount", "30.00")])
        self.assertEqual(p["custom_fields"], [{"field": 5, "value": "x"}, {"field": 7, "value": "AUD30.00"}])
        bad, _, _ = plan(doc(), [ch("amount", "$30")])
        self.assertEqual(bad, {})

    def test_decision_adds_tag_and_skips_raised(self):
        decisions = [{"key": "secret-in-ocr", "text": "a"}, {"key": "rego-due", "text": "b"}]
        patch, _, out = plan(doc(), decisions=decisions, raised={"secret-in-ocr"})
        self.assertEqual([d["key"] for d in out], ["rego-due"])
        self.assertEqual(patch, {"tags": [2, 4, 6]})
        patch, _, out = plan(doc(), decisions=decisions[:1], raised={"secret-in-ocr"})
        self.assertEqual((patch, out), ({}, []))

    def test_changes_record_old_and_new_names(self):
        _, changes, _ = plan(doc(), [ch("document_type", "Form", reason="kits are Form")])
        c = changes[0]
        self.assertEqual((c.field, c.old, c.new, c.reason), ("document_type", "Manual", "Form", "kits are Form"))


class LockedFieldsTest(unittest.TestCase):
    HISTORY = [
        {"action": "update", "actor": {"username": "tgreen"}, "changes": {"title": ["a", "b"]}},
        {"action": "update", "actor": {"username": "admin"}, "changes": {"tags": [[], [1]]}},
        {"action": "update", "actor": None, "changes": {"owner": [1, 2]}},
        {"action": "create", "actor": {"username": "tgreen"}, "changes": {"created": [None, "x"]}},
        {"action": "update", "actor": {"username": "dani"}, "changes": {"custom_fields": [[], [1]]}},
    ]

    def test_hand_edit_locks_field(self):
        got = locked_fields(self.HISTORY, {"tgreen", "dani"}, {"content_hash": None, "changed_fields": []}, "h")
        self.assertEqual(got, {"title": "hand", "amount": "hand"})

    def test_checker_change_locked_until_content_changes(self):
        state = {"content_hash": "h", "changed_fields": ["document_type"]}
        self.assertEqual(locked_fields([], set(), state, "h"), {"document_type": "checker"})
        self.assertEqual(locked_fields([], set(), state, "other"), {})


if __name__ == "__main__":
    unittest.main()
