"""Turn Claude's proposal into a PATCH body. Pure: no I/O, so every guard is testable."""
import datetime
import re
from dataclasses import dataclass

# Audit-log change keys, as the field names a proposal uses
HISTORY_FIELDS = {"title": "title", "tags": "tags", "document_type": "document_type",
                  "correspondent": "correspondent", "created": "created", "custom_fields": "amount",
                  "owner": "owner"}
PROPOSAL_FIELD = {"tags_add": "tags", "tags_remove": "tags"}
EARLIEST = datetime.date(1991, 1, 1)
AMOUNT = re.compile(r"^\d+(\.\d{2})?$")
KEY = re.compile(r"^[a-z0-9-]{3,40}$")


@dataclass
class Change:
    field: str
    old: object
    new: object
    reason: str


def locked_fields(history, hand_editors, doc_state, content_hash):
    """Fields the checker must leave alone: 'hand' if a person edited it, 'checker' if we already did."""
    locked = {}
    for entry in history:
        actor = (entry.get("actor") or {}).get("username")
        if entry.get("action") == "update" and actor in hand_editors:
            for key in entry.get("changes") or {}:
                if key in HISTORY_FIELDS:
                    locked[HISTORY_FIELDS[key]] = "hand"
    if doc_state.get("content_hash") == content_hash:
        for f in doc_state.get("changed_fields", []):
            locked.setdefault(f, "checker")
    return locked


def _iso(value, today):
    try:
        d = datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return d if EARLIEST <= d <= today else None


def plan_changes(doc, proposal, *, names, locked, raised, person_users, owner_default_id,
                 amount_field_id, needs_decision_id, today):
    tag_ids = names["tags"]
    tag_names = {v: k for k, v in tag_ids.items()}
    applicable = {n for n in tag_ids if not n.startswith("paperless-gpt") and n != "needs-decision"}
    type_names = {v: k for k, v in names["document_types"].items()}
    corr_names = {v: k for k, v in names["correspondents"].items()}

    cur_tags = set(doc.get("tags") or [])
    new_tags = set(cur_tags)
    patch, changes, decisions = {}, [], []

    for c in proposal.get("changes", []):
        field, value, reason = c.get("field"), c.get("value"), c.get("reason", "")
        lock = locked.get(PROPOSAL_FIELD.get(field, field))
        if lock:
            if lock == "hand":
                decisions.append({"key": f"hand-edit-{PROPOSAL_FIELD.get(field, field)}",
                                  "text": f"The checker would change {field} to {value}, but a person set it: {reason}"})
            continue
        if field in ("tags_add", "tags_remove"):
            for name in value if isinstance(value, list) else [value]:
                if name not in applicable:
                    continue
                tid = tag_ids[name]
                if field == "tags_add" and tid not in new_tags:
                    new_tags.add(tid)
                    changes.append(Change("tags_add", None, name, reason))
                elif field == "tags_remove" and tid in new_tags:
                    new_tags.discard(tid)
                    changes.append(Change("tags_remove", name, None, reason))
        elif field == "title" and isinstance(value, str) and value.strip() and value != doc.get("title"):
            patch["title"] = value.strip()
            changes.append(Change("title", doc.get("title"), patch["title"], reason))
        elif field == "document_type" and value in names["document_types"]:
            if names["document_types"][value] != doc.get("document_type"):
                patch["document_type"] = names["document_types"][value]
                changes.append(Change("document_type", type_names.get(doc.get("document_type")), value, reason))
        elif field == "correspondent" and isinstance(value, str) and value.strip():
            cid = names["correspondents"].get(value)
            if cid is None:
                patch["correspondent"] = {"create_correspondent": value.strip()}
            elif cid != doc.get("correspondent"):
                patch["correspondent"] = cid
            else:
                continue
            changes.append(Change("correspondent", corr_names.get(doc.get("correspondent")), value, reason))
        elif field == "created":
            d, evidence = _iso(value, today), c.get("evidence", "")
            if d and evidence and evidence in (doc.get("content") or "") and value != doc.get("created"):
                patch["created"] = value
                changes.append(Change("created", doc.get("created"), value, reason))
        elif field == "amount" and isinstance(value, str) and AMOUNT.match(value):
            fields = [f for f in doc.get("custom_fields") or [] if f.get("field") != amount_field_id]
            old = next((f.get("value") for f in doc.get("custom_fields") or [] if f.get("field") == amount_field_id), None)
            if old != f"AUD{value}":
                patch["custom_fields"] = fields + [{"field": amount_field_id, "value": f"AUD{value}"}]
                changes.append(Change("amount", old, f"AUD{value}", reason))

    if len(cur_tags) >= 2 and not new_tags:
        # Stripping every tag is what an injected instruction looks like; refuse the lot
        patch, changes, new_tags = {}, [], set(cur_tags)
        decisions = [{"key": "checker-refused",
                      "text": "The checker was asked to remove every tag from this document and refused. Check it by hand."}]

    for d in proposal.get("decisions", []):
        if KEY.match(str(d.get("key", ""))):
            decisions.append({"key": d["key"], "text": d.get("text", "")})
    seen, fresh = set(raised), []
    for d in decisions:
        if d["key"] not in seen:
            seen.add(d["key"])
            fresh.append(d)
    if fresh:
        new_tags.add(needs_decision_id)

    for tag_name, user_id in person_users.items():
        tid = tag_ids.get(tag_name)
        if tid in cur_tags and tid not in new_tags and doc.get("owner") == user_id:
            patch["owner"] = owner_default_id
            user_names = {v: k for k, v in names.get("users", {}).items()}
            changes.append(Change("owner", user_names.get(user_id, user_id),
                                  user_names.get(owner_default_id, owner_default_id), f"{tag_name} tag removed"))

    if new_tags != cur_tags:
        patch["tags"] = sorted(new_tags)
    return patch, changes, fresh
