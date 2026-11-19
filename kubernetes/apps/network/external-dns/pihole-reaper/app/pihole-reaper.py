#!/usr/bin/env python3
"""Remove Pi-hole CNAMEs that external-dns wrote and no longer has a source for.

The external-dns Pi-hole provider has no ownership registry (it lists only A, AAAA and
CNAME, so the TXT registry never sees its own markers), so records for removed ingresses
are never deleted. Guessing ownership from a name pattern would put the hand-made records
at risk, so ownership is proved instead, from a ledger:

  1. Work out what external-dns publishes: every ingress of class internal or external with
     an external-dns target annotation, one CNAME (host -> target) per host under
     DOMAIN_FILTER.
  2. A CNAME that is on a Pi-hole with exactly that host and target while an ingress
     asks for it is one external-dns wrote. Record "host,target" in the ledger ConfigMap.
  3. A ledger entry that no ingress asks for any more, and is still on the Pi-hole with
     exactly the same host and target, is stale. Delete it from every Pi-hole.

Never touched: A records (hosts), CNAMEs never in the ledger, CNAMEs whose target has
changed since they were ledgered, and any host an ingress still asks for under another target.

Safety: no ingresses read or fewer than MIN_DESIRED records wanted aborts the run; at most
MAX_DELETES per Pi-hole per run (the rest wait for the next run); an unreadable Pi-hole is skipped.

Env:
  PIHOLE_URLS     comma-separated Pi-hole base URLs (all share PIHOLE_PASSWORD)
  PIHOLE_PASSWORD required
  DOMAIN_FILTER   required, e.g. example.com
  DRY_RUN         default true. Anything but false/0/no reports without deleting. The ledger
                  is still maintained, since it only records what was observed.
  ADOPT           optional "host,target;host,target": records to treat as external-dns's
                  own although they were never seen sourced (stale before the ledger existed)
  MIN_DESIRED     default 10
  MAX_DELETES     default 5
"""
import json, os, ssl, sys, urllib.error, urllib.parse, urllib.request

PREFIX = "external-dns.alpha.kubernetes.io/"
CLASSES = {"internal", "external"}
LEDGER_NAME = "external-dns-pihole-ledger"
SA = "/var/run/secrets/kubernetes.io/serviceaccount"
DRY = os.environ.get("DRY_RUN", "true").strip().lower() not in ("false", "0", "no")
DOMAIN = os.environ["DOMAIN_FILTER"].strip().lower().lstrip(".")
URLS = [u.strip().rstrip("/") for u in os.environ["PIHOLE_URLS"].split(",") if u.strip()]
MIN_DESIRED = int(os.environ.get("MIN_DESIRED", "10"))
MAX_DELETES = int(os.environ.get("MAX_DELETES", "5"))


def log(msg):
    print(msg, flush=True)


def http(url, *, method="GET", headers=None, data=None, ctx=None):
    req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.status, r.read()


def kube(path, method="GET", body=None):
    token = open(f"{SA}/token").read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    hdr = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    return http(f"https://{host}:{os.environ.get('KUBERNETES_SERVICE_PORT', '443')}{path}",
                method=method, headers=hdr, data=data, ctx=ctx)


def in_domain(host):
    return host == DOMAIN or host.endswith("." + DOMAIN)


def desired():
    """{(host, target)} that external-dns publishes as CNAMEs, from the ingresses."""
    _, body = kube("/apis/networking.k8s.io/v1/ingresses")
    out = set()
    for ing in json.loads(body)["items"]:
        spec, meta = ing.get("spec", {}), ing.get("metadata", {})
        ann = meta.get("annotations") or {}
        if spec.get("ingressClassName") not in CLASSES:
            continue
        # the first target only is what matters here; external-dns writes one CNAME per name
        target = (ann.get(PREFIX + "target") or "").split(",")[0].strip().lower().rstrip(".")
        if not target:
            continue  # no target annotation: an A record at the load balancer, not ours to track
        hosts = [r.get("host") for r in spec.get("rules") or []]
        hosts += [h for t in spec.get("tls") or [] for h in t.get("hosts") or []]
        hosts += (ann.get(PREFIX + "hostname") or "").split(",")
        for h in hosts:
            h = (h or "").strip().lower().rstrip(".")
            if h and "*" not in h and in_domain(h):
                out.add((h, target))
    return out


def load_ledger():
    try:
        _, body = kube(f"/api/v1/namespaces/network/configmaps/{LEDGER_NAME}")
        cm = json.loads(body)
        return cm, set(json.loads(cm.get("data", {}).get("records", "[]")))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, set()
        raise


