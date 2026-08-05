# lib/config.sh
# Parse the cluster input file.
#
# File format (whitespace-separated, one cluster per line):
#   <name>  <api-url>  [extra oc-login flags...]
#
# Blank lines and lines starting with '#' are ignored. Example:
#   prod   https://api.prod.example.com:6443
#   lab    https://api.lab.example.com:6443   --insecure-skip-tls-verify=true
#   dr     https://api.dr.example.com:6443    --certificate-authority=/etc/pki/dr-ca.crt
#
# After config_load:
#   CLUSTER_NAMES[]        - ordered list of cluster names
#   CLUSTER_API[name]      - API URL per cluster
#   CLUSTER_FLAGS[name]    - extra oc login flags per cluster (may be empty)

declare -a CLUSTER_NAMES=()
declare -A CLUSTER_API=()
declare -A CLUSTER_FLAGS=()

config_load() {
  local file="$1"
  [[ -r "$file" ]] || die "cluster file not readable: $file"

  local lineno=0 line name api flags
  while IFS= read -r line || [[ -n "$line" ]]; do
    lineno=$((lineno + 1))
    # Strip comments and surrounding whitespace.
    line="${line%%#*}"
    line="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' <<<"$line")"
    [[ -z "$line" ]] && continue

    read -r name api flags <<<"$line"
    [[ -n "$name" && -n "$api" ]] \
      || die "$file:$lineno: expected '<name> <api-url> [login-flags]', got: $line"
    [[ "$api" == https://* ]] \
      || die "$file:$lineno: API URL must start with https:// : $api"
    [[ -z "${CLUSTER_API[$name]:-}" ]] \
      || die "$file:$lineno: duplicate cluster name: $name"

    CLUSTER_NAMES+=("$name")
    CLUSTER_API["$name"]="$api"
    CLUSTER_FLAGS["$name"]="${flags:-}"
  done < "$file"

  [[ ${#CLUSTER_NAMES[@]} -gt 0 ]] || die "no clusters defined in $file"
}

# Restrict CLUSTER_NAMES to a comma-separated subset (from --clusters).
config_select() {
  local wanted="$1" name found
  local -a selected=()
  local IFS=','
  for name in $wanted; do
    found=0
    [[ -n "${CLUSTER_API[$name]:-}" ]] && { selected+=("$name"); found=1; }
    [[ "$found" == 1 ]] || die "cluster '$name' not found in cluster file"
  done
  CLUSTER_NAMES=("${selected[@]}")
}
