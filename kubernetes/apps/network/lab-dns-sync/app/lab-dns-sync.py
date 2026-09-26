#!/usr/bin/env python3
"""Publish managed lab DNS records to Pi-hole, from PuppetDB and Proxmox.

NOTE: this file is the editable source. The pod runs a copy embedded in the
configMap in helmrelease.yaml. Change one and you must change the other, or the
cluster keeps running the old version.

The lab's managed nodes have no DNS records of their own. PuppetDB knows every
node's certname and current address, which beats a hand-kept list on
DHCP-assigned addresses.

pecdm clusters need a second source. Their PE nodes have to resolve each other
before PE is installed, so they can't wait for PuppetDB. Proxmox knows them from
the moment they boot: any running VM tagged PROXMOX_TAG, with a fully qualified
name, is published at the first non-loopback IPv4 its guest agent reports.

Only records matching MANAGED_RE or PROXMOX_MANAGED_RE are ever touched, so the
hand-curated entries in dns.hosts are never at risk. If a source can't be read,
its records are left alone rather than removed. Writes go to the primary
Pi-hole; nebula-sync replicates to the others.

Env:
  PIHOLE_URL        default http://192.168.9.2
  PIHOLE_PASSWORD   required
  PUPPETDB_URL      default https://puppet.lab.albatrossflavour.com:8081
  PUPPETDB_TOKEN    required, PE RBAC token (PuppetDB takes X-Authentication)
  PUPPETDB_CACERT   optional path to the Puppet CA cert; unset means no verify
  MANAGED_RE        default -puppet-(development|production)-\\d+\\.lab\\.
  PROXMOX_URL       default https://192.168.5.10:8006
  PROXMOX_TOKEN     optional, "user@realm!tokenid=secret". Unset skips Proxmox
  PROXMOX_TAG       default pecdm
  PROXMOX_MANAGED_RE default " pe-(server|psql|compiler|node)-\\d+-[0-9a-f]+\\."
  DRY_RUN           set to any value to report without changing anything
"""
import ipaddress, json, os, re, ssl, sys, urllib.parse, urllib.request

PIHOLE = os.environ.get("PIHOLE_URL", "http://192.168.9.2").rstrip("/")
PDB = os.environ.get("PUPPETDB_URL", "https://puppet.lab.albatrossflavour.com:8081").rstrip("/")
MANAGED = re.compile(os.environ.get("MANAGED_RE", r"-puppet-(development|production)-\d+\.lab\."))
PVE = os.environ.get("PROXMOX_URL", "https://192.168.5.10:8006").rstrip("/")
PVE_TAG = os.environ.get("PROXMOX_TAG", "pecdm")
PVE_MANAGED = re.compile(os.environ.get("PROXMOX_MANAGED_RE", r" pe-(server|psql|compiler|node)-\d+-[0-9a-f]+\."))
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
        _, body = http(f"{PVE}/api2/json/cluster/resources?type=vm", headers=hdr, ctx=ctx)
    except Exception as exc:  # noqa: BLE001
        log(f"  Proxmox unreadable, leaving its records alone: {exc}")
        return None
    entries = set()
    for vm in json.loads(body)["data"]:
        tags = (vm.get("tags") or "").split(";")
        if vm.get("type") != "qemu" or vm.get("status") != "running" or PVE_TAG not in tags:
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
        ip = next((a["ip-address"] for i in json.loads(body)["data"]["result"]
                   for a in i.get("ip-addresses", [])
                   if a.get("ip-address-type") == "ipv4"
                   and not ipaddress.ip_address(a["ip-address"]).is_loopback
                   and not ipaddress.ip_address(a["ip-address"]).is_link_local), None)
        if ip:
            entries.add(f"{ip} {name}")
    return entries


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

    # Each source only manages its own records, and only when it was readable
    managed = [MANAGED]
    pve = proxmox_inventory()
    if pve is not None:
        want |= pve
        managed.append(PVE_MANAGED)

    sid = pihole_session()
    hdr = {"X-FTL-SID": sid}
    try:
        _, body = http(f"{PIHOLE}/api/config/dns/hosts", headers=hdr)
        have = set(json.loads(body)["config"]["dns"]["hosts"])
        mine = {h for h in have if any(m.search(h) for m in managed)}
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
