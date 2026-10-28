"""One hourly run: check what paperless-gpt has finished with, fix it, raise decisions, maybe email."""
import datetime
import glob
import hashlib
import json
import os
import sys
from zoneinfo import ZoneInfo

from checker import digest
from checker.judge import JudgeError, UsageLimit, build_prompt, judge
from checker.paperless import PaperlessClient
from checker.plan import locked_fields, plan_changes
from checker.state import State

DIGEST_HOUR = 6
HASHED = ("title", "tags", "document_type", "correspondent", "created", "owner", "custom_fields")


def log(msg):
    print(msg, flush=True)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def fields_hash(doc):
    return _hash({k: sorted(doc.get(k) or []) if k == "tags" else doc.get(k) for k in HASHED})


def _read_log(path, since):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if not since or r["ts"] > since]


def check_document(client, judge_fn, state, d, ctx, dry):
    content = d.get("content") or ""
    chash = _hash(content)
    st = state.doc(d["id"])
    if st["content_hash"] == chash and st["fields_hash"] == fields_hash(d):
        return
    if not content.strip():
        log(f"{d['id']}: no OCR text, skipped")
        if not dry:
            state.mark_checked(d["id"], chash, fields_hash(d), st["changed_fields"], st["decisions"])
        return

    locked = locked_fields(client.history(d["id"]), ctx["hand"], st, chash)
    prompt = build_prompt(d, client.neighbours(d), ctx["rules"], ctx["names"], locked)
    proposal = judge_fn(prompt)
    patch, changes, decisions = plan_changes(
        d, proposal, names=ctx["names"], locked=locked, raised=set(st["decisions"]),
        person_users=ctx["person_users"], owner_default_id=ctx["owner_default"],
        amount_field_id=ctx["amount_field"], needs_decision_id=ctx["needs_decision"], today=ctx["today"])
    failed = ctx["failed"]
    if failed in (patch.get("tags") or d.get("tags") or []):
        # The checker has now classified it, so the "requeue failed" runbook mustn't undo that
        patch["tags"] = sorted(set(patch.get("tags") or d["tags"]) - {failed})

    for c in changes:
        log(f"{d['id']}: {c.field} {c.old!r} -> {c.new!r} ({c.reason})")
    for x in decisions:
        log(f"{d['id']}: decision [{x['key']}] {x['text']}")
    if dry:
        log(f"{d['id']}: dry run, would PATCH {sorted(patch)}")
        return

    if isinstance(patch.get("correspondent"), dict):
        name = patch["correspondent"]["create_correspondent"]
        patch["correspondent"] = client.create_correspondent(name)
        ctx["names"]["correspondents"][name] = patch["correspondent"]
    if patch:
        client.patch(d["id"], patch)
    ts = ctx["now"].isoformat()
    with open(ctx["log_path"], "a") as f:
        for c in changes:
            f.write(json.dumps({"ts": ts, "doc": d["id"], "title": d.get("title"), "field": c.field,
                                "old": c.old, "new": c.new, "reason": c.reason}, default=str) + "\n")
        f.flush()
    if changes:
        client.add_note(d["id"], "\n".join(f"checker: {c.field} {c.old} → {c.new}, because {c.reason}" for c in changes))
    for x in decisions:
        client.add_note(d["id"], f"checker decision [{x['key']}]: {x['text']}")

    after = client.document(d["id"]) or d
    changed = sorted(set(st["changed_fields"]) | {"tags" if c.field.startswith("tags_") else c.field for c in changes})
    state.mark_checked(d["id"], chash, fields_hash(after), changed, st["decisions"] + [x["key"] for x in decisions])


