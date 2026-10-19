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

- Every prompt must end, after the document content, with an instruction to reply with the answer alone. Without it the model sometimes writes its reasoning first, and paperless-gpt saves the whole reply as the title or correspondent. A long correspondent then fails paperless's 128-character limit.
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
