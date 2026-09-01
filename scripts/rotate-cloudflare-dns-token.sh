#!/usr/bin/env bash
# Rotates the single Cloudflare API token shared by cert-manager (DNS-01 solver)
# and external-dns (record sync) - confirmed 2026-09-01 to be the literal same
# token value in both kubernetes/apps/cert-manager/.../secret.sops.yaml and
# kubernetes/apps/network/external-dns/app/secret.sops.yaml, not two separate
# tokens. Uses Cloudflare's token "roll" endpoint (PUT /user/tokens/{id}/value),
# which issues a new secret for the existing token ID/scope and invalidates the
# old value immediately - no create-new/delete-old window.
#
# Does NOT touch the cloudflared tunnel credential - that's a different
# mechanism (Cloudflare Zero Trust -> Access -> Tunnels), not an API token.
#
# Requires a SEPARATE Cloudflare credential with "User API Tokens: Edit"
# permission to drive the roll call - the DNS-scoped token being rotated
# cannot roll itself. Never pass it as a CLI argument (shell history/process
# list); export it first.
#
# Also updates the 1Password item backing this token (vault "discworld", item
# ID gdc3flnxkhzs2sneomjy2c2u3a - "Cloudflare API Token - cert-manager +
# external-dns (DNS Edit)", created 2026-09-01 specifically for this; two
# earlier guesses at an existing item both turned out to be unrelated
# credentials, see git history of this file). Requires the 1Password CLI
# already signed in interactively as the user account - the
# OP_SERVICE_ACCOUNT_TOKEN this repo's zshrc cache normally exports does NOT
# have a grant on "discworld" and item writes need the interactive user
# account regardless, so it's unset here.
#
# Usage:
#   export CF_ROTATE_API_TOKEN="..."          # the separate, higher-privilege credential
#   ./scripts/rotate-cloudflare-dns-token.sh --list                 # find the token ID
#   ./scripts/rotate-cloudflare-dns-token.sh --token-id <id>        # roll it, update git + 1Password

set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
CM_SECRET="$REPO_ROOT/kubernetes/apps/cert-manager/cert-manager/issuers/secret.sops.yaml"
EDNS_SECRET="$REPO_ROOT/kubernetes/apps/network/external-dns/app/secret.sops.yaml"
API="https://api.cloudflare.com/client/v4"

OP_ACCOUNT="thegreens.1password.com"
OP_VAULT="discworld"
OP_ITEM="gdc3flnxkhzs2sneomjy2c2u3a" # "Cloudflare API Token - cert-manager + external-dns (DNS Edit)", created 2026-09-01
OP_FIELD="credential"

die() {
    echo "error: $*" >&2
    exit 1
}

[ -n "${CF_ROTATE_API_TOKEN:-}" ] || die "export CF_ROTATE_API_TOKEN first (the separate rotation credential, not the DNS token itself)"
command -v jq >/dev/null || die "jq is required"
command -v sops >/dev/null || die "sops is required"

verify_credential() {
    local resp
    resp=$(curl -fsS -X GET "$API/user/tokens/verify" \
        -H "Authorization: Bearer $CF_ROTATE_API_TOKEN" -H "Content-Type: application/json")
    jq -e '.success == true' >/dev/null <<<"$resp" || die "rotation credential failed to verify against Cloudflare"
    echo "rotation credential verified ok"
}

list_tokens() {
    verify_credential
    echo
    echo "Existing API tokens (id / name / status) - identify the DNS token used by cert-manager/external-dns:"
    curl -fsS -X GET "$API/user/tokens" \
        -H "Authorization: Bearer $CF_ROTATE_API_TOKEN" -H "Content-Type: application/json" |
        jq -r '.result[] | "\(.id)  \(.status)  \(.name)"'
}

