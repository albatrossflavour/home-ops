# Kyverno

Policy engine, deployed 2026-09-02. Everything is **audit-only**. No policy blocks anything, and the configuration is deliberately arranged so that an unreachable Kyverno cannot stop a deploy.

It exists for two reasons. Finding #2 of the cluster audit left `ResourceQuota` unaddressed everywhere except `media` and `flux-system`, and PodSecurity had been pushed as far as it can go: its unit of enforcement is the namespace, so a namespace inherits the permissions of its least restrictive tenant. Six namespaces sit at `enforce: privileged` and only three contain a workload that needs it. Kyverno's unit is the workload.

## What is deployed

| Component | Notes |
|---|---|
| Kyverno v1.19.0 (chart 3.9.0) | `kyverno` namespace, `enforce: restricted` |
| 17 Pod Security Standards policies | 11 Baseline + 6 Restricted, from `kyverno-policies` 3.9.0 |
| 7 custom policies | `kubernetes/apps/kyverno/policies/app/` |
| 1 PolicyException | Volsync restic movers |
| Policy Reporter + UI | `policy-reporter.${SECRET_DOMAIN}`, internal |

Kyverno v1.19 is tested against Kubernetes v1.33–v1.35. This cluster runs **v1.36.3**, one minor ahead. The chart's own `kubeVersion` constraint is only `>=1.25.0-0`, so nothing in the install path flags it. The tested range lives in the docs. Verified working end to end, but it is outside the supported matrix, and upstream's first question on any bug report will be the Kubernetes version.

## Nothing here can block a deploy

Three independent reasons, all verified live rather than read off the config:

- Every policy is `validationActions: [Audit]`, so it records a result and admits the resource.
- Every policy is `failurePolicy: Ignore`, so if the admission controller is unreachable, the request proceeds unchecked.
- Kyverno **deletes its own webhook configurations on graceful shutdown** (8 to 0, rebuilt within 5 seconds on restart).

That last one only covers a clean shutdown. A hard kill, an OOM, or a node vanishing at the hypervisor layer leaves the webhooks registered with nothing behind them, which is what `failurePolicy: Ignore` is actually for. Both mechanisms matter and they cover different failures.

Proven by breaking the `kyverno-svc` selector so the webhook stayed registered with an unreachable backend: creating a Kyverno policy was **blocked** (`no route to host`, because that webhook is `Fail`), while a bare pod and a real Deployment were both **created and ran**. The first result is what makes the other two mean anything; without it, "the pod was admitted" could just mean the webhook was never consulted.

**If you change any of this, keep `failurePolicy: Ignore` on anything matching real workloads.** The `kyverno-policies` chart ships `failurePolicy: Fail` as its default and it is overridden here on purpose.

## Layout

```text
kubernetes/apps/kyverno/
├── kyverno/          the engine (HelmRelease) + OCIRepositories for all three charts
├── pss/              the Pod Security Standards bundle (HelmRelease)
├── policies/app/     hand-written policies, the PolicyException, the GlobalContextEntry
└── policy-reporter/  the UI
```

## Adding a policy

Author against `policies.kyverno.io` (CEL), not the legacy `kyverno.io` `ClusterPolicy`. Upstream has already moved: the official PSS bundle ships both forms of all 17 policies and its `policyType` now *defaults* to `ValidatingPolicy`. The schema is Kubernetes' own ValidatingAdmissionPolicy shape: `matchConstraints`, `validations`, `validationActions`, `failurePolicy` are native VAP fields.

Copy `require-ingress-class.yaml` as the simplest complete example. Then, before committing:

```bash
kubectl apply --dry-run=server -f kubernetes/apps/kyverno/policies/app/your-policy.yaml
```

That sends the policy through Kyverno's own webhook, which compiles the CEL and rejects a syntax error with a caret pointing at the exact character. Costs nothing and catches the whole class of typo.

**Then verify the policy means what you think**, which is a different question entirely. Write an independent check, a short Python pass over the live API, and compare counts. This is not belt-and-braces; see "A policy that compiles can still be completely wrong" below.

Categorise custom policies as `"Tony's Conventions"` so they group separately from the upstream bundle in Policy Reporter.

## Traps

Every one of these was hit during the initial rollout. All of them fail silently.

**`kubectl get policyexception` queries the wrong CRD.** Both API groups register the name and the bare short name binds to the legacy `kyverno.io/v2`. An exception in the new group exists and the obvious command reports `No resources found`. Use `kubectl get policyexceptions.policies.kyverno.io -A`.

