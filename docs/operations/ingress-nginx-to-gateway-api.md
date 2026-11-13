# Migrate off ingress-nginx to Cilium Gateway API

**Status:** Planned, not started
**Created:** 2026-10-27
**Tracking:** OmniFocus task "Migrate off ingress-nginx to Cilium Gateway API"; origin is finding #21 in `Brain/projects/home-ops-cluster-audit-2026-08.md`

## Why

Community ingress-nginx is retired. Best-effort maintenance ended on 24 March 2026 and chart `4.15.1`, which both controllers pin, is the last release there will ever be. Upstream recommends Gateway API, and Cilium already runs the datapath here, so Cilium's Gateway API implementation is the natural target.

There is no CVE forcing this today. The October 2026 Cloudflare/eMudhra notice does not affect it: every backend behind nginx is plain HTTP, so nginx's frozen CA bundle is never used to verify anything. The risk is that the next fix of that kind will never ship for nginx.

## Current state

Checked live on 2026-10-27.

- Two ingress-nginx controllers in `network`: `internal` on `192.168.8.21` and `external` on `192.168.8.23`. Both use `default-ssl-certificate: network/${SECRET_DOMAIN/./-}-production-tls` and `proxy-body-size: 0`.
- 56 ingresses: 39 internal, 17 external.
  - 39 are app-template `ingress:` blocks (all on app-template `3.7.3`).
  - The rest are raw `Ingress` objects (6) or third-party chart ingresses (rook-ceph dashboard, authentik outpost and similar).
- Cilium `v1.20.4`, `kubeProxyReplacement: true`, L2 announcements, LB pool `192.168.8.0/24`. `envoy.enabled: false`, so Envoy runs embedded in the agent. No Gateway API CRDs are installed and `gatewayAPI` is not set.
- external-dns `v0.23.0`, three instances (Cloudflare, `pihole-internal`, `pihole-external`), all `sources: ["ingress"]` (plus `crd` on Cloudflare) and split by `--ingress-class`. All three keep `annotationPrefix: external-dns.alpha.kubernetes.io/`.
- cloudflared sends 13 hostnames to `https://ingress-nginx-external-controller.network.svc.cluster.local:443` with `originServerName: external.${SECRET_DOMAIN}`. The four `http://192.168.4.17` routes do not touch nginx.
- Homepage `v2.7.0` discovers services from ingress annotations.

## What has to change

| Item | Where | Notes |
| --- | --- | --- |
| app-template `ingress:` to `route:` | 39 HelmReleases | Mechanical once the pilot proves the rendering |
| Raw and third-party ingresses | ~17 | Charts without HTTPRoute support get a hand-written `HTTPRoute` beside the HelmRelease |
| theme-park `sub_filter` snippets | bazarr, prowlarr, radarr, sonarr, sabnzbd, qbittorrent, tautulli | Gateway API cannot rewrite response bodies. See decision D1 |
| `proxy-body-size` | global `0`, `send` at `5G`, rook dashboard `0` | Envoy has no body limit, but has a default 15s route timeout. Large uploads need `timeouts` on the route |
| NetworkPolicies allowing `io.kubernetes.pod.namespace: network` | `media/networkpolicy-default.yaml`, `utilities/networkpolicy-default.yaml`, `security/authentik/app/networkpolicy.yaml`, plus any others found in phase 0 | Gateway traffic arrives with Cilium's reserved `ingress` identity, not from a pod in `network`. Without `fromEntities: [ingress]` these apps go dark at cutover |
| external-dns | 3 HelmReleases | Add `gateway-httproute` source, filter with `--gateway-name`. The target annotation goes on the **Gateway**; external-dns ignores it on routes |
| Kyverno | `require-ingress-class`, `require-ingress-dns-target`, `require-homepage-decision` | The DNS target moves to the Gateway, so the per-route check becomes "parentRef is `internal` or `external`" |
| Homepage | `configmap.yaml` kubernetes block | `gateway: true` |
| `dns-export` | `network/dns-export/app/helmrelease.yaml` | Runs `kubectl get ingress` with `192.168.8.21` hard-coded. Needs to read HTTPRoutes |
| Alert | `observability/custom-alerts/app/prometheusrule.yaml` | Replaces the `ingress-nginx-.*-controller` replica alert |
| cloudflared | `network/cloudflared/app/configs/config.yaml` | Per-hostname `service:` swap to the external Gateway service |
| Docs | `CLAUDE.md` DNS sections, `docs/operations/kyverno.md`, `dns-networking.md`, Kyverno policy comments | All describe `className` and the ingress annotation |

