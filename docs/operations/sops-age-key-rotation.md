# SOPS Age Key Rotation

Procedure for rotating the age key that encrypts every SOPS-managed secret in this repo. There is no automation for this today — every step below is manual and reviewed before pushing.

## When to do this

- The key is suspected compromised (leaked `age.key`, compromised workstation, departing collaborator with access).
- Routine hygiene — no fixed interval is mandated here, but if it's been years, it's overdue.

## What's affected

One age key (`age1n7n73hztvwkq43gskmeddawn5w638dh30g0jycfxvn4h7ek9yvfq8tesqz`, defined in `.sops.yaml`) is the sole recipient for both creation rules (`talos/*.sops.yaml` and `kubernetes/*.sops.yaml`). It encrypts 7 files:

- `kubernetes/bootstrap/talos/talsecret.sops.yaml`
- `kubernetes/flux/vars/cluster-secrets.sops.yaml`
- `kubernetes/apps/external-secrets/onepassword-connect/app/onepassword-connect.secret.sops.yaml`
- `kubernetes/apps/network/external-dns/app/secret.sops.yaml`
- `kubernetes/apps/network/cloudflared/app/secret.sops.yaml`
- `kubernetes/apps/cert-manager/cert-manager/issuers/secret.sops.yaml`
- `kubernetes/apps/flux-system/webhooks/app/github/secret.sops.yaml`

Re-run `find . -iname "*.sops.yaml" -o -iname "*.sops.yml"` before starting in case new ones were added since this doc was written.

The in-cluster `flux-system/sops-age` Secret is what kustomize-controller actually decrypts with. It is **not** Flux-managed — it's created once, directly via `kubectl`, by `.taskfiles/Flux/Taskfile.yaml`'s `bootstrap` task, and that task only creates it if missing. Nothing currently updates it on a rotation, so Step 5 below has to be done by hand. This is expected, not a workaround — the secret Flux needs to decrypt everything else can't itself be Flux-managed.

## Procedure

This is a dual-key transition — the new key is added *alongside* the old one first, so nothing breaks mid-rotation, and the old key is only removed once the new one is proven working end to end.

### 1. Generate the new key

```bash
age-keygen -o age.key.new
```

Note the `# public key: age1...` line it prints — that's what goes into `.sops.yaml`.

### 2. Add the new key as a second recipient

Edit `.sops.yaml` and add the new public key to **both** `key_groups` (the `talos/` rule and the `kubernetes/` rule both currently list only the one key):

```yaml
key_groups:
  - age:
      - "age1n7n73hztvwkq43gskmeddawn5w638dh30g0jycfxvn4h7ek9yvfq8tesqz" # pragma: allowlist secret
      - "age1..." # new
```

(The old key above is the current, live public key from `.sops.yaml` — remove it in step 6, once the new one is confirmed working.)

### 3. Re-key all 7 files against both recipients

```bash
task sops:rotate-key
```

Loops `sops updatekeys` over every `*.sops.yaml`/`*.sops.yml` file in the repo (re-deriving the list live rather than hardcoding it, so it won't silently miss a file added since this doc was written), then verifies each one still decrypts. Stops on the first file that fails - do not continue to Step 5 if it does.

### 4. Verify every file decrypts with the new key alone

Point `SOPS_AGE_KEY_FILE` at *only* the new key (not the combined old+new local keyring) to prove the new key actually works on its own, not just that the old one still does:

```bash
SOPS_AGE_KEY_FILE=age.key.new sops --decrypt kubernetes/flux/vars/cluster-secrets.sops.yaml >/dev/null && echo OK
# repeat for the other 6 files
```

Commit and push `.sops.yaml` plus the 7 re-keyed files before continuing — Flux needs to already be able to decrypt with the new key before the in-cluster secret changes, or a mistake here becomes a cluster-wide decrypt failure the moment Step 5 lands.

### 5. Update the in-cluster secret

```bash
kubectl --kubeconfig kubeconfig -n flux-system delete secret sops-age
cat age.key.new | kubectl --kubeconfig kubeconfig -n flux-system create secret generic sops-age --from-file=age.agekey=/dev/stdin
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps --with-source
```

Watch `flux get kustomizations -A` and `flux get helmreleases -A` afterward — a decrypt failure here shows up as `SOPS_AGE_KEY_FILE` / secretbox errors on any Kustomization touching one of the 7 files.

### 6. Remove the old recipient, re-key again

Once Step 5 is confirmed clean, edit `.sops.yaml` to remove the old public key from both `key_groups`, leaving only the new one. Re-run `task sops:rotate-key` — this actually drops the old key from every file's recipient list, not just from git's idea of what the recipients should be.

Commit and push.

### 7. Back up the new key

```bash
cp age.key.new age.key
task backup:create
```

`task backup:create` updates the existing `homeops-age-key-backup` item in the `discworld` vault (`thegreens.1password.com` account) in place — it edits, not creates a duplicate, as long as the item already exists.

### 8. Clean up

```bash
shred -u age.key.new  # if not already renamed to age.key in step 7
unset SOPS_AGE_KEY_FILE  # re-open your shell, or re-source .envrc, so it picks up the new ./age.key
```

Confirm `direnv` (or however `SOPS_AGE_KEY_FILE` gets set locally — see `.envrc`) is now pointing at the rotated `age.key`, not a stale copy.

## Rollback

If Step 5 breaks decryption cluster-wide before Step 6 has run: the old key is still a valid recipient on every file (dual-key transition), so restoring the previous `sops-age` Secret content (from the 1Password backup, pre-rotation) immediately un-breaks it. This is exactly why Step 6 doesn't happen until Step 5 is confirmed working — once the old key is dropped from the files, this rollback path is gone.
