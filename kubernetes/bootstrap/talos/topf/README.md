# Talos machine configuration

The machine config for every node is rendered by [topf](https://github.com/postfinance/topf) from `topf.yaml` and the patch files in this directory, and none of the rendered output is committed. topf replaced talhelper on 2026-11-16, because talhelper was archived on 2026-08-26 and can't render Talos 1.14 configs.

## Layout

| Path | What it holds |
| --- | --- |
| `topf.yaml` | Cluster name and endpoint, the Talos and Kubernetes versions, the Image Factory schematic, and the six nodes with their IP and MAC address |
| `all/` | Patches for every node |
| `control-plane/` | Patches for the three control-plane nodes |
| `worker/` | Patches for the workers (none yet) |
| `node/<host>/` | Patches for one node (none yet) |
| `../talsecret.sops.yaml` | The cluster secrets bundle, sops-encrypted |

Patches merge in that order, and by filename inside each directory, so a later file wins. Files ending `.yaml.tpl` are Go templates and can read `.Node.Host`, `.Node.IP`, `.Node.Role`, and `.Node.Data` from `topf.yaml`.

topf only takes strategic merge patches, so a JSON6902 patch won't work here.

## Day to day

Show what a change would do to a node, then apply it:

```bash
task talos:maintenance:apply-config node=ogg ip=192.168.8.11
```

That renders the node's config into a private temporary directory, prints a dry-run diff against the live node, and asks before applying. On the control plane, do the etcd followers first and leave the leader until last, checking etcd between each.

To look at the whole cluster without applying anything:

```bash
cd kubernetes/bootstrap/talos/topf
SOPS_AGE_KEY_FILE=../../../../age.key topf apply --dry-run
```

`SOPS_AGE_KEY_FILE` has to point at the repo's `age.key`. If your shell already exports a different key file, the decrypt fails with "no identity matched any of the recipients", which is what the tasks avoid by setting it themselves.

## Things that will catch you out

- `topf render` doesn't validate, so it will write a config that a node rejects. The `Talhelper` CI check runs `talosctl validate` on every rendered config for that reason, and a dry-run against the node is still the real test.
- `talosctl upgrade` doesn't update the installer image recorded in a node's config. After upgrading Talos, apply the configs again or the next diff shows the old tag.
- `topf reset` wipes the whole install disk by default, so `task talos:nuke` passes `--full=false` unless it's forced.
- `topf kubeconfig` produces an admin credential that expires after 12 hours, which is why `task talos:fetch-kubeconfig` calls `talosctl kubeconfig`.
- `task talos:bootstrap` and `task talos:nuke` were rewritten for topf and haven't been run since.
