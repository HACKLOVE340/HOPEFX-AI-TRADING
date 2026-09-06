#!/usr/bin/env bash
# scripts/install_ollama.sh — install the local inference runtime on Linux/macOS.
#
# Ollama is what runs a model on this machine. Without it the local leg of the
# model chain cannot answer, and `ai/local_model.py` refuses to start rather
# than pretending otherwise.
#
# WHY THIS DOES NOT PIPE CURL INTO A SHELL
#
# The upstream one-liner is `curl -fsSL https://ollama.com/install.sh | sh`.
# That executes whatever the server returns, unread and unverifiable, as root,
# on a machine that executes trades. This downloads the script to a file first,
# so it can be checksummed and inspected, and only then runs it. Set
#
#     OLLAMA_INSTALL_SHA256=<sha256 of the installer you reviewed>
#
# to pin it: the install then REFUSES if upstream changes, instead of running
# the change. Without a pin it still refuses an empty or HTML error page, which
# is the failure that would otherwise be executed as a shell script.
#
# Usage:  bash scripts/install_ollama.sh
set -euo pipefail

INSTALLER_URL="${OLLAMA_INSTALL_URL:-https://ollama.com/install.sh}"
EXPECTED_SHA="${OLLAMA_INSTALL_SHA256:-}"

if command -v ollama >/dev/null 2>&1; then
  echo "ollama: already installed at $(command -v ollama)"
  ollama --version || true
  exit 0
fi

echo "ollama: not present — installing from ${INSTALLER_URL}"

TMPDIR_OLLAMA="$(mktemp -d)"
trap 'rm -rf "${TMPDIR_OLLAMA}"' EXIT
SCRIPT="${TMPDIR_OLLAMA}/install.sh"

if ! curl -fsSL --retry 3 --retry-delay 2 --max-time 120 -o "${SCRIPT}" "${INSTALLER_URL}"; then
  echo "ollama: could not download the installer from ${INSTALLER_URL}" >&2
  echo "        Install it manually: https://ollama.com/download" >&2
  exit 1
fi

# An HTML error page and an empty file are both things that must never reach a
# shell. Checked before anything is executed.
if [ ! -s "${SCRIPT}" ]; then
  echo "ollama: the downloaded installer is empty — refusing to run it" >&2
  exit 1
fi
if head -c 512 "${SCRIPT}" | grep -qiE '<!doctype|<html'; then
  echo "ollama: the download is an HTML page, not a script — refusing to run it" >&2
  exit 1
fi
if ! head -n 1 "${SCRIPT}" | grep -qE '^#!'; then
  echo "ollama: the download has no shebang — refusing to run it" >&2
  exit 1
fi

ACTUAL_SHA="$(sha256sum "${SCRIPT}" | awk '{print $1}')"
echo "ollama: installer sha256 ${ACTUAL_SHA}"
if [ -n "${EXPECTED_SHA}" ]; then
  if [ "${ACTUAL_SHA}" != "${EXPECTED_SHA}" ]; then
    echo "ollama: checksum mismatch — refusing to run it" >&2
    echo "        expected ${EXPECTED_SHA}" >&2
    echo "        actual   ${ACTUAL_SHA}" >&2
    exit 1
  fi
  echo "ollama: checksum matches the pin"
else
  echo "ollama: no OLLAMA_INSTALL_SHA256 pin set — running an unpinned installer."
  echo "        Pin it with the sha256 above once you have reviewed ${SCRIPT##*/}."
fi

sh "${SCRIPT}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama: the installer finished but ollama is still not on PATH" >&2
  echo "        This is a failed install reporting success. See https://ollama.com/download" >&2
  exit 1
fi

echo "ollama: installed at $(command -v ollama)"
ollama --version || true
