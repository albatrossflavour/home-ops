"""The daily email: what changed, what's waiting on a decision, and the shadow-period tally."""
import smtplib
from collections import OrderedDict
from email.message import EmailMessage
from html import escape

FIELD_LABELS = {"created": "Created date", "title": "Title", "tags_add": "Tag added", "tags_remove": "Tag removed",
                "document_type": "Type", "correspondent": "Correspondent", "owner": "Owner", "amount": "Amount", "check-failed": "Couldn't check"}
CSS = ("body{font-family:-apple-system,Segoe UI,sans-serif;max-width:640px;margin:0 auto;padding:16px;color:#1d1d1f}"
       "h2{font-size:18px;margin:24px 0 8px}a{color:#0a58ca}"
       ".doc{border:1px solid #ddd;border-radius:8px;padding:10px 12px;margin:8px 0}"
       ".row{margin:4px 0;font-size:14px}.old{color:#a33;text-decoration:line-through}.new{color:#176b2c}"
       ".why{color:#666;font-size:13px}.stop{background:#fff3cd;padding:10px;border-radius:8px}"
       ".tally{color:#666;font-size:13px;margin-top:24px}")


def _fmt(v):
    return "(none)" if v in (None, "", []) else escape(str(v))


def _link(base, doc, title):
    return f'<a href="{escape(base)}/documents/{int(doc)}/details">{escape(title or str(doc))}</a>'


def subject(changes, decisions):
    return f"Paperless checker: {len({c['doc'] for c in changes})} changed, {len(decisions)} decisions"


def build_digest(changes, open_decisions, tally, stopped_reason, base_url):
    if not changes and not open_decisions and not stopped_reason:
        return None
    # Created-date changes first: they can move a document between tax years
    by_doc = OrderedDict()
    for c in sorted(changes, key=lambda c: c["field"] != "created"):
        by_doc.setdefault(c["doc"], []).append(c)

    out = [f"<html><head><meta name='viewport' content='width=device-width'><style>{CSS}</style></head><body>"]
    if stopped_reason:
        out.append(f"<p class='stop'>The checker stopped early: {escape(stopped_reason)}. It carries on next run.</p>")
    if by_doc:
        out.append(f"<h2>Changed ({len(by_doc)} documents)</h2>")
        for doc, rows in by_doc.items():
            out.append(f"<div class='doc'>{_link(base_url, doc, rows[0].get('title'))}")
            for c in rows:
                out.append(f"<div class='row'><b>{escape(FIELD_LABELS.get(c['field'], c['field']))}</b>: "
                           f"<span class='old'>{_fmt(c['old'])}</span> → <span class='new'>{_fmt(c['new'])}</span>"
                           f"<div class='why'>{escape(c.get('reason', ''))}</div></div>")
            out.append("</div>")
    if open_decisions:
        out.append(f"<h2>Waiting on you ({len(open_decisions)})</h2>")
        for d in open_decisions:
            out.append(f"<div class='doc'>{_link(base_url, d['doc'], d.get('title'))}"
                       f"<div class='row'>{escape(d.get('text', ''))}</div></div>")
    fields = ", ".join(f"{escape(FIELD_LABELS.get(k, k))} {v}" for k, v in sorted(tally.get("fields", {}).items()))
    out.append(f"<p class='tally'>Shadow period so far: {tally.get('checked', 0)} checked, "
               f"{tally.get('changed', 0)} changed{': ' + fields if fields else ''}.</p></body></html>")
    return "".join(out)


def send(html, *, host, port, sender, to, subject):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content("This summary is HTML. Open it in a mail client that shows HTML.")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.send_message(msg)
