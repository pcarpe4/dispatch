#!/usr/bin/env bash
# vrops-openshift-esxi-mapping.sh
# Map OpenShift clusters to the ESXi hosts their node VMs run on, including the
# physical CPU counts (sockets and cores) of each host, using the vROps
# (VMware Aria Operations) Suite API.
#
# Inputs (two text files):
#   1. vROps instances file - one vROps hostname or base URL per line.
#      Blank lines and lines starting with '#' are ignored.
#        vrops-east.example.com
#        https://vrops-west.example.com
#
#   2. Clusters file - one OpenShift cluster per line, optionally followed by
#      its environment (whitespace or comma separated). Blank lines and '#'
#      comments are ignored.
#        ocp-prod-east    prod
#        ocp-dev-1        dev
#        ocp-lab
#
# Matching: OpenShift on vSphere names node VMs "<infra-id>-<role>-<n>" where
# the infra-id is "<cluster-name>-<5 random chars>", so a VM is attributed to a
# cluster when its name starts with "<cluster-name>-" (case-insensitive).
#
# Output: CSV to stdout, one row per (cluster, ESXi host) pair:
#   environment,cluster,vrops_instance,esxi_host,host_cpu_sockets,host_cpu_cores,vm_count,vms
# host_cpu_sockets = physical CPU packages on the host; host_cpu_cores = total
# physical cores. "vms" is a semicolon-separated list of the cluster's VMs on
# that host. A per-cluster summary is printed to stderr at the end.
#
# Requires: curl, jq.
#
# Credentials / environment:
#   VROPS_USER          username (required; same for all instances)
#   VROPS_PASSWORD      password (required)
#   VROPS_AUTH_SOURCE   auth source, e.g. an AD/LDAP source name (optional,
#                       omit for local accounts)
#   VROPS_INSECURE=1    skip TLS verification (self-signed certs)
#   VROPS_AUTH_SCHEME   token scheme in the Authorization header
#                       (default: vRealizeOpsToken; newer builds: OpsToken)
#   DEBUG=1             print progress and workdir to stderr
#
# Usage:
#   VROPS_USER=svc-ro VROPS_PASSWORD=... \
#     ./vrops-openshift-esxi-mapping.sh vrops-instances.txt clusters.txt > mapping.csv
#
set -euo pipefail

for bin in curl jq; do
  command -v "$bin" >/dev/null || { echo "missing required binary: $bin" >&2; exit 1; }
done

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <vrops-instances-file> <clusters-file>" >&2
  exit 1
fi
INSTANCES_FILE="$1"
CLUSTERS_FILE="$2"
[[ -r "$INSTANCES_FILE" ]] || { echo "cannot read instances file: $INSTANCES_FILE" >&2; exit 1; }
[[ -r "$CLUSTERS_FILE" ]]  || { echo "cannot read clusters file: $CLUSTERS_FILE" >&2; exit 1; }

: "${VROPS_USER:?set VROPS_USER}"
: "${VROPS_PASSWORD:?set VROPS_PASSWORD}"
AUTH_SCHEME="${VROPS_AUTH_SCHEME:-vRealizeOpsToken}"

CURL_OPTS=(--silent --show-error --fail --connect-timeout 15 --max-time 300)
[[ "${VROPS_INSECURE:-0}" == "1" ]] && CURL_OPTS+=(--insecure)

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
[[ "${DEBUG:-0}" == "1" ]] && echo "workdir: $WORK" >&2

dbg() { [[ "${DEBUG:-0}" == "1" ]] && echo "$*" >&2 || true; }