**`features.policyExceptions.enabled` ships `false`.** A `PolicyException` applies cleanly, appears in `kubectl get`, and does absolutely nothing. The only signal is an apply-time warning that Flux never surfaces. The Kustomization still goes `Ready=True`.

**A policy matches more than it says.** Autogen expands a policy written for `pods` to Deployments, ReplicaSets, DaemonSets, StatefulSets, Jobs and CronJobs. One policy over 226 pods produced 20,128 results across seven kinds, two thirds of them historical ReplicaSets.

**Admission time and scan time see different objects.** Volsync creates its movers via a Job, so at admission the pod has only `generateName` (`volsync-src-nocodb-`) with an empty name; by background scan it has a real name and no generateName. A `matchCondition` testing one alone silently misses either every live admission or every report. Test both.

**Report results are stamped at scan time, not read live.** Check `results[].timestamp` before concluding anything. This caused two wrong conclusions on day one: once that the scan did not cover Ingresses at all, once that a fix had not worked. Both were stale data. A full scan takes about five minutes and runs Deployments, DaemonSets, ReplicaSets, Pods, then Jobs and CronJobs, so reading early gives a confidently wrong answer.

**Cross-resource lookups need explicit RBAC.** Kyverno ships RBAC for core resources only. `require-pvc-backup` reads Volsync CRDs through a `GlobalContextEntry`, and without a grant the entry silently never populates while the policy still reports `Webhook configured` and `Policy is ready for reporting`. The only trace is one line in a controller log:

```text
failed to sync cache for volsync.backube/v1alpha1, Resource=replicationsources:
informer stopped (context canceled), the resource may not exist in the cluster
```

The grant is `rbac-volsync-read.yaml`, a ClusterRole carrying Kyverno's three aggregation labels. The worker does **not** retry after that failure, so the reports controller needs restarting before the cache will sync.

## A policy that compiles can still be completely wrong

The most important thing in this document.

`require-pvc-backup`'s `GlobalContextEntry` projection was written as `items[].join(...)` when the cached value is a bare list. It compiled, deployed, raised no error, evaluated to null, and made the policy fail **all 36** replicated PVCs, including three that demonstrably have working backups. A confidently-stated backup crisis that did not exist.

Nothing in the policy status, the controller logs, or the report distinguished "the lookup returned no match" from "the lookup returned nothing at all". It was caught only because an independent count over the live API said the answer should be around 22.

The failure runs both ways. Had the expression been inverted it would have reported zero violations and everyone would have believed it. **"It compiled" is not evidence of anything.** Always check a new policy's output against an independent count before trusting it.

## Exceptions

`PolicyException` is the object PodSecurity has no equivalent of, and it has better governance primitives than expected: `expiresAt` (RFC3339), `properties` (whose own CRD documentation suggests `reason`, `ticket` and `approved-by`), and `reportResult: skip|pass`, so an exemption stays visible in the report rather than vanishing. An exempted workload that disappears is indistinguishable from a compliant one.

Exceptions are confined to the `kyverno` namespace (`features.policyExceptions.namespace`) rather than `*`. An exception is permission to violate policy, so letting any namespace declare its own exemptions hands that decision to whoever can write to that namespace.

`expiresAt` is deliberately unset on the Volsync exception. Expiry is right for a temporary workaround and a footgun for a structural requirement. Volsync needs those capabilities permanently, and an expiry would mean backups start failing policy on a date nobody remembers.

## Not done

**Enforce mode.** Nothing blocks. Moving a policy to `Deny` should be treated like the PodSecurity rollout: enforce only where the cluster is already compliant, and work the backlog separately.

**CI gating.** Parked on branch `ci/kyverno-policy-gate-parked`. The script is written and verified against a stubbed renderer; the blocker is `flux-local build hr`, which cannot resolve the cross-namespace `bitnami-nginx` OCIRepository (six HelmReleases share that `chartRef` pattern) and leaves ~40 `cluster-settings` substitutions unresolved. A tool limitation, not a repo fault. Note that audit-mode policies exit 0 from the CLI regardless of flags, so CI gating requires flipping the gating policies to `Deny` first.

**Mutate, generate, image verification, cleanup.** Only one of Kyverno's five policy types is in use. `mutate` is the notable gap: the nine hand-written `automountServiceAccountToken: false` patches are one mutate rule, and injecting default resources would have prevented the `media-quota` backup outage rather than merely reporting it.
