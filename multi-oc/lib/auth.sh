# lib/auth.sh
# Credential collection and cluster login.
#
# Security notes:
#   - Username/password/token are read with `read` from the terminal, never
#     taken as command-line arguments, so they cannot appear in shell history.
#   - Password/token prompts use `read -s` (silent) so they are not echoed.
#   - The password is fed to `oc login` on stdin, never via --password, so it
#     is not visible in `ps` output or /proc/<pid>/cmdline.
#   - Each cluster logs in against its own temporary KUBECONFIG under a
#     0700 directory that is shredded on exit; the user's real kubeconfig
#     is never read or modified.

MOC_USERNAME=""
MOC_PASSWORD=""
MOC_TOKEN=""

# Prompt for username + password (or token in token mode). Reads from
# /dev/tty so it works even when stdin is a pipe or file.
auth_prompt() {
  if [[ "$AUTH_MODE" == "token" ]]; then
    read -rsp "API token: " MOC_TOKEN </dev/tty; printf '\n' >&2
    [[ -n "$MOC_TOKEN" ]] || die "empty token"
  else
    read -rp  "Username: " MOC_USERNAME </dev/tty
    read -rsp "Password: " MOC_PASSWORD </dev/tty; printf '\n' >&2
    [[ -n "$MOC_USERNAME" && -n "$MOC_PASSWORD" ]] || die "empty username or password"
  fi
}

# auth_login <cluster-name>
# Logs in to one cluster using its isolated kubeconfig. Login output is
# captured and only shown on failure.
auth_login() {
  local name="$1"
  local api="${CLUSTER_API[$name]}"
  local kubeconfig="$KUBECONFIG_DIR/$name"
  local -a flags=()
  # Word-split intentionally: per-cluster flags from the config file.
  read -ra flags <<<"${CLUSTER_FLAGS[$name]:-}"

  local out rc=0
  if [[ "$AUTH_MODE" == "token" ]]; then
    out=$(KUBECONFIG="$kubeconfig" oc login "$api" \
            --token="$MOC_TOKEN" "${flags[@]}" 2>&1) || rc=$?
  else
    # Password over stdin: oc prompts on stdin when --password is absent.
    out=$(printf '%s\n' "$MOC_PASSWORD" \
          | KUBECONFIG="$kubeconfig" oc login "$api" \
              --username="$MOC_USERNAME" "${flags[@]}" 2>&1) || rc=$?
  fi

  if [[ $rc -ne 0 ]]; then
    log_error "login failed for $name ($api)"
    printf '%s\n' "$out" | sed 's/^/    /' >&2
    return 1
  fi
  log_ok "logged in to $name"
}

# Log out of every cluster we logged in to (invalidates the session tokens
# server-side, not just locally).
auth_logout_all() {
  local name kubeconfig
  for name in "${CLUSTER_NAMES[@]}"; do
    kubeconfig="$KUBECONFIG_DIR/$name"
    [[ -s "$kubeconfig" ]] || continue
    KUBECONFIG="$kubeconfig" oc logout >/dev/null 2>&1 || true
  done
}

# Wipe credentials from memory as soon as they are no longer needed.
auth_scrub() {
  MOC_PASSWORD=""; MOC_TOKEN=""
  unset MOC_PASSWORD MOC_TOKEN
}