## Risks

Ordered by damage.

1. **NetworkPolicies drop Gateway traffic.** Covered in the table above. It is silent until cutover, and it takes authentik with it, which takes every protected app with it. Phase 1 fixes it before anything moves.
2. **Enabling Gateway API changes Cilium on every node.** The agents restart. This gets its own PR, nothing else in it, at a quiet time.
3. **Envoy defaults differ from nginx.** The 15s default route timeout breaks big uploads (immich, nextcloud, send) and slow responses. WebSockets (Home Assistant) need checking too.
4. **External access is family-facing.** toodlepip is Dani's business site; nextcloud and immich on `pdlf.net` are in daily use. External hostnames move last, one at a time, and each one is a single cloudflared line to revert.
5. **external-dns conflicts during the overlap.** An `Ingress` and an `HTTPRoute` for the same host with different targets will fight over the record. Each app's ingress is removed in the same commit that adds its route.
6. **Client IP.** `X-Forwarded-For` behaviour changes. authentik and anything that logs or limits by IP needs checking.
7. **Less familiar tooling.** Envoy config inside Cilium is harder to inspect than nginx logs, and Hubble is off. The nginx metrics go away.

## Decisions needed

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| D1 | theme-park on the 7 media apps | Drop it; route those hosts through the existing plain-nginx `nginx-reverse-proxy`, which can still `sub_filter`; app-native CSS where supported | Drop it unless you care. Plain nginx is still maintained, so the reverse-proxy route is a valid fallback |
| D2 | Final Gateway IPs | Keep the new parallel-run IPs and update every reference; or reclaim `.21` and `.23` once nginx is gone | Reclaim. It keeps `dns-export`, policy comments and anything hard-coded outside the repo valid |
| D3 | Envoy placement | Leave embedded (`envoy.enabled: false`); move to the separate cilium-envoy DaemonSet first | Leave embedded. Moving it is another datapath change, and nothing here needs it |

## Plan

The approach is a parallel run. New Gateways come up on new IPs alongside nginx, routes move a namespace at a time, and nginx stays until everything has soaked.

### Phase 0: checks, no cluster changes (half a day)

- [ ] Find the Gateway API CRD version Cilium `1.20.4` expects in the versioned docs. Current docs say v1.5.1, the 1.20 release post says 1.4 to 1.6. Pin the exact version.
- [ ] `helm template` an app-template `3.7.3` release with a `route:` block and confirm the HTTPRoute renders as expected.
- [ ] Confirm Homepage `v2.7.0` reads `gethomepage.dev/*` annotations from HTTPRoutes, not just from Ingresses.
- [ ] Find how `internal.${SECRET_DOMAIN}` and `external.${SECRET_DOMAIN}` resolve on the LAN (pihole static, DNSEndpoint, router).
- [ ] Grep every NetworkPolicy and CiliumNetworkPolicy that allows the `network` namespace in.
- [ ] List the third-party charts and whether each supports HTTPRoute.
- [ ] Check `externalTrafficPolicy` on the nginx services and what client IP apps see today.
- [ ] Answer D1 to D3.

### Phase 1: NetworkPolicies (1 to 2 hours)

Add `fromEntities: [ingress]` next to each existing `network`-namespace rule. The two coexist during the run.

- Harmless with nothing using it yet.
- Verify policy verdicts with the procedure in `network-policy-flow-capture.md` once phase 3 has a Gateway to test from.
- Rollback: revert the PR.

### Phase 2: enable Gateway API in Cilium (half a day including soak)

1. Install the pinned standard-channel Gateway API CRDs through Flux, as their own Kustomization ordered before Cilium.
2. Set `gatewayAPI.enabled: true` in `kube-system/cilium/app/helm-values.yaml`.
3. Let the agents roll and confirm `kubectl get gatewayclass cilium` reports `Accepted`.
4. Watch it for a day: node readiness, etcd, existing LB services, the Cilium agent restart count.

Rollback: revert the values change. Leaving the CRDs installed is harmless.

### Phase 3: Gateways, external-dns, Kyverno, Homepage (1 day)

