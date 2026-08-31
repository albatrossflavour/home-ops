#!/usr/bin/env bash

# Finds pods with RBD-backed (ceph-block) volumes whose kernel client has
# been continuously mapped since before the last cephx keyGeneration
# rotation - the exact condition that caused the 2026-08-29 ogg/postgres16-2
# outage. A stale mapping presents an old cephx ticket and gets rejected
# the next time it actually needs to authenticate (an OSD it talks to
# restarts), not at rotation time itself - so it's a silent, delayed
# failure with no live signal from `ceph -s`.
#
# Run this after any cephx keyGeneration bump, before considering the
# rotation done. Any pod listed as STALE needs restarting so its RBD
# device remaps with the current key.
#
# See docs/operations/cephx-key-rotation.md.

set -euo pipefail

KUBECONFIG_PATH="${KUBECONFIG:-kubeconfig}"
KUBECTL="kubectl --kubeconfig ${KUBECONFIG_PATH}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CEPHX_FILE="kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml"

# The file has three keyGeneration lines (daemon, csi, rbdMirrorPeer) -
# only the csi one governs the kernel RBD client that actually mounts
# volumes into pods, so target it specifically rather than the first
# keyGeneration match in the file.
csi_line=$(
  cd "${REPO_ROOT}" &&
    awk '/^\s*csi:/{f=1} f && /keyGeneration:/{print NR; exit}' "${CEPHX_FILE}"
)

if [[ -z "${csi_line}" ]]; then
  echo "ERROR: could not find csi.keyGeneration in ${CEPHX_FILE}" >&2
  exit 1
fi

rotation_date=$(
  cd "${REPO_ROOT}" &&
    git blame -L "${csi_line},${csi_line}" --date=iso-strict "${CEPHX_FILE}" |
    grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+[+-][0-9]{2}:[0-9]{2}'
)

if [[ -z "${rotation_date}" ]]; then
  echo "ERROR: could not determine last cephx rotation date from git blame on ${CEPHX_FILE}" >&2
  exit 1
fi

rotation_epoch=$(date -d "${rotation_date}" +%s)
echo "Last cephx keyGeneration change: ${rotation_date}"
echo ""

rbd_pvcs=$(
  ${KUBECTL} get pvc -A -o json |
    jq -r '.items[] | select(.spec.storageClassName == "ceph-block") | .metadata.namespace + "/" + .metadata.name'
)

stale_count=0
printf "%-30s %-40s %-25s %s\n" "NAMESPACE" "POD" "STARTED" "STATUS"

while read -r ns pod start pvc_claims; do
  [[ -z "${pod}" ]] && continue
  mounts_rbd=false
  for claim in ${pvc_claims}; do
    if grep -qx "${ns}/${claim}" <<<"${rbd_pvcs}"; then
      mounts_rbd=true
      break
    fi
  done
  [[ "${mounts_rbd}" == false ]] && continue

  start_epoch=$(date -d "${start}" +%s)
  if ((start_epoch < rotation_epoch)); then
    printf "%-30s %-40s %-25s %s\n" "${ns}" "${pod}" "${start}" "STALE - restart this pod"
    ((stale_count++)) || true
  else
    printf "%-30s %-40s %-25s %s\n" "${ns}" "${pod}" "${start}" "ok"
  fi
done < <(
  ${KUBECTL} get pods -A -o json |
    jq -r '.items[] | select(.status.phase == "Running") |
      .metadata.namespace as $ns |
      (.spec.volumes // [] | map(select(.persistentVolumeClaim != null) | .persistentVolumeClaim.claimName)) as $claims |
      select($claims | length > 0) |
      "\($ns) \(.metadata.name) \(.status.startTime) \($claims | join(","))"' |
    sed 's/,/ /g'
)

echo ""
if ((stale_count > 0)); then
  echo "${stale_count} pod(s) carrying a stale cephx session - restart them before considering this rotation done."
  exit 1
else
  echo "No stale RBD mounts found."
fi
