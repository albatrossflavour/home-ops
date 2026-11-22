#!/usr/bin/env python3
"""Publish managed lab DNS records to Pi-hole, from PuppetDB, Proxmox and a file.

kustomization.yaml builds the pod's configMap from this file, curated.json and
puppet-ca.pem, so each exists once, here.

The lab's managed nodes have no DNS records of their own. PuppetDB knows every
node's certname and current address, which beats a hand-kept list on
DHCP-assigned addresses.

pecdm clusters need a second source. Their PE nodes have to resolve each other
before PE is installed, so they can't wait for PuppetDB. Proxmox knows them from
the moment they boot: any running VM tagged PROXMOX_TAG, with a fully qualified
name, is published at the first non-loopback IPv4 its guest agent reports.

The lab's fixed infrastructure names, and the Pi-hole settings AD needs, come
from CURATED_FILE (curated.json), so a rebuilt Pi-hole gets them back on the
next run:

  hosts         "IP name" records. Each name is owned: any other record for it
                is replaced, so changing an address is an edit here.
  absent_hosts  names to remove. A name dropped from hosts is otherwise left as
                it is, since nothing records that this script once wrote it.
  rev_servers   dns.revServers in full (conditional forwarding), when present.
  allow_regex   allow-list regexes. Each is written with a comment starting
                COMMENT_TAG, and a tagged regex no longer listed is removed.

Only records matching MANAGED_RE or PROXMOX_MANAGED_RE, names in the curated
file, and tagged regexes are ever touched, so everything else hand-kept in the
Pi-holes is never at risk. If a source can't be read, its records are left
alone rather than removed.

Managed records are written to the primary Pi-hole and to every replica in
PIHOLE_REPLICAS. nebula-sync only copies the primary to the replicas on the
hour, and clients that ask a replica first would otherwise get NXDOMAIN for up
to an hour after a record is added. nebula-sync's copy then matches what is
already there.

Env:
  PIHOLE_URL        default http://192.168.9.2
  PIHOLE_REPLICAS   optional, comma-separated replica URLs sharing the password
  PIHOLE_PASSWORD   required
  PUPPETDB_URL      default https://puppet.lab.albatrossflavour.com:8081
  PUPPETDB_TOKEN    required, PE RBAC token (PuppetDB takes X-Authentication)
  PUPPETDB_CACERT   optional path to the Puppet CA cert; unset means no verify
  MANAGED_RE        default -puppet-(development|production)-\\d+\\.(lab|gce)\\.
  PROXMOX_URL       default https://192.168.5.10:8006
  PROXMOX_TOKEN     optional, "user@realm!tokenid=secret". Unset skips Proxmox
  PROXMOX_TAG       default pecdm
  PROXMOX_MANAGED_RE default " pe-(server|psql|compiler|node)-\\d+-[0-9a-f]+\\."
  CURATED_FILE      default /app/curated.json. Missing or unreadable skips it
  DRY_RUN           set to any value to report without changing anything
"""

import ipaddress
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request

PIHOLE = os.environ.get("PIHOLE_URL", "http://192.168.9.2").rstrip("/")
REPLICAS = [
    u.strip().rstrip("/")
    for u in os.environ.get("PIHOLE_REPLICAS", "").split(",")
    if u.strip()
]
PDB = os.environ.get(
    "PUPPETDB_URL", "https://puppet.lab.albatrossflavour.com:8081"
).rstrip("/")
MANAGED = re.compile(
    os.environ.get("MANAGED_RE", r"-puppet-(development|production)-\d+\.(lab|gce)\.")
)
PVE = os.environ.get("PROXMOX_URL", "https://192.168.5.10:8006").rstrip("/")
PVE_TAG = os.environ.get("PROXMOX_TAG", "pecdm")
PVE_MANAGED = re.compile(
    os.environ.get(
        "PROXMOX_MANAGED_RE", r" pe-(server|psql|compiler|node)-\d+-[0-9a-f]+\."
    )
)
CURATED = os.environ.get("CURATED_FILE", "/app/curated.json")
COMMENT_TAG = "lab-dns-sync: "
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
    status, body = http(
        f"{PDB}/pdb/query/v4?{q}", headers={"X-Authentication": token}, ctx=ctx
    )
    if status != 200:
        raise SystemExit(f"PuppetDB returned {status}")
    return json.loads(body)


