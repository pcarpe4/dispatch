# lib/exec.sh
# Run the requested oc command against each cluster.
#
# Modes:
#   - streamed (default): output printed as each cluster finishes, prefixed
#     with the cluster name.
#   - --output-dir DIR: per-cluster output written to DIR/<name>.out
#     (stderr to DIR/<name>.err), nothing interleaved on the terminal.
#   - --parallel N: up to N clusters run concurrently.

# exec_one <cluster-name> <out-file> <err-file> -- runs OC_ARGS with the
# cluster's kubeconfig. Returns the oc exit code.
exec_one() {
  local name="$1" out_file="$2" err_file="$3"
  KUBECONFIG="$KUBECONFIG_DIR/$name" oc "${OC_ARGS[@]}" \
    >"$out_file" 2>"$err_file"
}

# exec_report <cluster-name> <rc> <out-file> <err-file>
exec_report() {
  local name="$1" rc="$2" out_file="$3" err_file="$4"

  if [[ -n "$OUTPUT_DIR" ]]; then
    if [[ $rc -eq 0 ]]; then
      log_ok "$name -> $OUTPUT_DIR/$name.out"
    else
      log_error "$name exited $rc -> $OUTPUT_DIR/$name.err"
    fi
    return 0
  fi

  # Streamed mode: prefix every line with the cluster name.
  if [[ $rc -eq 0 ]]; then
    log_ok "$name"
  else
    log_error "$name exited $rc"
  fi
  sed "s/^/[$name] /" "$out_file"
  sed "s/^/[$name] /" "$err_file" >&2
}

# exec_all - iterate CLUSTER_NAMES, honoring PARALLEL. Sets FAILED_CLUSTERS.
declare -a FAILED_CLUSTERS=()
exec_all() {
  local name rc
  local -A pids=()
  local -A rcs=()
  local tmp="$KUBECONFIG_DIR/.out"
  mkdir -p "$tmp"

  local out_base
  if [[ -n "$OUTPUT_DIR" ]]; then
    mkdir -p "$OUTPUT_DIR"
    out_base="$OUTPUT_DIR"
  else
    out_base="$tmp"
  fi

  for name in "${CLUSTER_NAMES[@]}"; do
    # Skip clusters that never logged in.
    [[ -s "$KUBECONFIG_DIR/$name" ]] || { FAILED_CLUSTERS+=("$name"); continue; }

    exec_one "$name" "$out_base/$name.out" "$out_base/$name.err" &
    pids["$name"]=$!

    # Throttle to PARALLEL concurrent jobs.
    while (( $(jobs -rp | wc -l) >= PARALLEL )); do
      wait -n || true
    done
  done

  for name in "${!pids[@]}"; do
    rc=0; wait "${pids[$name]}" || rc=$?
    rcs["$name"]=$rc
  done

  # Report in the original config-file order.
  for name in "${CLUSTER_NAMES[@]}"; do
    [[ -n "${pids[$name]:-}" ]] || continue
    rc="${rcs[$name]}"
    exec_report "$name" "$rc" "$out_base/$name.out" "$out_base/$name.err"
    [[ $rc -eq 0 ]] || FAILED_CLUSTERS+=("$name")
  done
}