############################################
# 1. Parse input files
############################################
# clusters.json: [{"cluster":"ocp-prod-east","env":"prod"}, ...]
awk 'NF && $1 !~ /^#/' "$CLUSTERS_FILE" | tr ',' ' ' \
  | jq -R -s '
      [ split("\n")[] | select(length > 0) | [splits("[[:space:]]+")]
        | { cluster: (.[0] | ascii_downcase), env: (.[1] // "") } ]
    ' > "$WORK/clusters.json"

mapfile -t INSTANCES < <(awk 'NF && $1 !~ /^#/ {print $1}' "$INSTANCES_FILE")
[[ ${#INSTANCES[@]} -gt 0 ]] || { echo "no vROps instances found in $INSTANCES_FILE" >&2; exit 1; }
jq -e 'length > 0' "$WORK/clusters.json" >/dev/null \
  || { echo "no clusters found in $CLUSTERS_FILE" >&2; exit 1; }

############################################
# 2. vROps Suite API helpers
############################################
TOKEN=""
BASE=""

vrops_get() { # vrops_get <path-and-query>
  curl "${CURL_OPTS[@]}" \
    -H "Authorization: ${AUTH_SCHEME} ${TOKEN}" \
    -H "Accept: application/json" \
    "${BASE}/suite-api/api/$1"
}

acquire_token() {
  local body
  body="$(jq -n --arg u "$VROPS_USER" --arg p "$VROPS_PASSWORD" --arg s "${VROPS_AUTH_SOURCE:-}" \
    '{username:$u, password:$p} + (if $s != "" then {authSource:$s} else {} end)')"
  curl "${CURL_OPTS[@]}" -X POST \
    -H "Content-Type: application/json" -H "Accept: application/json" \
    -d "$body" \
    "${BASE}/suite-api/api/auth/token/acquire" | jq -r '.token'
}

# Fetch every resource of a kind (paged) into a JSON array of {id,name}.
fetch_resources() { # fetch_resources <resourceKind> <outfile>
  local kind="$1" out="$2" page=0 pagesize=1000 count
  : > "$out.pages"
  while :; do
    vrops_get "resources?resourceKind=${kind}&pageSize=${pagesize}&page=${page}" \
      | jq '[.resourceList[]? | {id: .identifier, name: .resourceKey.name}]' >> "$out.pages"
    count="$(jq -s '.[-1] | length' "$out.pages")"
    dbg "  ${kind} page ${page}: ${count} resources"
    (( count < pagesize )) && break
    page=$((page + 1))
  done
  jq -s 'add // []' "$out.pages" > "$out"
}

# Print "sockets,cores" for a host resource, from its vROps properties.
host_cpu_counts() { # host_cpu_counts <resourceId>
  vrops_get "resources/$1/properties" | jq -r '
    [.property[]? | {name: (.name | ascii_downcase), value}] as $p
    | def pick(ks): first($p[] | select(.name as $n | ks | index($n)) | .value) // null;
      ( pick(["cpu|numpackages", "hardware|cpuinfo|numcpupackages", "cpu|numcpupackages"])
        // first($p[] | select(.name | test("package|socket")) | .value) // "" ) as $sockets
    | ( pick(["cpu|numcores", "hardware|cpuinfo|numcpucores", "cpu|corecount_provisioned"])
        // first($p[] | select(.name | test("cpu.*core")) | .value) // "" ) as $cores
    | "\($sockets),\($cores)"
  '
}

############################################
# 3. Per-instance collection
############################################
: > "$WORK/rows.jsonl"   # one JSON object per matched VM

for INSTANCE in "${INSTANCES[@]}"; do
  BASE="${INSTANCE%/}"
  [[ "$BASE" == http* ]] || BASE="https://${BASE}"
  SHORT="${BASE#https://}"; SHORT="${SHORT#http://}"
  dbg "instance: ${SHORT}"

  if ! TOKEN="$(acquire_token)" || [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
    echo "WARNING: authentication failed for ${SHORT}, skipping" >&2
    continue
  fi

  fetch_resources HostSystem "$WORK/hosts.json"
  fetch_resources VirtualMachine "$WORK/vms.json"
  dbg "  $(jq 'length' "$WORK/hosts.json") hosts, $(jq 'length' "$WORK/vms.json") VMs"

  # VMs whose name starts with "<cluster>-"
  jq --slurpfile clusters "$WORK/clusters.json" '
    [ .[] as $vm
      | ($vm.name | ascii_downcase) as $vn
      | $clusters[0][]
      | select(.cluster as $c | $vn | startswith($c + "-"))
      | {vm_id: $vm.id, vm_name: $vm.name, cluster, env}
    ]' "$WORK/vms.json" > "$WORK/matched.json"
  dbg "  $(jq 'length' "$WORK/matched.json") matched node VMs"

  declare -A HOST_CPUS=()

  while IFS=$'\t' read -r vm_id vm_name cluster env; do
    # Related HostSystem of the VM. We fetch all relationships (rather than
    # filtering server-side with relationshipType) because a VM's only
    # HostSystem relation is its parent ESXi host, and this avoids
    # enum-casing differences between vROps versions.
    host_json="$(vrops_get "resources/${vm_id}/relationships" \
      | jq -c '[.resourceList[]? | select(.resourceKey.resourceKindKey == "HostSystem")
                | {id: .identifier, name: .resourceKey.name}] | first // empty')"
    if [[ -z "$host_json" ]]; then
      echo "WARNING: no ESXi host found for VM ${vm_name} on ${SHORT}" >&2
      continue
    fi
    host_id="$(jq -r '.id' <<<"$host_json")"
    host_name="$(jq -r '.name' <<<"$host_json")"

    if [[ -z "${HOST_CPUS[$host_id]:-}" ]]; then
      HOST_CPUS[$host_id]="$(host_cpu_counts "$host_id")"
    fi
    IFS=',' read -r sockets cores <<<"${HOST_CPUS[$host_id]}"

    jq -n -c \
      --arg env "$env" --arg cluster "$cluster" --arg vrops "$SHORT" \
      --arg host "$host_name" --arg sockets "$sockets" --arg cores "$cores" \
      --arg vm "$vm_name" \
      '{env: $env, cluster: $cluster, vrops: $vrops, host: $host,
        sockets: $sockets, cores: $cores, vm: $vm}' >> "$WORK/rows.jsonl"
  done < <(jq -r '.[] | [.vm_id, .vm_name, .cluster, .env] | @tsv' "$WORK/matched.json")

  unset HOST_CPUS
done

############################################
# 4. Output
############################################
echo "environment,cluster,vrops_instance,esxi_host,host_cpu_sockets,host_cpu_cores,vm_count,vms"
if [[ -s "$WORK/rows.jsonl" ]]; then
  jq -r -s '
    group_by([.cluster, .host])[]
    | .[0] as $r
    | [ $r.env, $r.cluster, $r.vrops, $r.host, $r.sockets, $r.cores,
        (length | tostring), ([.[].vm] | sort | join(";")) ]
    | @csv' "$WORK/rows.jsonl"

  # per-cluster summary to stderr
  {
    echo
    echo "=== summary ==="
    jq -r -s '
      group_by(.cluster)[]
      | ( [group_by(.host)[] | .[0]] ) as $hosts
      | "\(.[0].cluster) (\(.[0].env // "-")): \(length) VMs across \($hosts | length) ESXi hosts, "
        + "total \([$hosts[].sockets | tonumber? // 0] | add) physical CPU sockets / "
        + "\([$hosts[].cores | tonumber? // 0] | add) cores"' "$WORK/rows.jsonl"
  } >&2
else
  echo "WARNING: no cluster node VMs matched on any vROps instance" >&2
fi