def proxmox_inventory():
    """Entries for running VMs tagged PVE_TAG, or None if Proxmox can't be read.

    Uses the API with a read-only token (PVEAuditor on /vms is enough on PVE 9).
    A VM whose guest agent isn't answering yet is skipped this round.
    """
    token = os.environ.get("PROXMOX_TOKEN")
    if not token:
        return None
    ctx = ssl._create_unverified_context()  # lab-internal, self-signed
    hdr = {"Authorization": f"PVEAPIToken={token}"}
    try:
        _, body = http(
            f"{PVE}/api2/json/cluster/resources?type=vm", headers=hdr, ctx=ctx
        )
    except Exception as exc:  # noqa: BLE001
        log(f"  Proxmox unreadable, leaving its records alone: {exc}")
        return None
    entries = set()
    for vm in json.loads(body)["data"]:
        tags = (vm.get("tags") or "").split(";")
        if (
            vm.get("type") != "qemu"
            or vm.get("status") != "running"
            or PVE_TAG not in tags
        ):
            continue
        name = vm.get("name", "")
        if "." not in name:
            log(f"  skip {name}: not a fully qualified name")
            continue
        url = f"{PVE}/api2/json/nodes/{vm['node']}/qemu/{vm['vmid']}/agent/network-get-interfaces"
        try:
            _, body = http(url, headers=hdr, ctx=ctx)
        except Exception:  # noqa: BLE001
            log(f"  skip {name}: guest agent not answering yet")
            continue
        ip = next(
            (
                a["ip-address"]
                for i in json.loads(body)["data"]["result"]
                for a in i.get("ip-addresses", [])
                if a.get("ip-address-type") == "ipv4"
                and not ipaddress.ip_address(a["ip-address"]).is_loopback
                and not ipaddress.ip_address(a["ip-address"]).is_link_local
            ),
            None,
        )
        if ip:
            entries.add(f"{ip} {name}")
    return entries


def curated_source():
    """The curated file, or None if it can't be read (its records are left alone)."""
    try:
        with open(CURATED) as f:
            cur = json.load(f)
        for entry in cur.get("hosts", []):
            ip, _name = entry.split()
            ipaddress.ip_address(ip)
        return cur
    except Exception as exc:  # noqa: BLE001
        log(f"  curated file {CURATED} unusable, leaving its records alone: {exc}")
        return None


def names_re(names):
    """A pattern matching any "IP name" record for exactly these names."""
    if not names:
        return None
    return re.compile(
        r"^\S+ (?:" + "|".join(re.escape(n) for n in sorted(names)) + r")$"
    )


def call_all(base, hdr, calls):
    """Make (method, path, expected status, body) calls. True if all succeed."""
    ok_all = True
    for method, path, ok, payload in calls:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {**hdr, "Content-Type": "application/json"} if data else hdr
        try:
            status, _ = http(f"{base}{path}", method=method, headers=headers, data=data)
        except Exception as exc:  # noqa: BLE001
            log(f"  {method} {path} errored: {exc}")
            ok_all = False
            continue
        if status != ok:
            log(f"  {method} {path} returned {status}")
            ok_all = False
    return ok_all


