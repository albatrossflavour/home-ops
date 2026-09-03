# Network policy flow capture

Input data for writing CiliumNetworkPolicies for the `network` and `rook-ceph` namespaces. Captured 2026-09-01, analysed and recorded 2026-09-03.

## What was captured

Two `hubble observe --follow -o jsonpb` captures ran for six hours from 2026-09-01T23:01:39Z, one per namespace, writing to an `emptyDir`. They were bare unmanaged Pods, which is why four of the original six were lost outright when `magrat` went `NotReady` on 2026-09-01 and got evicted with their data. These two survived.

| namespace | flows captured | raw size | unique initiating tuples |
| --------- | -------------- | -------- | ------------------------ |
| `network` | 1,120,486 | 2.56 GB | 61 |
| `rook-ceph` | 292,708 | 476 MB | 10 |

Aggregation was done inside the pods rather than by copying 3 GB out. The filter drops `is_reply == true`, which is what collapses 50,798 raw tuples down to 61: without it you are mostly counting return traffic on ephemeral ports, which tells you nothing about who initiates what.

```bash
jq -r 'select(.flow.l4 != null) | select(.flow.is_reply != true) | ...' /data/flows.jsonl \
  | sort | uniq -c | sort -rn
```

The pods were deleted after this document was written. `emptyDir` means the raw flows are gone; what follows is all that survives.

## network namespace

`ingress-nginx` is the hub. Everything else in the namespace is small by comparison.

### Ingress to the namespace

| source | destination | port | notes |
| ------ | ----------- | ---- | ----- |
| OUTSIDE | `ingress-nginx` | TCP/443 | real external traffic, 54,629 flows |
| OUTSIDE | `ingress-nginx` | TCP/10254 | metrics scrape, 70,219 flows |
| OUTSIDE | `ingress-nginx` | TCP/80 | 9 flows only |
| OUTSIDE | `external-dns` | TCP/7979 | metrics, 55,117 |
| OUTSIDE | `cloudflared` | TCP/8080 | metrics, 37,838 |
| OUTSIDE | `echo-server` | TCP/8080 | 21,603 |
| OUTSIDE | `dns-export` | TCP/80 | 11,520 |
| `observability/prometheus` | `ingress-nginx` | TCP/10254, TCP/80 | |
| `observability/prometheus` | `external-dns` | TCP/7979 | |
| `observability/prometheus` | `cloudflared` | TCP/8080 | |
| `observability/prometheus` | `echo-server` | TCP/8080 | |
| `network/cloudflared` | `ingress-nginx` | TCP/443 | tunnel to ingress, 9,499 |
| `utilities/node-red` | `ingress-nginx` | TCP/443 | |
| `utilities/n8n` | `ingress-nginx` | TCP/443 | |
| `default/paperless-ai` | `ingress-nginx` | TCP/443 | |
| `default/homepage` | `ingress-nginx` | TCP/80, TCP/443 | |
| `database/nocodb` | `ingress-nginx` | TCP/443 | |
| `media/prowlarr` | `ingress-nginx` | TCP/80 | **DROPPED, see findings** |

The large OUTSIDE-to-metrics-port counts are worth understanding before writing a policy: those ports (10254, 7979, 8080) are Prometheus scrape targets, and the scrapes arrive without a pod identity. A naive `fromEndpoints` rule for `observability/prometheus` will not cover them.

### Egress from the namespace

`ingress-nginx` reaches into nine namespaces:

| destination | port |
| ----------- | ---- |
| `observability/tempo` | TCP/4317 |
| `observability/gatus` | TCP/80 |
| `observability/grafana` | TCP/3000 |
| `observability/prometheus` | TCP/9090 |
| `utilities/shlink` | TCP/8081 |
| `utilities/send` | TCP/1443 |
| `utilities/n8n` | TCP/5678 |
| `media/overseerr` | TCP/5055 |
| `database/nocodb` | TCP/8080 |
| `default/nginx` | TCP/8080 |
| `default/paperless` | TCP/8000 |
| `default/syncthing` | TCP/8384 |
| `default/homepage` | TCP/3000 |
| `default/toodlepip-website` | TCP/8080 |
| `default/pdlf-website` | TCP/80 |
| `default/shit-of-theseus` | TCP/80 |
| `default/grafana` | TCP/3000 |
| `security/authentik` | TCP/9000 |
| `kyverno/policy-reporter-ui` | TCP/8080 |
| `network/echo-server` | TCP/8080 |
| `kube-system/coredns` | UDP/53 |

Plus egress outside the cluster:

| workload | destination | port |
| -------- | ----------- | ---- |
| `ingress-nginx` | OUTSIDE | TCP/8123, TCP/6443 |
| `cloudflared` | OUTSIDE | UDP/7844, TCP/7844, TCP/443, UDP/53 |
| `external-dns` | OUTSIDE | TCP/80, TCP/443, TCP/6443 |
| `dns-export` | OUTSIDE | TCP/443, TCP/6443, UDP/53 |
| `nebula-sync` | OUTSIDE | TCP/80 |

