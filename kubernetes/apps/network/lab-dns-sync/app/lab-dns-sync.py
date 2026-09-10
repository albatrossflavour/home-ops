#!/usr/bin/env python3
"""Publish managed Puppet node DNS records to Pi-hole, from PuppetDB.

NOTE: this file is the editable source. The pod runs a copy embedded in the
configMap in helmrelease.yaml. Change one and you must change the other, or the
cluster keeps running the old version.

The lab's managed nodes have no DNS records of their own. PuppetDB knows every
node's certname and current address, which beats a hand-kept list on
DHCP-assigned addresses.

Only records matching MANAGED_RE are ever touched, so the hand-curated entries
in dns.hosts are never at risk. Writes go to the primary Pi-hole; nebula-sync
replicates to the others.

Env:
  PIHOLE_URL        default http://192.168.9.2
  PIHOLE_PASSWORD   required
  PUPPETDB_URL      default https://puppet.lab.albatrossflavour.com:8081
  PUPPETDB_TOKEN    required, PE RBAC token (PuppetDB takes X-Authentication)
  PUPPETDB_CACERT   optional path to the Puppet CA cert; unset means no verify
  MANAGED_RE        default -puppet-(development|production)-\\d+\\.lab\\.
  DRY_RUN           set to any value to report without changing anything
"""
import ipaddress, json, os, re, ssl, sys, urllib.parse, urllib.request

PIHOLE = os.environ.get("PIHOLE_URL", "http://192.168.9.2").rstrip("/")
PDB = os.environ.get("PUPPETDB_URL", "https://puppet.lab.albatrossflavour.com:8081").rstrip("/")
MANAGED = re.compile(os.environ.get("MANAGED_RE", r"-puppet-(development|production)-\d+\.lab\."))
DRY = bool(os.environ.get("DRY_RUN"))


def log(msg):
    print(msg, flush=True)


def http(url, *, method="GET", headers=None, data=None, ctx=None):
    req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.status, r.read()


def puppetdb_inventory():
    token = os.environ["PUPPETDB_TOKEN"]
    ca = os.environ.get("PUPPETDB_CACERT")
    if ca:
        ctx = ssl.create_default_context(cafile=ca)
    else:
        ctx = ssl._create_unverified_context()  # lab-internal, no CA mounted
        log("  note: PUPPETDB_CACERT unset, not verifying the PuppetDB certificate")
    q = urllib.parse.urlencode({"query": "inventory[certname, facts.networking.ip]{}"})
    status, body = http(f"{PDB}/pdb/query/v4?{q}",
                        headers={"X-Authentication": token}, ctx=ctx)
    if status != 200:
        raise SystemExit(f"PuppetDB returned {status}")
    return json.loads(body)


def pihole_session():
    body = json.dumps({"password": os.environ["PIHOLE_PASSWORD"]}).encode()
    status, resp = http(f"{PIHOLE}/api/auth", method="POST", data=body,
                        headers={"Content-Type": "application/json"})
    sid = json.loads(resp).get("session", {}).get("sid")
    if not sid:
        raise SystemExit(f"Pi-hole auth failed ({status})")
    return sid


def main():
    want = set()
    for row in puppetdb_inventory():
        fqdn, ip = row["certname"], row.get("facts.networking.ip")
        if not ip or not MANAGED.search(fqdn):
            continue
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            continue
        want.add(f"{ip} {fqdn}")

    sid = pihole_session()
    hdr = {"X-FTL-SID": sid}
    try:
        _, body = http(f"{PIHOLE}/api/config/dns/hosts", headers=hdr)
        have = set(json.loads(body)["config"]["dns"]["hosts"])
        mine = {h for h in have if MANAGED.search(h)}
        add, remove = sorted(want - mine), sorted(mine - want)

        log(f"managed: {len(want & mine)} correct, {len(add)} to add, "
            f"{len(remove)} to remove ({len(have - mine)} curated entries untouched)")
        for e in remove:
            log(f"  - {e}")
        for e in add:
            log(f"  + {e}")

        if DRY:
            log("dry run, nothing changed")
            return 0

        failed = False
        for entry, method, ok in ([(e, "DELETE", 204) for e in remove] +
                                  [(e, "PUT", 201) for e in add]):
            url = f"{PIHOLE}/api/config/dns/hosts/{urllib.parse.quote(entry, safe='')}"
            try:
                status, _ = http(url, method=method, headers=hdr)
            except Exception as exc:  # noqa: BLE001
                log(f"  {method} errored for {entry}: {exc}")
                failed = True
                continue
            if status != ok:
                log(f"  {method} returned {status} for {entry}")
                failed = True
        if failed:
            log("finished with errors")
            return 1
        if add or remove:
            log("applied. nebula-sync carries it to the replicas on the hour")
        else:
            log("nothing to do")
        return 0
    finally:
        try:
            http(f"{PIHOLE}/api/auth", method="DELETE", headers=hdr)
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
