#!/bin/sh
# monitoring/alertmanager/render-config.sh
# Renders alertmanager.yml.tmpl to stdout. No side effects, no exec — so the
# rendering can be tested directly (tests/unit/test_alertmanager_config.py)
# rather than only by watching a container fail to start.
#
# Two transformations, in order:
#
#   1. Conditional blocks. Everything between `# @if VAR` and `# @endif` is kept
#      only when VAR is set and non-empty; otherwise the whole block, markers
#      included, is dropped. This is what lets the stack start with no
#      notification secrets configured: alertmanager rejects a telegram_config
#      with an empty bot_token, an email_config with an empty `to`, and a
#      pagerduty_config with an empty routing_key, but it accepts a receiver
#      with no integrations at all.
#
#   2. ${VAR} and ${VAR:-default} substitution, done with awk, NOT shell `eval`.
#
# On (2): the original implementation looped over the template running
#     eval "printf '%s\n' \"$line\""
# on every line, which hands each line to the shell as code and crash-looped the
# container in two separate ways:
#
#   a. `set -u` plus any '$' that is not a ${VAR} reference aborts the script.
#      Two comment lines documented P&L thresholds as "> $5" and "$1-$5", so the
#      shell tried to expand positional parameters and died with
#          eval: 5: parameter not set
#   b. Even with comments skipped, quoting inside values could terminate the
#      printf format string and leave the rest to be run as a command:
#          eval: critical: not found
#
# Both are the same root cause: eval. awk does purely textual substitution and
# cannot execute template content, so a future comment mentioning a price, a
# regex backreference, a shell metacharacter, or an apostrophe cannot break
# startup. envsubst is not used because it does not support :- defaults (and is
# absent from the prom/alertmanager base image, which is busybox-based).
set -eu

TMPL="${1:-/etc/alertmanager/alertmanager.yml.tmpl}"
CHANNELS="${2:-$(dirname "$0")/channels.sh}"

# Sets HOPEFX_AM_{TELEGRAM,EMAIL,PAGERDUTY}_ENABLED from the ALERTMANAGER_* env.
# Sourced rather than duplicated so the rendered config and the entrypoint's
# startup banner cannot disagree about which channels are armed.
# shellcheck source=channels.sh
. "$CHANNELS"

awk '
# ── Pass 1 semantics, inlined: conditional blocks ────────────────────────────
/^[[:space:]]*#[[:space:]]*@if[[:space:]]/ {
  name = $0
  sub(/^.*@if[[:space:]]+/, "", name)
  sub(/[[:space:]].*$/, "", name)
  skip = ((name in ENVIRON) && ENVIRON[name] != "") ? 0 : 1
  next
}
/^[[:space:]]*#[[:space:]]*@endif[[:space:]]*$/ { skip = 0; next }
skip == 1 { next }

# ── Pass 2 semantics: ${NAME} and ${NAME:-default} ───────────────────────────
# POSIX semantics: the default is used when NAME is unset OR set-but-empty.
# Only well-formed ${...} references are touched; a bare "$5" or "$foo" is left
# verbatim.
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
' "$TMPL"