roll_token() {
    local token_id="$1"
    verify_credential

    echo "rolling token $token_id ..."
    local resp new_value
    resp=$(curl -fsS -X PUT "$API/user/tokens/$token_id/value" \
        -H "Authorization: Bearer $CF_ROTATE_API_TOKEN" -H "Content-Type: application/json")
    jq -e '.success == true' >/dev/null <<<"$resp" || die "roll failed: $(jq -c '.errors' <<<"$resp")"
    new_value=$(jq -r '.result' <<<"$resp")
    [ -n "$new_value" ] && [ "$new_value" != "null" ] || die "roll succeeded but no new value returned"
    echo "token rolled - old value is now invalid"

    # Belt-and-braces: the old value is already dead at this point, and until the
    # git write below is verified, this new one exists only in a shell variable.
    # Stash it to a tightly-permissioned temp file so a failure in the next few
    # lines (sops erroring, disk full, whatever) doesn't strand it - the file is
    # deleted the moment both git files are confirmed to hold it durably.
    local fallback
    fallback=$(mktemp)
    (
        umask 077
        printf '%s' "$new_value" >"$fallback"
    )
    echo "new value stashed at $fallback until git write is verified (belt-and-braces)"

    echo "writing new value into both secret.sops.yaml files ..."
    sops --set "[\"stringData\"][\"api-token\"] \"$new_value\"" "$CM_SECRET"
    sops --set "[\"stringData\"][\"api-token\"] \"$new_value\"" "$EDNS_SECRET"

    echo "verifying both files decrypt to the same new value ..."
    local a b
    a=$(sops -d --extract '["stringData"]["api-token"]' "$CM_SECRET")
    b=$(sops -d --extract '["stringData"]["api-token"]' "$EDNS_SECRET")
    [ "$a" = "$new_value" ] || die "cert-manager file does not match the new value after write"
    [ "$b" = "$new_value" ] || die "external-dns file does not match the new value after write"
    echo "confirmed: both files hold the new, matching token value"

    # Both git files are now the durable copy - safe to drop the temp fallback.
    rm -f "$fallback"
    echo "fallback temp file removed - the new value now only lives encrypted in git (and 1Password, below)"

    if [ -z "$OP_ITEM" ]; then
        echo "OP_ITEM is not set - skipping 1Password update. Set it once the correct item is confirmed" >&2
        echo "(a prior guess and a prior ID both turned out to be wrong items - see script comments)." >&2
        return 0
    fi

    echo "updating 1Password item ($OP_VAULT / \"$OP_ITEM\" / $OP_FIELD) ..."
    if OP_SERVICE_ACCOUNT_TOKEN=op item edit "$OP_ITEM" \
        --account "$OP_ACCOUNT" --vault "$OP_VAULT" \
        "$OP_FIELD=$new_value" >/dev/null 2>&1; then
        echo "1Password item updated"
    else
        echo "WARNING: could not update 1Password - check the CLI is signed in interactively," \
            "and that field \"$OP_FIELD\" is actually the right field name on this item." \
            "Update it manually - pull the value back out of git rather than retyping it:" >&2
        echo "  op item edit \"$OP_ITEM\" --account $OP_ACCOUNT --vault $OP_VAULT \\" >&2
        echo "    $OP_FIELD=\"\$(sops -d --extract '[\"stringData\"][\"api-token\"]' $CM_SECRET)\"" >&2
    fi
    unset a b new_value

    cat <<EOF

Next steps (not done automatically):
  1. Review the diff: git -C "$REPO_ROOT" diff -- "$CM_SECRET" "$EDNS_SECRET"
     (ciphertext will look like a full rewrite - that's expected, SOPS re-encrypts the whole value)
  2. Commit and push.
  3. external-dns will auto-restart on its own (secret.reloader.stakater.com/reload is already wired up).
  4. cert-manager has NO reloader annotation - restart it manually once the new secret has reconciled:
       kubectl rollout restart deployment/cert-manager -n cert-manager
  5. Confirm a real cert renewal/DNS-01 challenge still works before considering this done.
  6. If the 1Password update above warned, update it by hand - the item ID is confirmed correct,
     most likely cause is the CLI not being signed in interactively, or the item's field isn't
     actually named "credential" (check what field name was set when the item was created).
  7. If the script died BEFORE "fallback temp file removed" printed, the new value is sitting in the
     mktemp path printed earlier - recover it from there, it was never written anywhere else, then
     delete that file yourself once you've used it.
EOF
}

case "${1:-}" in
--list) list_tokens ;;
--token-id)
    [ -n "${2:-}" ] || die "usage: $0 --token-id <id>"
    roll_token "$2"
    ;;
*) die "usage: $0 --list | --token-id <id>" ;;
esac