def save_ledger(cm, records):
    data = {"records": json.dumps(sorted(records))}
    if cm is None:
        kube("/api/v1/namespaces/network/configmaps", "POST",
             {"apiVersion": "v1", "kind": "ConfigMap",
              "metadata": {"name": LEDGER_NAME, "namespace": "network"}, "data": data})
    else:
        cm["data"] = data
        kube(f"/api/v1/namespaces/network/configmaps/{LEDGER_NAME}", "PUT", cm)


def pihole_cnames(base):
    """Returns (sid, set of "host,target" CNAME strings as stored; ttl suffix kept)."""
    body = json.dumps({"password": os.environ["PIHOLE_PASSWORD"]}).encode()
    _, resp = http(f"{base}/api/auth", method="POST", data=body,
                   headers={"Content-Type": "application/json"})
    sid = json.loads(resp).get("session", {}).get("sid")
    if not sid:
        raise RuntimeError("auth failed")
    _, resp = http(f"{base}/api/config/dns/cnameRecords", headers={"X-FTL-SID": sid})
    return sid, set(json.loads(resp)["config"]["dns"]["cnameRecords"])


def split(entry):
    """'host,target[,ttl]' -> (host, target, ttl or None); lowercased."""
    p = [x.strip().lower().rstrip(".") for x in entry.split(",")]
    return (p[0], p[1] if len(p) > 1 else "", p[2] if len(p) > 2 else None)


def main():
    want = desired()
    log(f"{len(want)} CNAMEs wanted by ingresses; dry run: {DRY}")
    if len(want) < MIN_DESIRED:
        log(f"fewer than {MIN_DESIRED} wanted, refusing to act on a source that looks wrong")
        return 1
    want_hosts = {h for h, _ in want}

    cm, ledger = load_ledger()
    for item in os.environ.get("ADOPT", "").split(";"):
        if item.strip():
            ledger.add(",".join(x.strip().lower() for x in item.split(",")))
    before = set(ledger)

    sessions, present = {}, {}
    failed = False
    for base in URLS:
        try:
            sid, entries = pihole_cnames(base)
            sessions[base] = sid
            present[base] = {}
            for e in entries:
                h, t, _ = split(e)
                present[base][(h, t)] = e
        except Exception as exc:  # noqa: BLE001
            log(f"{base}: unreadable, skipping: {exc}")
            failed = True

    try:
        # learn: wanted and on a Pi-hole means external-dns wrote it
        for pair in want:
            if any(pair in p for p in present.values()):
                ledger.add(",".join(pair))
        # forget: nobody has it any more, or its target was changed by hand
        if len(present) == len(URLS):
            on_any = {",".join(k) for p in present.values() for k in p}
            ledger &= on_any | {",".join(p) for p in want}

        stale = sorted(r for r in ledger
                       if tuple(r.split(",")) not in want and r.split(",")[0] not in want_hosts)
        added = sorted(ledger - before)
        for r in added:
            log(f"ledger + {r}")
        for r in sorted(before - ledger):
            log(f"ledger - {r} (gone from every Pi-hole)")
        log(f"ledger holds {len(ledger)} records, {len(stale)} stale")

        for base, recs in present.items():
            hits = [(r, recs[tuple(r.split(","))]) for r in stale if tuple(r.split(",")) in recs]
            kept = len(recs) - len(hits)
            log(f"{base}: {len(recs)} CNAMEs, {len(hits)} stale to remove, {kept} untouched")
            if len(hits) > MAX_DELETES:
                log(f"  more than {MAX_DELETES} stale, deleting {MAX_DELETES} now and the rest next run")
                hits = hits[:MAX_DELETES]
            for r, entry in hits:
                if DRY:
                    log(f"  would delete {entry}")
                    continue
                url = f"{base}/api/config/dns/cnameRecords/{urllib.parse.quote(entry, safe='')}"
                try:
                    status, _ = http(url, method="DELETE", headers={"X-FTL-SID": sessions[base]})
                    log(f"  deleted {entry} ({status})")
                except Exception as exc:  # noqa: BLE001
                    log(f"  delete errored for {entry}: {exc}")
                    failed = True

        # a stale record gone from every Pi-hole is dropped next run by the rule above
        if ledger != before:
            save_ledger(cm, ledger)
    finally:
        for base, sid in sessions.items():
            try:
                http(f"{base}/api/auth", method="DELETE", headers={"X-FTL-SID": sid})
            except Exception:  # noqa: BLE001
                pass
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
