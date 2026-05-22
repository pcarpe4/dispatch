# Adding a Windows VM to an OpenShift Cluster as a Node

This guide walks through joining a manually provisioned Windows Server VM to an
existing OpenShift cluster as a worker node using the **Windows Machine Config
Operator (WMCO)** in *Bring-Your-Own-Host* (BYOH) mode.

It covers the specific situation where the VM:

- was provisioned **without an IP address** (networking must be configured by hand),
- has **no DNS** configured,
- has **no internet access for tooling**, so OpenSSH is delivered by mounting a
  shared folder from the local/admin machine and installed from a zip archive.

> BYOH mode is used when the VM is not created by a cloud `MachineSet` — you
> provision the instance yourself and hand it to WMCO via a ConfigMap. WMCO then
> connects over SSH, installs the kubelet/CRI/CNI components, and registers the
> node.

---

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Configure Windows networking (static IP)](#2-configure-windows-networking-static-ip)
3. [Configure DNS and hostname](#3-configure-dns-and-hostname)
4. [Deliver the OpenSSH package via a shared folder](#4-deliver-the-openssh-package-via-a-shared-folder)
5. [Install OpenSSH Server from the zip](#5-install-openssh-server-from-the-zip)
6. [Authorize the WMCO SSH key](#6-authorize-the-wmco-ssh-key)
7. [Prepare the OpenShift cluster](#7-prepare-the-openshift-cluster)
8. [Register the instance with WMCO](#8-register-the-instance-with-wmco)
9. [Verify the node joined](#9-verify-the-node-joined)
10. [Running workloads on the Windows node](#10-running-workloads-on-the-windows-node)
11. [Removing the node](#11-removing-the-node)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

| Requirement | Notes |
|-------------|-------|
| OpenShift cluster | WMCO version must match the cluster minor version. |
| Cluster network | `OVNKubernetes` with **hybrid networking enabled** (see below). |
| Windows Server VM | Windows Server 2022 or 2019, fully patched, English locale. |
| `oc` CLI | Logged in with `cluster-admin`. |
| Admin workstation | Has the OpenSSH zip and will share it to the VM. |
| Network reachability | The VM's subnet must reach the cluster API and worker nodes; WMCO must be able to reach the VM on TCP 22. |

Confirm the cluster network type and that hybrid networking is enabled — Windows
nodes will not work without it:

```bash
# Must print: OVNKubernetes
oc get network.config/cluster -o jsonpath='{.spec.networkType}{"\n"}'

# Must print a non-empty hybrid overlay config
oc get network.operator/cluster \
  -o jsonpath='{.spec.defaultNetwork.ovnKubernetesConfig.hybridOverlayConfig}{"\n"}'
```

If hybrid networking is **not** configured, enable it (ideally do this at install
time — patching a running cluster restarts the OVN pods and is briefly
disruptive). Pick a `hybridClusterNetwork` CIDR that does **not** overlap the
existing cluster or service networks:

```bash
oc patch network.operator/cluster --type=merge -p '{
  "spec": {
    "defaultNetwork": {
      "ovnKubernetesConfig": {
        "hybridOverlayConfig": {
          "hybridClusterNetwork": [
            { "cidr": "10.132.0.0/14", "hostPrefix": 23 }
          ]
        }
      }
    }
  }
}'
```

> Throughout this guide, replace the placeholder values:
> `10.0.10.50` (VM IP), `10.0.10.1` (gateway), `10.0.10.10`/`10.0.10.11` (DNS
> servers), `win-node-1` (hostname), `example.com` (domain),
> `api.<cluster>.example.com` (cluster API), `10.0.10.5` (admin workstation IP).

---

## 2. Configure Windows networking (static IP)

The VM was provisioned without an IP. Log in to the VM console (the hypervisor
remote console, since there is no network yet) and open an **elevated
PowerShell** session.

Identify the network adapter:

```powershell
Get-NetAdapter
```

Note the `Name` (commonly `Ethernet` or `Ethernet0`) and use it below. Remove any
stale/DHCP configuration, then assign a static address and gateway:

```powershell
$ifAlias = "Ethernet"

# Drop any existing IP / gateway and disable DHCP
Remove-NetIPAddress  -InterfaceAlias $ifAlias -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetRoute      -InterfaceAlias $ifAlias -DestinationPrefix "0.0.0.0/0" -Confirm:$false -ErrorAction SilentlyContinue
Set-NetIPInterface   -InterfaceAlias $ifAlias -Dhcp Disabled

# Assign the static address (PrefixLength 24 == 255.255.255.0)
New-NetIPAddress -InterfaceAlias $ifAlias `
  -IPAddress 10.0.10.50 -PrefixLength 24 -DefaultGateway 10.0.10.1
```

Verify:

```powershell
Get-NetIPConfiguration -InterfaceAlias $ifAlias
Test-NetConnection 10.0.10.1 -InformationLevel Detailed   # ping the gateway
```

---

## 3. Configure DNS and hostname

Set the DNS servers so the VM can resolve the cluster API and image registries:

```powershell
$ifAlias = "Ethernet"

Set-DnsClientServerAddress -InterfaceAlias $ifAlias `
  -ServerAddresses ("10.0.10.10","10.0.10.11")

# Optional: set the DNS suffix used for short-name resolution
Set-DnsClient -InterfaceAlias $ifAlias -ConnectionSpecificSuffix "example.com"
```

Flush the cache and confirm resolution works for the cluster endpoints:

```powershell
Clear-DnsClientCache
Resolve-DnsName api.<cluster>.example.com
Resolve-DnsName quay.io

# The VM must reach the API server on 6443
Test-NetConnection api.<cluster>.example.com -Port 6443
```

Set a stable hostname (this becomes the node name) and ensure the clock is
accurate — kubelet certificate auth fails if time skews more than a few minutes:

```powershell
w32tm /resync /force
w32tm /query /status

Rename-Computer -NewName "win-node-1" -Restart
```

The VM reboots. Reconnect after it comes back up.

---

## 4. Deliver the OpenSSH package via a shared folder

WMCO connects to the VM over SSH, so the OpenSSH Server must be installed first.
Since the VM has no internet access, copy the package from the admin workstation
via a shared folder.

### 4a. On the local / admin machine

Download **`OpenSSH-Win64.zip`** from the official Microsoft release page
(<https://github.com/PowerShell/Win32-OpenSSH/releases>) onto the admin
workstation, then expose it over SMB (run elevated PowerShell):

```powershell
New-Item -Path C:\Share\openssh -ItemType Directory -Force
Copy-Item .\OpenSSH-Win64.zip -Destination C:\Share\openssh\

New-SmbShare -Name "openssh" -Path "C:\Share\openssh" -ReadAccess "Everyone"
```

> **Hypervisor alternative:** if the VM still has no usable network, attach the
> folder as a hypervisor shared folder instead (VMware Shared Folders →
> `\\vmware-host\Shared Folders\openssh`, VirtualBox → `\\VBOXSVR\openssh`, or
> mount an ISO containing the zip). The rest of this section is unchanged apart
> from the source path.

### 4b. On the Windows VM

Map the share and copy the archive locally (elevated PowerShell):

```powershell
New-Item -Path C:\Temp -ItemType Directory -Force

# Map the admin workstation's share by IP
net use Z: \\10.0.10.5\openssh /persistent:no

Copy-Item Z:\OpenSSH-Win64.zip -Destination C:\Temp\
net use Z: /delete
```

---

## 5. Install OpenSSH Server from the zip

Extract the archive and run the bundled install script (elevated PowerShell):

```powershell
# The zip contains a top-level OpenSSH-Win64 folder
Expand-Archive -Path C:\Temp\OpenSSH-Win64.zip -DestinationPath C:\Temp -Force

if (Test-Path "C:\Program Files\OpenSSH") { Remove-Item "C:\Program Files\OpenSSH" -Recurse -Force }
Move-Item C:\Temp\OpenSSH-Win64 "C:\Program Files\OpenSSH"

# Register the sshd and ssh-agent services
Set-Location "C:\Program Files\OpenSSH"
powershell -ExecutionPolicy Bypass -File .\install-sshd.ps1
```

Enable and start the services:

```powershell
Set-Service -Name sshd      -StartupType Automatic
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service sshd
Start-Service ssh-agent
```

Open the firewall for SSH:

```powershell
New-NetFirewallRule -Name "OpenSSH-Server-In-TCP" `
  -DisplayName "OpenSSH Server (sshd)" `
  -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
```

**Set the default SSH shell to PowerShell.** WMCO requires this — node
configuration fails if the default shell is `cmd.exe`:

```powershell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" `
  -Name DefaultShell `
  -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -PropertyType String -Force
```

Restart the service to apply:

```powershell
Restart-Service sshd
```

---

## 6. Authorize the WMCO SSH key

WMCO authenticates to the VM with a key pair. Generate it **on the admin
workstation** (no passphrase — WMCO cannot supply one):

```bash
ssh-keygen -t rsa -b 4096 -N '' -f ./wmco-key
# produces wmco-key (private) and wmco-key.pub (public)
```

Copy `wmco-key.pub` to the VM (via the same shared folder), then install it for
the admin account. For an account in the local **Administrators** group, OpenSSH
reads `C:\ProgramData\ssh\administrators_authorized_keys` (not the per-user
file), and that file must have restricted ACLs:

```powershell
$pub = Get-Content C:\Temp\wmco-key.pub
$akf = "C:\ProgramData\ssh\administrators_authorized_keys"

Add-Content -Path $akf -Value $pub

# Only SYSTEM and Administrators may read the file, inheritance removed
icacls.exe $akf /inheritance:r /grant "SYSTEM:F" /grant "Administrators:F"

Restart-Service sshd
```

Confirm key-based login works from the admin workstation **before** involving
WMCO:

```bash
ssh -i ./wmco-key Administrator@10.0.10.50 "powershell -Command Get-Host"
```

You should get a PowerShell host banner back with no password prompt.

---

## 7. Prepare the OpenShift cluster

### 7a. Install the Windows Machine Config Operator

Create the namespace, `OperatorGroup`, and `Subscription`:

```bash
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: openshift-windows-machine-config-operator
  labels:
    openshift.io/cluster-monitoring: "true"
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: windows-machine-config-operator
  namespace: openshift-windows-machine-config-operator
spec:
  targetNamespaces:
  - openshift-windows-machine-config-operator
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: windows-machine-config-operator
  namespace: openshift-windows-machine-config-operator
spec:
  channel: stable
  installPlanApproval: Automatic
  name: windows-machine-config-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
EOF
```

Wait for the operator to be running:

```bash
oc get csv -n openshift-windows-machine-config-operator
oc rollout status deployment/windows-machine-config-operator \
  -n openshift-windows-machine-config-operator
```

### 7b. Create the private-key secret

WMCO reads the SSH private key from a secret named `cloud-private-key` in its
namespace. The key file inside the secret **must** be named `private-key.pem`:

```bash
oc create secret generic cloud-private-key \
  --from-file=private-key.pem=./wmco-key \
  -n openshift-windows-machine-config-operator
```

---

## 8. Register the instance with WMCO

For BYOH instances, WMCO watches a ConfigMap named `windows-instances` in its
namespace. Each entry's **key** is the VM's IP address or DNS name, and the
**value** is `username=<admin account>`:

```bash
cat <<'EOF' | oc apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: windows-instances
  namespace: openshift-windows-machine-config-operator
data:
  10.0.10.50: |-
    username=Administrator
EOF
```

> Use a DNS name as the key instead of the IP if you prefer
> (`win-node-1.example.com`) — WMCO must be able to reach the VM at whatever
> value you choose.

As soon as the ConfigMap is created, WMCO connects over SSH and begins
configuring the node (kubelet, containerd, hybrid-overlay, CNI). This typically
takes **5–10 minutes**.

---

## 9. Verify the node joined

Watch the WMCO logs and the node list:

```bash
# Operator progress
oc logs -f deployment/windows-machine-config-operator \
  -n openshift-windows-machine-config-operator

# Windows node should appear and reach Ready
oc get nodes -l kubernetes.io/os=windows -w
```

Once `Ready`, inspect the node:

```bash
oc get nodes -l kubernetes.io/os=windows \
  -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,OS:.status.nodeInfo.osImage,VERSION:.status.nodeInfo.kubeletVersion

oc describe node win-node-1
```

A healthy Windows node carries the label `kubernetes.io/os=windows` and the
taint `os=Windows:NoSchedule`.

---

## 10. Running workloads on the Windows node

The `NoSchedule` taint means only pods that explicitly target Windows land on the
node. Add a matching `nodeSelector` and `toleration`:

```yaml
spec:
  nodeSelector:
    kubernetes.io/os: windows
  tolerations:
  - key: "os"
    value: "Windows"
    effect: "NoSchedule"
  containers:
  - name: app
    image: mcr.microsoft.com/windows/servercore/iis:windowsservercore-ltsc2022
```

The container's Windows Server base-image version must be compatible with the
node's OS version.

---

## 11. Removing the node

To deconfigure and remove the Windows node, delete its entry from the
`windows-instances` ConfigMap. WMCO drains the node, removes the cluster
components from the VM, and deletes the `Node` object:

```bash
oc edit configmap windows-instances \
  -n openshift-windows-machine-config-operator
# remove the 10.0.10.50 entry, save

oc get nodes -l kubernetes.io/os=windows
```

The VM itself is left intact (BYOH does not delete instances you provisioned).

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `Resolve-DnsName` fails on the VM | DNS not applied — re-check `Set-DnsClientServerAddress` and run `Clear-DnsClientCache`. |
| `Test-NetConnection api... -Port 6443` fails | Routing/firewall between the VM subnet and the cluster API; verify gateway and that the subnet reaches the masters. |
| `ssh` prompts for a password | `administrators_authorized_keys` missing the key or has wrong ACLs; re-run the `icacls` command and `Restart-Service sshd`. |
| WMCO logs: *unable to execute command* / shell errors | `DefaultShell` not set to PowerShell — re-apply the registry value and restart `sshd`. |
| Node never appears | Confirm the `cloud-private-key` secret exists with file key `private-key.pem`, and that the ConfigMap key matches a reachable address. |
| Node stuck `NotReady` | Hybrid networking not enabled / overlay CIDR overlaps an existing network — recheck step 1. |
| WMCO logs: *kubelet certificate* / TLS errors | Clock skew on the VM — run `w32tm /resync /force`. |
| WMCO refuses the instance | Unsupported Windows Server version, or WMCO version does not match the cluster minor version. |

Useful diagnostics:

```bash
# Operator events and status
oc get events -n openshift-windows-machine-config-operator --sort-by=.lastTimestamp
oc describe configmap windows-instances -n openshift-windows-machine-config-operator

# Node-level detail
oc describe node win-node-1
```

```powershell
# On the VM
Get-Service sshd, ssh-agent
Get-NetIPConfiguration
Get-Content C:\ProgramData\ssh\logs\sshd.log -Tail 50
```

---

## References

- OpenShift docs — *Windows Container Support for OpenShift* / WMCO BYOH instances
- Microsoft *Win32-OpenSSH* releases: <https://github.com/PowerShell/Win32-OpenSSH/releases>
