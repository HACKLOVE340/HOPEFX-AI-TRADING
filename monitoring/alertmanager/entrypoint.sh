#!/bin/sh
# monitoring/alertmanager/entrypoint.sh
# Expands ${VAR} and ${VAR:-default} placeholders in alertmanager.yml.tmpl, then
# execs the real alertmanager binary.
#
# Expansion is done with awk, NOT shell `eval`.
#
# The previous implementation looped over the template and ran
#     eval "printf '%s\n' \"$line\""
# on every line. That hands each line to the shell as code, which made template
# content executable and crash-looped the container in two separate ways:
#
#   1. `set -u` + any '$' that is not a ${VAR} reference aborts the script.
#      Two comment lines documented P&L thresholds as "> $5" and "$1-$5", so the
#      shell tried to expand positional parameters and died with
#          eval: 5: parameter not set
#   2. Even with comments skipped, quoting inside values could still terminate
#      the printf format string and leave following text to be run as a command:
#          eval: critical: not found
#
# Both are the same root cause: eval. awk does purely textual substitution and
# cannot execute template content, so a future comment mentioning a price, a
# regex backreference, a shell metacharacter, or an apostrophe cannot break
# startup. envsubst is not used because it does not support :- defaults (and is
# absent from the prom/alertmanager base image, which is busybox-based).
set -eu

TMPL=/etc/alertmanager/alertmanager.yml.tmpl
OUT=/tmp/alertmanager.yml

# ${NAME} and ${NAME:-default}. Matches POSIX semantics: the default is used
# when NAME is unset OR set-but-empty. Only well-formed ${...} references are
# touched; a bare '$5' or '$foo' is left verbatim.
awk '
{
  line = $0
  out = ""
  while (match(line, /\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}/)) {
    tok   = substr(line, RSTART, RLENGTH)
    inner = substr(tok, 3, length(tok) - 3)      # strip leading ${ and trailing }
    sep   = index(inner, ":-")
    if (sep > 0) {
      name = substr(inner, 1, sep - 1)
      def  = substr(inner, sep + 2)
    } else {
      name = inner
      def  = ""
    }
    val = ((name in ENVIRON) && ENVIRON[name] != "") ? ENVIRON[name] : def
    out  = out substr(line, 1, RSTART - 1) val
    line = substr(line, RSTART + RLENGTH)
  }
  print out line
}
' "$TMPL" > "$OUT"

exec /bin/alertmanager \
    --config.file="$OUT" \
    --storage.path=/alertmanager \
    --web.listen-address=:9093 \
    --cluster.listen-address= \
    "$@"
