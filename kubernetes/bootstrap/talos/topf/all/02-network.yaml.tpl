# One static interface per node, selected by MAC address (nodes[].data.mac in
# topf.yaml) so it survives interface renames. Control-plane nodes also
# carry the API VIP on it.
apiVersion: v1alpha1
kind: LinkAliasConfig
name: ethSel0
selector:
  match: glob("{{ .Node.Data.mac }}", mac(link.hardware_addr))
{{- if eq .Node.Role "control-plane" }}
---
# The Kubernetes API VIP, shared between the three control-plane nodes. It is
# here and not under control-plane/ so the document order matches what the
# nodes already hold, which keeps the dry-run diff empty.
apiVersion: v1alpha1
kind: Layer2VIPConfig
name: 192.168.8.20
link: ethSel0
{{- end }}
---
apiVersion: v1alpha1
kind: LinkConfig
name: ethSel0
mtu: 1500
addresses:
  - address: {{ .Node.IP }}/24
routes:
  - gateway: 192.168.8.1
