#!/usr/bin/env bash
# check-healthz.sh — parallel HTTP healthz checker for a fleet of clusters.
#
# Usage:
#   ./check-healthz.sh [options] '<url-template>' [clusters.csv]
#
# URL placeholders: {cluster}, {env}
# CSV: two columns (cluster, env). A `cluster,env` header row is auto-detected
# and skipped. Reads from stdin if no file is given.
#
# Example:
#   ./check-healthz.sh \
#       'https://api.{cluster}.{env}.example.com/healthz' \
#       clusters.csv
#
#   curl -s https://config/clusters.csv | \
#     ./check-healthz.sh -k 'https://{cluster}.{env}.openshift.local/healthz'
#
# Exit codes: 0 = every endpoint returned 2xx; 1 = one or more failed; 2 = usage.

set -uo pipefail

# ---------- defaults ----------
TIMEOUT=5
CONCURRENCY=50
INSECURE=0
MAX_BODY=200
SHOW_BODY=1
USE_CSV=0
PRETTY=0
SHOW_HEADER=1

usage() {
    cat <<'EOF'
Usage: check-healthz.sh [options] '<url-template>' [clusters.csv]

URL placeholders: {cluster}, {env}
CSV: 2 cols (cluster,env). Header row optional, auto-detected. Stdin if no file.

Options:
  -t, --timeout SEC     per-request timeout (default: 5)
  -c, --concurrency N   parallel requests (default: 50)
  -k, --insecure        skip TLS verification
  -b, --max-body N      truncate response body to N chars (default: 200; 0 = full)
      --no-body         omit response body column
      --csv             output CSV instead of TSV
      --pretty          align columns (buffers all rows until completion)
      --no-header       don't print the column header row
  -h, --help            show this help

Output columns: cluster  env  http_code  time_s  response
EOF
    exit 2
}

# ---------- argparse ----------
POSITIONAL=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -t|--timeout)      TIMEOUT="$2"; shift 2 ;;
        -c|--concurrency)  CONCURRENCY="$2"; shift 2 ;;
        -k|--insecure)     INSECURE=1; shift ;;
        -b|--max-body)     MAX_BODY="$2"; shift 2 ;;
        --no-body)         SHOW_BODY=0; shift ;;
        --csv)             USE_CSV=1; shift ;;
        --pretty)          PRETTY=1; shift ;;
        --no-header)       SHOW_HEADER=0; shift ;;
        -h|--help)         usage ;;
        --)                shift; POSITIONAL+=("$@"); break ;;
        -*)                echo "unknown option: $1" >&2; usage ;;
        *)                 POSITIONAL+=("$1"); shift ;;
    esac
done

[[ ${#POSITIONAL[@]} -lt 1 ]] && usage
URL_TEMPLATE="${POSITIONAL[0]}"
INPUT="${POSITIONAL[1]:-/dev/stdin}"

[[ "$URL_TEMPLATE" == *'{cluster}'* ]] \
    || echo "warning: URL template has no {cluster} placeholder" >&2

if [[ "$USE_CSV" == "1" ]]; then
    DELIM=','
else
    DELIM=$'\t'
fi

# ---------- worker (runs once per row in parallel) ----------
check_one() {
    local cluster="$1" env="$2"
    local url="${URL_TEMPLATE//\{cluster\}/$cluster}"
    url="${url//\{env\}/$env}"

    local tmpfile
    tmpfile=$(mktemp "${TMPDIR:-/tmp}/healthz.XXXXXX")

    local curl_opts=(-sS -o "$tmpfile" -w '%{http_code} %{time_total}'
                     --max-time "$TIMEOUT" --connect-timeout "$TIMEOUT")
    [[ "$INSECURE" == "1" ]] && curl_opts+=(--insecure)

    local stats code time body
    if stats=$(curl "${curl_opts[@]}" "$url" 2>/dev/null); then
        code="${stats%% *}"
        time="${stats##* }"
        if [[ "$SHOW_BODY" == "1" ]]; then
            body=$(tr '\n\r\t' '   ' < "$tmpfile")
            [[ "$MAX_BODY" -gt 0 && ${#body} -gt "$MAX_BODY" ]] \
                && body="${body:0:$MAX_BODY}…"
        else
            body=""
        fi
    else
        code="ERR"
        time="-"
        body="(unreachable or timeout)"
    fi
    rm -f "$tmpfile"

    # naive CSV escaping if the body contains the delimiter or quotes
    if [[ "$USE_CSV" == "1" && "$body" == *[\",]* ]]; then
        body="\"${body//\"/\"\"}\""
    fi

    printf '%s%s%s%s%s%s%s%s%s\n' \
        "$cluster" "$DELIM" "$env" "$DELIM" "$code" "$DELIM" "$time" "$DELIM" "$body"
}
export -f check_one
export URL_TEMPLATE TIMEOUT INSECURE MAX_BODY SHOW_BODY USE_CSV DELIM

# ---------- pipeline ----------
results_file=$(mktemp "${TMPDIR:-/tmp}/healthz-results.XXXXXX")
trap 'rm -f "$results_file"' EXIT

emit() {
    if [[ "$SHOW_HEADER" == "1" ]]; then
        printf 'cluster%senv%shttp_code%stime_s%sresponse\n' \
            "$DELIM" "$DELIM" "$DELIM" "$DELIM"
    fi

    awk -F, -v OFS=' ' '
        # auto-skip a "cluster,env" header row (case-insensitive)
        NR == 1 {
            f1 = tolower($1); gsub(/^[ \t]+|[ \t]+$/, "", f1)
            if (f1 == "cluster") next
        }
        NF >= 2 {
            gsub(/^[ \t"]+|[ \t"]+$/, "", $1)
            gsub(/^[ \t"]+|[ \t"]+$/, "", $2)
            if ($1 != "" && $2 != "") print $1, $2
        }
    ' "$INPUT" \
    | xargs -n 2 -P "$CONCURRENCY" bash -c 'check_one "$1" "$2"' _ \
    | tee "$results_file"
}

if [[ "$PRETTY" == "1" ]]; then
    emit | column -t -s "$DELIM"
else
    emit
fi

# ---------- summary ----------
total=$(wc -l < "$results_file" | tr -d ' ')
ok=$(awk -F"$DELIM" '$3 ~ /^2[0-9][0-9]$/ {n++} END {print n+0}' "$results_file")
non2xx=$(awk -F"$DELIM" '$3 ~ /^[0-9]+$/ && $3 !~ /^2[0-9][0-9]$/ {n++} END {print n+0}' "$results_file")
errs=$(awk -F"$DELIM" '$3 == "ERR" {n++} END {print n+0}' "$results_file")
fail=$((total - ok))

echo >&2
echo "Summary: ${ok}/${total} OK, ${fail} FAIL (${non2xx} non-2xx, ${errs} unreachable)" >&2

[[ "$fail" -eq 0 ]] && exit 0 || exit 1