def sync_settings(base, hdr, cur):
    """Bring rev_servers and the tagged allow regexes in line with cur."""
    calls = []
    if "rev_servers" in cur:
        _, body = http(f"{base}/api/config/dns/revServers", headers=hdr)
        have = json.loads(body)["config"]["dns"]["revServers"]
        if have != cur["rev_servers"]:
            log(f"  revServers {have} -> {cur['rev_servers']}")
            calls.append(
                (
                    "PATCH",
                    "/api/config",
                    200,
                    {"config": {"dns": {"revServers": cur["rev_servers"]}}},
                )
            )

    _, body = http(f"{base}/api/domains/allow/regex", headers=hdr)
    have = {d["domain"]: d for d in json.loads(body)["domains"]}
    want = {r["domain"]: COMMENT_TAG + r["comment"] for r in cur.get("allow_regex", [])}
    for domain, comment in sorted(want.items()):
        quoted = urllib.parse.quote(domain, safe="")
        entry = {"comment": comment, "groups": [0], "enabled": True}
        if domain not in have:
            log(f"  + allow regex {domain}")
            calls.append(
                ("POST", "/api/domains/allow/regex", 201, {"domain": domain, **entry})
            )
        elif have[domain].get("comment") != comment or not have[domain].get("enabled"):
            log(f"  ~ allow regex {domain}")
            calls.append(("PUT", f"/api/domains/allow/regex/{quoted}", 200, entry))
    for domain, d in sorted(have.items()):
        if (d.get("comment") or "").startswith(COMMENT_TAG) and domain not in want:
            log(f"  - allow regex {domain}")
            calls.append(
                (
                    "DELETE",
                    f"/api/domains/allow/regex/{urllib.parse.quote(domain, safe='')}",
                    204,
                    None,
                )
            )

    if DRY or not calls:
        return True
    return call_all(base, hdr, calls)


def pihole_session(base):
    body = json.dumps({"password": os.environ["PIHOLE_PASSWORD"]}).encode()
    status, resp = http(
        f"{base}/api/auth",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    sid = json.loads(resp).get("session", {}).get("sid")
    if not sid:
        raise RuntimeError(f"Pi-hole auth failed at {base} ({status})")
    return sid


def sync_pihole(base, want, managed, cur):
    """Bring one Pi-hole's managed records and settings in line. True on success."""
    sid = pihole_session(base)
    hdr = {"X-FTL-SID": sid}
    try:
        _, body = http(f"{base}/api/config/dns/hosts", headers=hdr)
        have = set(json.loads(body)["config"]["dns"]["hosts"])
        mine = {h for h in have if any(m.search(h) for m in managed)}
        add, remove = sorted(want - mine), sorted(mine - want)

        log(
            f"{base}: {len(want & mine)} correct, {len(add)} to add, "
            f"{len(remove)} to remove ({len(have - mine)} other entries untouched)"
        )
        for e in remove:
            log(f"  - {e}")
        for e in add:
            log(f"  + {e}")

        hosts = [
            (
                "DELETE",
                f"/api/config/dns/hosts/{urllib.parse.quote(e, safe='')}",
                204,
                None,
            )
            for e in remove
        ]
        hosts += [
            (
                "PUT",
                f"/api/config/dns/hosts/{urllib.parse.quote(e, safe='')}",
                201,
                None,
            )
            for e in add
        ]
        ok_all = DRY or call_all(base, hdr, hosts)
        if cur is not None:
            ok_all = sync_settings(base, hdr, cur) and ok_all
        if DRY:
            log("  dry run, nothing changed")
        return ok_all
    finally:
        try:
            http(f"{base}/api/auth", method="DELETE", headers=hdr)
        except Exception:  # noqa: BLE001
            pass


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

    # Each source only manages its own records, and only when it was readable
    managed = [MANAGED]
    pve = proxmox_inventory()
    if pve is not None:
        want |= pve
        managed.append(PVE_MANAGED)

    cur = curated_source()
    if cur is not None:
        want |= set(cur.get("hosts", []))
        owned = names_re(
            {e.split()[1] for e in cur.get("hosts", [])}
            | set(cur.get("absent_hosts", []))
        )
        if owned:
            managed.append(owned)

    # Primary first. A replica that fails doesn't stop the others; the run
    # just reports failure so it is visible.
    failed = False
    for base in [PIHOLE] + REPLICAS:
        try:
            if not sync_pihole(base, want, managed, cur):
                failed = True
        except Exception as exc:  # noqa: BLE001
            log(f"{base}: sync failed: {exc}")
            failed = True
    if failed:
        log("finished with errors")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
