# multi-oc

Run a single `oc` command against multiple OpenShift clusters, driven by an
input file. Credentials are typed interactively at a hidden prompt, so they
never appear in your shell history, in `ps` output, or on disk.

## Layout

```
multi-oc/
├── bin/multi-oc            # entrypoint (arg parsing + orchestration)
├── lib/
│   ├── log.sh              # logging helpers (stderr, colorized on TTYs)
│   ├── config.sh           # cluster input-file parsing
│   ├── auth.sh             # credential prompts + oc login/logout
│   └── exec.sh             # per-cluster execution, parallelism, reporting
├── clusters.conf.example   # sample cluster input file
└── README.md
```

Each module is sourced by the entrypoint and does one job, so you can extend
one piece (e.g. add a new auth mode in `lib/auth.sh`, or a new output format
in `lib/exec.sh`) without touching the rest.

## Requirements

- `bash` 4.3+ (associative arrays, `wait -n`)
- `oc` in `PATH`

## Quick start

```sh
cp clusters.conf.example clusters.conf   # then edit with your clusters
./bin/multi-oc -f clusters.conf -- get nodes
```

You'll be prompted once:

```
Username: patrick
Password:            <- hidden while typing
```

and the command runs on every cluster in the file, output prefixed per
cluster:

```
[prod] NAME          STATUS   ROLES    ...
[dr]   NAME          STATUS   ROLES    ...
```

Everything after `--` is passed to `oc` verbatim, so any oc subcommand
works: `get`, `describe`, `adm top nodes`, `apply -f -`, etc.

## Options

| Flag | Description |
|------|-------------|
| `-f, --file FILE` | Cluster input file (required). |
| `-c, --clusters LIST` | Target only these clusters (comma-separated names). |
| `-p, --parallel N` | Run up to N clusters concurrently (default 1). |
| `-o, --output-dir DIR` | Write output to `DIR/<name>.out` / `DIR/<name>.err` instead of the terminal. |
| `-t, --token` | Authenticate with an API token (hidden prompt) instead of username/password. |
| `--keep-login` | Skip `oc logout` on exit. |

Examples:

```sh
# Cluster health across prod and DR, 4 at a time
./bin/multi-oc -f clusters.conf -c prod,dr -p 4 -- get clusteroperators

# Collect JSON reports per cluster into ./reports/
./bin/multi-oc -f clusters.conf -o ./reports -- get pods -A -o json

# Token auth (e.g. when your IdP requires SSO for passwords)
./bin/multi-oc -f clusters.conf --token -- whoami
```

## Cluster input file

Whitespace-separated, one cluster per line; `#` comments and blank lines are
ignored:

```
# name   api-url                              extra oc-login flags (optional)
prod     https://api.prod.example.com:6443
dr       https://api.dr.example.com:6443      --certificate-authority=/etc/pki/dr-ca.crt
lab      https://api.lab.example.com:6443     --insecure-skip-tls-verify=true
```

The optional trailing flags are passed to `oc login` for that cluster only —
useful for custom CAs or lab clusters with self-signed certs.

## How credentials are protected

- Username and password (or token) are read from the terminal with `read`,
  never accepted as command-line arguments — so nothing sensitive can end up
  in `~/.bash_history`.
- The password/token prompt uses `read -s`, so it isn't echoed to the screen.
- The password is piped to `oc login` on **stdin** (oc's own interactive
  prompt), never via `--password`, so it's invisible to `ps` and
  `/proc/*/cmdline`.
- Credential variables are cleared from the shell's memory immediately after
  the logins finish.
- Each cluster gets its own temporary `KUBECONFIG` in a `0700` temp
  directory; your real `~/.kube/config` is never read or modified. On exit
  the tool runs `oc logout` against every cluster (invalidating the session
  tokens server-side) and deletes the temp directory. Use `--keep-login` to
  keep sessions alive instead.

One set of credentials is prompted and reused for all targeted clusters
(the common case with LDAP/SSO-backed clusters). If some clusters need
different credentials, run the tool separately per group using
`--clusters`.

## Exit status

`0` if the command succeeded on every targeted cluster; `1` if any cluster
failed to log in or the command exited non-zero there (failed clusters are
listed at the end).
