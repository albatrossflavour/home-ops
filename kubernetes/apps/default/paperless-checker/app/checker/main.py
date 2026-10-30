"""One hourly run: check what paperless-gpt has finished with, fix it, raise decisions, maybe email."""
import datetime
import glob
import hashlib
import json
import os
import sys
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

from checker import digest
from checker.judge import JudgeError, StopRun, UsageLimit, build_prompt, judge
from checker.paperless import PaperlessClient
from checker.plan import Change, current_values, is_system_tag, locked_fields, plan_changes
from checker.state import State

DIGEST_HOUR = 6
HASHED = ("title", "tags", "document_type", "correspondent", "created", "owner", "custom_fields")


def log(msg):
    print(msg, flush=True)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def fields_hash(doc, ctx):
    # System tags are left out, so closing a decision (removing needs-decision) doesn't trigger a recheck
    return _hash(current_values(doc, ctx["system_tags"], ctx["amount_field"]))


def _read_log(path, since):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if not since or r["ts"] > since]


_LOG_LOCK = threading.Lock()


def _write_log(ctx, doc, rows):
    ts = ctx["now"].isoformat()
    with _LOG_LOCK, open(ctx["log_path"], "a") as f:
        for field, old, new, reason in rows:
            f.write(json.dumps({"ts": ts, "doc": doc["id"], "title": doc.get("title"), "field": field,
                                "old": old, "new": new, "reason": reason}, default=str) + "\n")
        f.flush()


def check_document(client, judge_fn, state, d, ctx, dry):
    content = d.get("content") or ""
    chash = _hash(content)
    st = state.doc(d["id"])
    if st["content_hash"] == chash and st["fields_hash"] == fields_hash(d, ctx):
        return
    if not content.strip():
        log(f"{d['id']}: no OCR text, skipped")
        if not dry:
            state.mark_checked(d["id"], chash, fields_hash(d, ctx), st["set_values"], st["decisions"])
        return

    current = current_values(d, ctx["system_tags"], ctx["amount_field"])
    locked = locked_fields(client.history(d["id"]), ctx["hand"], st, current, ctx["system_tag_names"],
                           ctx["system_tags"], ctx["hand_since"])
    prompt = build_prompt(d, client.neighbours(d), ctx["rules"], ctx["names"], locked,
                          raised=st["decisions"], amount_field_id=ctx["amount_field"],
                          old=_older_than_a_month(d.get("created"), ctx["today"]))
    proposal = judge_fn(prompt)
    # Same text as when decisions were last raised: anything "new" is the same point reworded
    allow_new = not (st["decisions"] and st["content_hash"] == chash)
    patch, changes, decisions = plan_changes(
        d, proposal, names=ctx["names"], locked=locked, raised=set(st["decisions"]),
        person_users=ctx["person_users"], owner_default_id=ctx["owner_default"],
        amount_field_id=ctx["amount_field"], needs_decision_id=ctx["needs_decision"], today=ctx["today"],
        allow_new_decisions=allow_new)
    failed = ctx["failed"]
    if failed in (patch.get("tags") or d.get("tags") or []):
        # The checker has now classified it, so the "requeue failed" runbook mustn't undo that
        patch["tags"] = sorted(set(patch.get("tags") or d["tags"]) - {failed})
        changes.append(Change("tags_remove", "paperless-gpt-failed", None, "the checker classified it instead"))

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
    # From here the change is made, so record it whatever happens to the notes
    _write_log(ctx, d, [(c.field, c.old, c.new, c.reason) for c in changes])
    notes = []
    if changes:
        notes.append("\n".join(f"checker: {c.field} {c.old} → {c.new}, because {c.reason}" for c in changes))
    notes += [f"checker decision [{x['key']}]: {x['text']}" for x in decisions]
    for note in notes:
        try:
            client.add_note(d["id"], note)
        except (urllib.error.URLError, OSError) as e:
            log(f"{d['id']}: note failed: {e}")
    try:
        after = client.document(d["id"]) or dict(d, **patch)
    except (urllib.error.URLError, OSError):
        after = dict(d, **patch)
    after_values = current_values(after, ctx["system_tags"], ctx["amount_field"])
    set_values = dict(st["set_values"])
    for c in changes:
        field = "tags" if c.field.startswith("tags_") else c.field
        set_values[field] = after_values.get(field)
    state.mark_checked(d["id"], chash, fields_hash(after, ctx), set_values, st["decisions"] + [x["key"] for x in decisions])


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


