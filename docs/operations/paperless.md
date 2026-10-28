# Paperless

paperless-ngx (`kubernetes/apps/default/paperless`) stores the documents. paperless-gpt (`kubernetes/apps/default/paperless-gpt`) classifies them with Claude: title, tags, correspondent and document type.

## How a document gets classified

1. paperless-ngx consumes a document. A paperless workflow named `paperless-gpt` adds the `paperless-gpt-auto` tag.
2. paperless-gpt polls for that tag, sends the OCR text to Claude once per field, writes the results back, and swaps the tag for `paperless-gpt-auto-complete`.
3. After three failed attempts it applies `paperless-gpt-failed` and stops retrying.

paperless-ngx's own auto-matching is set to "None" on every tag. If it's left on, the built-in classifier and paperless-gpt both write tags and fight each other.

## Where the configuration lives

| What | Where | Why there |
| --- | --- | --- |
| Behaviour settings (model, which fields to generate, no new tags, created date left alone) | `paperless-gpt/app/helmrelease.yaml`, plain env | Not secret, so changes diff readably in a PR |
| Prompt templates | `paperless-gpt/app/prompts.sops.yaml` | SOPS-encrypted because the rules contain personal detail |
| Anthropic key, paperless API token | 1Password, via `paperless-gpt/app/externalsecret.yaml` | Keys stay in 1Password |
| Custom field selection, undo history | `/app/config` and `/app/db` on the `paperless-gpt` PVC | Written by the app; volsync backs it up |

An init container copies the templates from the Secret into `/app/prompts` on every start. Git is the source of truth. **Edits made in paperless-gpt's web UI are lost on the next restart.**

## Editing a prompt

```bash
sops kubernetes/apps/default/paperless-gpt/app/prompts.sops.yaml
```

The file holds `title_prompt.tmpl`, `tag_prompt.tmpl`, `correspondent_prompt.tmpl` and `document_type_prompt.tmpl` as Go `text/template`. Fields not overridden use paperless-gpt's defaults.

PR diffs of the encrypted file are unreadable, so review a change locally before shipping:

```bash
diff <(git show main:kubernetes/apps/default/paperless-gpt/app/prompts.sops.yaml | sops -d --input-type yaml --output-type yaml /dev/stdin) \
     <(sops -d kubernetes/apps/default/paperless-gpt/app/prompts.sops.yaml)
```

Things learned the hard way:

- Never ask the model to reason inside `<think>` tags or say the reasoning is thrown away. The API refuses the request outright (`stop_reason: refusal`, no content), paperless-gpt treats that as an empty answer, and documents get their correspondent, type and tags wiped while being marked complete. This happened to 663 documents on 2026-10-20. Prompts end with "Do not show any working or reasoning" instead. That still leaks reasoning occasionally (57 of about 6,200 titles), so check titles after a big reprocess.
- Leaked reasoning comes from rules that seem to conflict with the document in front of the model: a business named after a person, an unreadable issuer, "registration" meaning an event. Spell out each edge case in the prompt and tell it a best guess beats an explanation. That took a set of 8 leaking documents to 0.
- Sonnet 5.5 reasons in a separate thinking block on hard documents (about 500 tokens). That's invisible to paperless-gpt and is part of why a document costs about 2.6 cents.
- Before shipping a prompt change, send it to the API by hand against a couple of real documents and check `stop_reason` is `end_turn`.
- `sops -d` re-indents block scalars. Scripted edits against decrypted output need to match the decrypted indentation, not the source file's.
- A case-insensitive grep for a short word can match base64 ciphertext. Check a hit before assuming plaintext leaked.

Ship with `ship` like any other change. Reloader restarts the pod when the Secret changes; confirm with:

```bash
kubectl -n default exec deploy/paperless-gpt -c app -- head -5 /app/prompts/tag_prompt.tmpl
```

## Reprocessing documents

Add `paperless-gpt-auto` to a document and paperless-gpt picks it up within a poll cycle. It processes about one document every 25 seconds.

Existing tags aren't cleared first. For a clean re-tag, replace the document's tags with just `paperless-gpt-auto`, and take a snapshot of the old values first so they can be put back.

## Reaching the web UI

There's no ingress. The UI has no authentication and can rewrite any document.

```bash
kubectl -n default port-forward svc/paperless-gpt 8080:8080
```

The manual review queue is the `paperless-gpt` tag: documents with it wait in the UI for approval instead of being written straight back.

## When a correspondent comes through blank

Correspondents are restricted to existing names in practice, because the prompt prefers the list. A new organisation sometimes comes through without one. Add it in paperless and reprocess the document.

## Landmines

- **Deleting a parent tag deletes its children.** Deleting a tag that a workflow filters on leaves the workflow's filter empty, so it matches every document. Check `children` and every workflow's `filter_has_tags` before deleting tags, and disable affected workflows first.
- **The Anthropic key must be scoped to a workspace.** An unscoped key fails every request with `This API key is not scoped to a workspace ... must include the anthropic-workspace-id header`, and paperless-gpt can't send that header.

## Second-pass checker

`kubernetes/apps/default/paperless-checker` runs hourly at five past. It re-checks every document paperless-gpt has finished with since its last run, compares it with the house rules (the same `paperless-gpt-prompts` Secret, mounted at `/rules`) and the closest existing documents, and fixes what paperless-gpt got wrong. It runs `claude -p` with no tools on the subscription token, and the script does the writing with PATCH and note calls only. It has no way to delete a document.

What it leaves behind:

- A note on each document it changes, `checker: <field> <old> → <new>, because <reason>`.
- The `needs-decision` tag and a `checker decision [<key>]:` note when a person has to decide or act. Removing the tag closes it, and that decision isn't raised again on that document unless its text changes.
- One HTML email a day, at the first run after 06:00, only when something changed or a decision is open.

It acts as the paperless superuser `checker`, so its edits are told apart from people's in the audit log (`admin` is paperless-gpt). A field a person changed last is never overwritten.

State lives on the `paperless-checker` PVC: `/data/state.json` (what it has checked, the values it set, decisions raised) and `/data/changes.jsonl` (one line per change, with the old value, so anything can be put back). `CHECK_SINCE` in the HelmRelease is only read while there is no state file.

Day to day:

- Run it now: `kubectl -n default create job --from=cronjob/paperless-checker checker-manual-$(date +%s)`
- Pause it: set `suspend: true` under the cronjob in the HelmRelease.
- See what it would do without changing anything: add `DRY_RUN: "1"` to its env.
- A run that stops early (usage limit, Claude or paperless down, Claude token rejected) exits 2, keeps what it finished, and says why in the next email. A rejected token is renewed with `claude setup-token`, stored in the `discworld` vault as `CLAUDE_CODE_OAUTH_TOKEN`.
- A document listed as "Couldn't check" is skipped until it changes. Requeue it through paperless-gpt with `paperless-gpt-auto`, and the checker picks it up afterwards.
