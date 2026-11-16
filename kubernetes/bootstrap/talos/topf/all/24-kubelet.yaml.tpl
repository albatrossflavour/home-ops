# The kubelet stays in the old machine.kubelet form on purpose.
#
# Talos 1.14 has a KubeletConfig document, but it has no extraMounts field
# (its ExtraMounts() returns nil in machinery v1.14.6), and OpenEBS hostpath
# needs /var/openebs/local bind-mounted into the kubelet. The two forms are
# mutually exclusive, so the generated KubeletConfig is deleted below and
# everything it carried (image, seccomp default) is set here instead.
#
# Moving to the document form means moving OpenEBS off an extra mount first,
# probably onto a Talos user volume. That is a storage migration, not a
# config edit.
machine:
  kubelet:
    extraArgs:
      rotate-server-certificates: "true"
      # Eviction thresholds - when to evict pods (% available)
      eviction-hard: "nodefs.available<5%,nodefs.inodesFree<5%,imagefs.available<5%,imagefs.inodesFree<5%,memory.available<500Mi,pid.available<5%"
      eviction-soft: "nodefs.available<10%,nodefs.inodesFree<10%,imagefs.available<10%,imagefs.inodesFree<10%,memory.available<1Gi,pid.available<10%"
      eviction-soft-grace-period: "nodefs.available=2m,nodefs.inodesFree=2m,imagefs.available=2m,imagefs.inodesFree=2m,memory.available=2m,pid.available=2m"
      # Image GC - clean old images (% disk used - triggers well before eviction @ 95% used)
      image-gc-high-threshold: "70"  # Start cleaning at 70% disk used
      image-gc-low-threshold: "60"   # Stop cleaning at 60% disk used
    image: ghcr.io/siderolabs/kubelet:{{ .KubernetesVersion }}
    defaultRuntimeSeccompProfileEnabled: true
    disableManifestsDirectory: true
    extraMounts:
      # OpenEBS hostpath.
      - destination: /var/openebs/local
        type: bind
        source: /var/openebs/local
        options:
          - bind
          - rshared
          - rw
---
apiVersion: v1alpha1
kind: KubeletConfig
$patch: delete
---
# nodeIP is the one kubelet setting that has to move: KubeNodeConfig always
# exists in 1.14 and conflicts with machine.kubelet.nodeIP.
apiVersion: v1alpha1
kind: KubeNodeConfig
nodeIP:
  validSubnets:
    - 192.168.8.0/24
