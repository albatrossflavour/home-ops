#!/usr/bin/env bash
# Evaluate this repo's Kyverno policies against the manifests a PR would
# actually produce, and fail the build on a violation.
#
# Two things make this less obvious than it looks.
#
# 1. The objects the policies care about - Ingresses, Pods, PVCs - do not
#    exist in git. They are produced by Helm at deploy time from HelmReleases.
#    Running kyverno straight over kubernetes/apps matches zero resources and
#    reports a green tick that means nothing. So everything is rendered first
#    with flux-local, the same tool the Flux Diff check already uses.
#
# 2. The in-cluster policies are all validationActions: [Audit] on purpose,
#    so that an unreachable Kyverno can never block a deploy. Audit policies
#    exit 0 from the CLI no matter what flags are passed (--audit-warn and
#    --warn-exit-code do not change it; the result counts as "fail", not
#    "warn"). So the gating policies are copied to a temp dir and flipped to
#    [Deny] for CI only. Same source files, enforced only where a human is
#    still holding the change.
set -o errexit
set -o pipefail

KUBERNETES_DIR="${1:-./kubernetes}"
POLICY_DIR="${KUBERNETES_DIR}/apps/kyverno/policies/app"

# Policies that gate a merge. Deliberately only those with zero current
# violations, so this blocks NEW breakage without demanding the backlog be
# cleared first - the same approach used for the PodSecurity rollout.
#
# Held back until their backlog is worked, then move them up:
#   require-pod-resources        91 violations
#   require-homepage-decision    15
#   require-image-digest          1  (default/grafana-shitbox)
#   require-pvc-backup               needs a live cluster for its
#                                    GlobalContextEntry lookup
GATING_POLICIES=(
  "require-ingress-dns-target"
  "require-ingress-class"
  "require-storageclass-allowlist"
)

WORK="$(mktemp -d)"
mkdir -p "${WORK}/policies"
trap 'rm -rf "${WORK}"' EXIT

echo "=== Preparing gating policies (Audit -> Deny) ==="
for name in "${GATING_POLICIES[@]}"; do
  src="${POLICY_DIR}/${name}.yaml"
  [[ -f "${src}" ]] || { echo "Policy not found: ${src}"; exit 1; }
  sed 's/validationActions: \[Audit\]/validationActions: [Deny]/' "${src}" > "${WORK}/policies/${name}.yaml"
  if ! grep -q 'validationActions: \[Deny\]' "${WORK}/policies/${name}.yaml"; then
    echo "Failed to switch ${name} to Deny - check its validationActions formatting"
    exit 1
  fi
  echo "  ${name}"
done

echo "=== Rendering and evaluating ==="
# hr and ks are rendered and evaluated separately rather than concatenated.
# kyverno panics outright on two objects sharing a name, and the two builds
# can legitimately overlap (build ks emits the HelmRelease object itself,
# build hr emits what that HelmRelease produces). Separate passes remove the
# risk; errexit means either failing fails the build.
for kind in hr ks; do
  out="${WORK}/rendered-${kind}.yaml"
  echo "--- flux-local build ${kind} ---"
  # --all-namespaces defaults to FALSE, which scopes the build to a single
  # namespace and silently renders nothing - no error, no warning, exit 0.
  # That is how this first failed, and it is exactly the vacuous-green case
  # the object-count guard below exists to catch. --sources matches the
  # GitRepository, same as the Flux Diff workflow already passes.
  flux-local build "${kind}" \
    --path "${KUBERNETES_DIR}/flux" \
    --all-namespaces \
    --sources "home-kubernetes" \
    --output-file "${out}" 2>"${WORK}/${kind}.err" || {
    echo "flux-local build ${kind} failed:"; cat "${WORK}/${kind}.err"; exit 1
  }
  count="$(grep -c '^kind:' "${out}" || true)"
  echo "  rendered ${count} objects"

  # A render producing almost nothing would let every policy pass vacuously,
  # which is the failure mode that makes a green tick meaningless.
  if [[ "${count}" -lt 20 ]]; then
    echo "Refusing to continue: ${kind} render produced implausibly few objects (${count})."
    echo "--- stderr from flux-local ---"
    cat "${WORK}/${kind}.err" || true
    exit 1
  fi

  kyverno apply "${WORK}/policies" --resource "${out}"
done

echo "=== All gating policies passed ==="