def _older_than_a_month(created, today):
    """Old documents get fixed without reminders or questions; a missing or odd date counts as new."""
    try:
        return datetime.date.fromisoformat((created or "")[:10]) < today - datetime.timedelta(days=30)
    except ValueError:
        return False


def _fatal(e):
    """Errors that end the run rather than skip one document."""
    if isinstance(e, urllib.error.HTTPError):
        return e.code == 401 or e.code >= 500
    return isinstance(e, (StopRun, urllib.error.URLError, OSError))


def run(client, judge_fn, state, env, now, send_fn):
    dry = bool(env.get("DRY_RUN"))
    names = {k: client.lookup(k) for k in ("tags", "document_types", "correspondents", "users")}
    tags = names["tags"]
    ctx = {
        "names": names, "rules": env["RULES"], "now": now, "today": now.date(), "log_path": env["CHANGES_LOG"],
        "hand_since": env.get("HAND_EDITS_SINCE", ""),
        "hand": {u.strip() for u in env.get("HAND_EDITORS", "").split(",") if u.strip()},
        "person_users": {t: names["users"][u] for t, u in json.loads(env.get("PERSON_USERS", "{}")).items()},
        "owner_default": names["users"][env["OWNER_DEFAULT"]],
        "amount_field": client.lookup("custom_fields").get("Amount"),
        "needs_decision": tags["needs-decision"], "failed": tags.get("paperless-gpt-failed"),
    }
    ctx["system_tag_names"] = {n for n in tags if is_system_tag(n)}
    ctx["system_tags"] = {tags[n] for n in ctx["system_tag_names"]}
    if state.fresh and not state.last_run_set():
        # First run: start from CHECK_SINCE (or now), never the back catalogue
        state.last_run = env.get("CHECK_SINCE") or now.isoformat()
    cap = int(env.get("MAX_DOCS_PER_RUN", "20"))
    workers = int(env.get("WORKERS", "1"))

    def attempt(listed):
        try:
            d = client.document(listed["id"])
            if d is None:
                log(f"{listed['id']}: gone, skipped")
            else:
                check_document(client, judge_fn, state, d, ctx, dry)
        except Exception as e:
            # Record a skipped document straight away so the log stays in the order documents finished
            if not dry and isinstance(e, JudgeError):
                _write_log(ctx, listed, [("check-failed", None, str(e)[:200], "not checked; fix by hand or requeue it")])
            elif not dry and isinstance(e, urllib.error.HTTPError) and not _fatal(e):
                _write_log(ctx, listed, [("check-failed", None, f"paperless {e.code}", "not checked; fix by hand or requeue it")])
            return e
        return None

    # Check a wave of documents at once, then settle them in order so the cursor only passes finished ones.
    # Docs after a stop in the same wave may already be done; the hashes skip them next run.
    listed_docs = client.ready_documents(state.last_run, [tags["paperless-gpt-auto"]], cap)
    outcomes = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i in range(0, len(listed_docs), workers):
            wave = listed_docs[i:i + workers]
            results = list(pool.map(attempt, wave))
            outcomes += zip(wave, results)
            if any(r is not None and _fatal(r) for r in results):
                break
    code = 0
    for listed, err in outcomes:
        try:
            if err:
                raise err
        except StopRun as e:
            log(f"stopping: {e}")
            state.stopped = f"usage limit reached ({e})" if isinstance(e, UsageLimit) else str(e)
            code = 2
            break
        except urllib.error.HTTPError as e:
            if e.code == 401 or e.code >= 500:
                log(f"stopping: paperless returned {e.code}")
                state.stopped = f"paperless returned {e.code}"
                code = 2
                break
            # A 4xx about this one document: skip it rather than block every later run
            log(f"{listed['id']}: paperless refused ({e.code}): {e}")
            code = 1
        except (urllib.error.URLError, OSError) as e:
            log(f"stopping: can't reach paperless: {e}")
            state.stopped = f"couldn't reach paperless ({e})"
            code = 2
            break
        except JudgeError as e:
            # Skip it rather than stop, or one bad document blocks every run; the digest lists it
            log(f"{listed['id']}: judge failed: {e}")
            code = 1
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