`TCP/6443` is the Kubernetes API. `TCP/8123` from ingress-nginx is Home Assistant, which runs `hostNetwork` and so appears as OUTSIDE rather than as a pod. `UDP/7844` is the Cloudflare tunnel itself.

## rook-ceph namespace

Only ten tuples, and nine of them go to OUTSIDE. That is not because Ceph talks to the internet.

```text
68565  rook-ceph/-        -> OUTSIDE  TCP/3300   mon v2
23067  rook-ceph/ceph-rgw -> OUTSIDE  TCP/6790   mon v1
22518  rook-ceph/-        -> OUTSIDE  TCP/6443   kube API
17412  rook-ceph/ceph-rgw -> OUTSIDE  TCP/3300
13918  OUTSIDE            -> rook-ceph/ceph-csi TCP/8081
 9712  rook-ceph/-        -> OUTSIDE  TCP/6800   OSD
 5126  rook-ceph/ceph-rgw -> OUTSIDE  TCP/6800
 3580  rook-ceph/ceph-csi -> OUTSIDE  TCP/6443
  838  rook-ceph/-        -> OUTSIDE  TCP/6790
   10  rook-ceph/-        -> OUTSIDE  TCP/443
```

**33 of rook-ceph's 46 pods run `hostNetwork: true`.** Ceph peer traffic therefore leaves and arrives on node IPs, not pod IPs, so Cilium sees the other mons and OSDs as entities outside the cluster. Ports 3300, 6790 and 6800 are mons and OSDs talking to each other.

The consequence for policy authoring is the important part: **a pod-selector policy cannot express Ceph's own cluster traffic.** Any `rook-ceph` policy needs CIDR rules covering the node network (`192.168.8.0/24`) for 3300, 6790 and the 6800+ OSD range, or it will break storage the moment it is enforced. This is the single most likely way to take the cluster down while tightening network policy.

## Findings

### prowlarr was being actively denied (resolved 2026-09-03)

```text
22  media/prowlarr-767b478bd6-5wkzb -> network/ingress-nginx-internal-controller  TCP/80  POLICY_DENIED
```

The only `DROPPED` verdict in either capture, and it turned out not to be a policy problem at all.

Prowlarr's application list held three entries. Sonarr and Radarr were configured correctly against in-cluster names (`http://sonarr`, `http://radarr`, both resolving to Services on port 80 in the same namespace, which `media-default` already permits). The third was **Mylar**, at `http://mylar.albatrossflavour.com` - an ingress hostname, which resolves to the internal ingress VIP and lands on `ingress-nginx-internal-controller:80`. That egress is not covered by `media-default`, hence the denial.

Mylar was commented out of `kubernetes/apps/media/kustomization.yaml` on 2025-12-23 in commit `ebd5a629` ("remove mylarr for now"). It has not run since. Prowlarr had been attempting a full indexer sync to a dead application for over eight months, and had been saying so:

```text
[warning] Applications unavailable due to failures for more than 6 hours: Mylar
```

Fixed by deleting the stale application (`DELETE /api/v1/applications/34`), not by widening the network policy. Adding an egress rule would have made the symptom disappear while leaving prowlarr syncing indexers into a void. Verified afterwards: the health warning cleared and no prowlarr drops appear in Hubble's ring buffer.

Two things worth carrying from this. First, the network policy was correct - it surfaced a real configuration error that had been invisible for eight months, which is the argument for default-deny in a sentence. Second, if Mylar ever returns it should be configured as `http://mylar` like its siblings, not via an ingress hostname. Hairpinning through the ingress to reach a pod in the same namespace is slower, and it needs a policy exception that the direct path does not.

### qbittorrent drops inbound BitTorrent traffic

Not a policy denial and not related to the above, but visible in the same ring buffer:

```text
187.14.243.221:60540 (world) <> media/qbittorrent:50413 (world) Service backend not found DROPPED (UDP)
```

External peers are reaching UDP/50413 and finding no service backend. Worth a look separately.

### The busiest flow in the namespace is tracing

`ingress-nginx -> observability/tempo TCP/4317` at 174,290 flows is the single largest tuple, well ahead of actual external traffic on 443. That is OTLP export from the ingress controller. Worth knowing before anyone concludes the cluster is busier than it is.

### Metrics scrapes arrive without pod identity

Three of the top six ingress tuples are Prometheus scraping metrics ports from OUTSIDE. Any default-deny policy in `network` that only allows `fromEndpoints` matching `observability/prometheus` will break metrics collection for ingress-nginx, external-dns and cloudflared simultaneously.

## What to do next

1. ~~Fix the prowlarr denial.~~ Done 2026-09-03 - it was a stale Mylar application entry, not a policy gap. See findings.
2. Write `network-default` from the tables above. The egress list is long but it is a closed set, and `ingress-nginx` is the only workload with meaningful fan-out.
3. Treat `rook-ceph` as a separate exercise with node-CIDR rules, and test it in audit mode first. The hostNetwork behaviour means the usual pod-selector approach silently fails to describe what Ceph actually does.
4. If another capture is ever needed, run it as a `Job` with a PVC rather than a bare `Pod` with `emptyDir`. Four of the original six captures were lost to a node eviction, and these two only survived long enough because nobody noticed them for two days.