def maybe_digest(client, state, env, now, send_fn, needs_decision):
    if now.hour < DIGEST_HOUR or state.last_digest[:10] == now.date().isoformat():
        return
    log_path = env["CHANGES_LOG"]
    changes = _read_log(log_path, state.last_digest)
    everything = _read_log(log_path, "")
    open_decisions = []
    for d in client.tagged(needs_decision):
        notes = [n["note"] for n in client.notes(d["id"]) if n["note"].startswith("checker decision")]
        open_decisions.append({"doc": d["id"], "title": d.get("title"), "text": "\n".join(notes) or "Tagged needs-decision"})
    fields = {}
    for r in everything:
        fields[r["field"]] = fields.get(r["field"], 0) + 1
    tally = {"checked": len(state.docs), "changed": len({r["doc"] for r in everything}), "fields": fields}
    html = digest.build_digest(changes, open_decisions, tally, state.stopped, env["PAPERLESS_PUBLIC_URL"])
    if html:
        send_fn(html, digest.subject(changes, open_decisions))
    state.last_digest = now.isoformat()
    state.stopped = None


def run(client, judge_fn, state, env, now, send_fn):
    dry = bool(env.get("DRY_RUN"))
    names = {k: client.lookup(k) for k in ("tags", "document_types", "correspondents", "users")}
    tags = names["tags"]
    ctx = {
        "names": names, "rules": env["RULES"], "now": now, "today": now.date(), "log_path": env["CHANGES_LOG"],
        "hand": {u.strip() for u in env.get("HAND_EDITORS", "").split(",") if u.strip()},
        "person_users": {t: names["users"][u] for t, u in json.loads(env.get("PERSON_USERS", "{}")).items()},
        "owner_default": names["users"][env["OWNER_DEFAULT"]],
        "amount_field": client.lookup("custom_fields").get("Amount"),
        "needs_decision": tags["needs-decision"], "failed": tags.get("paperless-gpt-failed"),
    }
    cap = int(env.get("MAX_DOCS_PER_RUN", "20"))
    code = 0
    for listed in client.ready_documents(state.last_run, [tags["paperless-gpt-auto"]], cap):
        try:
            d = client.document(listed["id"])
            if d is None:
                log(f"{listed['id']}: gone, skipped")
            else:
                check_document(client, judge_fn, state, d, ctx, dry)
        except UsageLimit as e:
            log(f"stopping: {e}")
            state.stopped = f"usage limit reached ({e})"
            code = 2
            break
        except JudgeError as e:
            # Skip it rather than stop, or one bad document blocks every run; the digest lists it
            log(f"{listed['id']}: judge failed: {e}")
            code = 1
            if not dry:
                with open(ctx["log_path"], "a") as f:
                    f.write(json.dumps({"ts": now.isoformat(), "doc": listed["id"], "title": listed.get("title"),
                                        "field": "check-failed", "old": None, "new": str(e)[:200],
                                        "reason": "not checked; fix by hand or requeue it"}) + "\n")
        if dry:
            continue
        state.last_run = listed["modified"]
        state.save()
    if dry:
        return code
    maybe_digest(client, state, env, now, send_fn, ctx["needs_decision"])
    state.save()
    return code


def main():
    env = dict(os.environ)
    env.setdefault("CHANGES_LOG", "/data/changes.jsonl")
    env["RULES"] = "\n\n".join(open(p).read() for p in sorted(glob.glob(os.path.join(env.get("RULES_DIR", "/rules"), "*.tmpl"))))
    client = PaperlessClient(env["PAPERLESS_URL"], env["PAPERLESS_TOKEN"])
    state = State(env.get("STATE_PATH", "/data/state.json"))
    state.load()
    claude_bin = env.get("CLAUDE_BIN", "/data/claude/node_modules/.bin/claude")

    def send(html, subject):
        digest.send(html, host=env.get("SMTP_HOST", "smtp-relay.default.svc.cluster.local"),
                    port=int(env.get("SMTP_PORT", "25")), sender=env["DIGEST_FROM"], to=env["DIGEST_TO"], subject=subject)

    now = datetime.datetime.now(ZoneInfo(env.get("TZ", "Australia/Sydney")))
    return run(client, lambda p: judge(p, claude_bin=claude_bin), state, env, now, send)


if __name__ == "__main__":
    sys.exit(main())
