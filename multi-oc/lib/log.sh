# lib/log.sh
# Logging helpers. All log output goes to stderr so stdout stays clean
# for command results (pipe/redirect friendly).

# Colors only when stderr is a terminal.
if [[ -t 2 ]]; then
  _C_RED=$'\033[31m'; _C_GRN=$'\033[32m'; _C_YLW=$'\033[33m'
  _C_CYN=$'\033[36m'; _C_RST=$'\033[0m'
else
  _C_RED=""; _C_GRN=""; _C_YLW=""; _C_CYN=""; _C_RST=""
fi

log_info()  { printf '%s[info]%s %s\n'  "$_C_CYN" "$_C_RST" "$*" >&2; }
log_ok()    { printf '%s[ ok ]%s %s\n'  "$_C_GRN" "$_C_RST" "$*" >&2; }
log_warn()  { printf '%s[warn]%s %s\n'  "$_C_YLW" "$_C_RST" "$*" >&2; }
log_error() { printf '%s[fail]%s %s\n'  "$_C_RED" "$_C_RST" "$*" >&2; }

die() { log_error "$*"; exit 1; }