- Two `Gateway` objects in `network`, `internal` on `192.168.8.25` and `external` on `192.168.8.26` (confirm both are free first).
  - HTTPS listener on 443 with `certificateRefs` to `${SECRET_DOMAIN/./-}-production-tls`, which already covers every hostname.
  - HTTP listener on 80 with a redirect HTTPRoute, replacing nginx's default SSL redirect.
  - `allowedRoutes.namespaces.from: All`.
  - The internal Gateway's target annotation names a new record (for example `gateway-internal.${SECRET_DOMAIN}` pointing at `.25`) so routes can move one at a time. The external Gateway keeps `external.${SECRET_DOMAIN}`, because public DNS for external hostnames does not change in this migration; cloudflared does the switching.
- external-dns: add `gateway-httproute` to `sources` on all three instances, with `--gateway-name=internal` or `--gateway-name=external` alongside the existing `--ingress-class`.
- Kyverno: add HTTPRoute equivalents of the three ingress policies (parentRef must be `internal` or `external`; homepage decision annotation present). Dry-run each one and check its output against a count you have made by hand, per `kyverno.md`.
- Homepage: `gateway: true`.
- `dns-export`: read HTTPRoutes as well as ingresses.

Rollback: delete the Gateways. Nothing routes through them yet.

### Phase 4: pilot (half a day)

Move one plain internal app with no snippets and no large uploads. Check each of these before moving anything else:

- [ ] `curl --resolve <host>:443:192.168.8.25` returns the app over valid TLS
- [ ] pihole has the record, pointing at the new target
- [ ] the old ingress record is gone, with no flapping in external-dns logs
- [ ] the Homepage tile appears, widget included
- [ ] the Kyverno policy report shows the route passing
- [ ] `dns-export` lists the host
- [ ] HTTP redirects to HTTPS

### Phase 5: internal bulk (1 to 1.5 days)

Namespace by namespace, smallest blast radius first, `security` (authentik) last. One commit per app: remove the ingress and add the route together.

- Set `timeouts.request` and `timeouts.backendRequest` on immich, nextcloud, send and rook dashboard, then test with a real multi-GB upload.
- Test Home Assistant WebSockets by leaving a dashboard open.
- Apply D1 to the media apps.

### Phase 6: external (1 day, spread over several evenings)

Per hostname: add the route on the `external` Gateway, then change that hostname's `service:` in cloudflared's `config.yaml` to the external Gateway service. Check from outside the LAN (phone off wifi) before moving on.

Order: `bandcamp.tv` and `shit-of-theseus.com` first, then the `*.lab` PE hostnames, then `${SECRET_DOMAIN}`, then `pdlf.net` and toodlepip last, outside times the family is using them.

Also change the LAN resolution for `external.${SECRET_DOMAIN}` to `.26`, depending on what phase 0 found.

Rollback per hostname: revert the cloudflared line.

### Phase 7: decommission (half a day, after a week's soak)

1. Delete both ingress-nginx HelmReleases, their Kustomizations, and the `ingress-nginx` HelmRepository.
2. D2: move `.21` and `.23` onto the Gateways, point the target annotations and LAN records back at `internal.` and `external.`, and release `.25` and `.26`.
3. Remove `--ingress-class` and the `ingress` source from external-dns once nothing uses it.
4. Remove the old ingress Kyverno policies and the nginx replica alert; add a Gateway/Envoy equivalent.
5. Remove the `network`-namespace allowances from NetworkPolicies where nothing in `network` still needs to reach the app directly.
6. Update `CLAUDE.md`, `kyverno.md`, `dns-networking.md` and the policy comments.

## Effort and duration

| Phase | Hands-on |
| --- | --- |
| 0 Checks | 0.5 day |
| 1 NetworkPolicies | 0.25 day |
| 2 Cilium | 0.5 day |
| 3 Gateways and plumbing | 1 day |
| 4 Pilot | 0.5 day |
| 5 Internal bulk | 1 to 1.5 days |
| 6 External | 1 day |
| 7 Decommission | 0.5 day |
| **Total** | **about 5 to 6 days** |

Elapsed time is 2 to 4 weeks of evenings and weekends, mostly soak time between phases. Phases 0 to 2 fit in one weekend. These figures are estimates and have not been tested against the work.
