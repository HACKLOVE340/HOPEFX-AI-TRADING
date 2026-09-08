#!/usr/bin/env bash
# scripts/check_secrets.sh
# Pre-commit guard: block commits containing plaintext credentials.
#
# Skips:
#   - Lines with # pragma: allowlist secret
#   - Lines with env var references: ${VAR}, $VAR, ${{ secrets.X }}
#   - Lines with angle-bracket placeholders: <BASE64_ENCODED_...>
#   - Lines with empty values: KEY: ""
#   - Known placeholder words: changeme, placeholder, example, etc.
#   - Template/example files: *.example.yaml, k8s-secrets.yaml, secrets.example.*
#   - Comment lines
#
# Usage:
#   bash scripts/check_secrets.sh          # scan staged files only
#   bash scripts/check_secrets.sh --all    # scan entire working tree

set -euo pipefail

RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCAN_ALL=false
[[ "${1:-}" == "--all" ]] && SCAN_ALL=true

# File path patterns to always exclude
EXCLUDE_PATH_PATTERNS=(
    '\.env\.example'
    '\.secrets\.baseline'
    'check_secrets\.sh'
    'CHANGELOG'
    '\.md$'
    '\.txt$'
    '\.py$'
    '\.js$'
    '\.ts$'
    '\.sh$'
    'node_modules'
    '__pycache__'
    '\.git/'
    'secrets\.example\.'
    'k8s-secrets\.yaml$'
    '\.example\.yaml$'
    '\.example\.yml$'
    'values\.yaml$'
)

# Credential key names to check
CRED_KEYS='(PASSWORD|PASSWD|API_KEY|API_SECRET|SECRET_KEY|ACCESS_TOKEN|AUTH_TOKEN|PRIVATE_KEY|ENCRYPTION_KEY|JWT_SECRET|WEBHOOK_SECRET|BOT_TOKEN|CLIENT_SECRET)'

found=0

is_excluded() {
    local file="$1"
    for pat in "${EXCLUDE_PATH_PATTERNS[@]}"; do
        if echo "$file" | grep -qE "$pat"; then
            return 0
        fi
    done
    return 1
}

scan_content() {
    local file="$1"
    local content="$2"

    is_excluded "$file" && return 0

    local line_num=0
    while IFS= read -r line; do
        line_num=$((line_num + 1))

        # Skip blank lines
        [[ -z "$line" ]] && continue
        # Skip comment lines
        echo "$line" | grep -qE '^\s*#' && continue
        # Skip lines with pragma allowlist
        echo "$line" | grep -qE 'pragma:\s*allowlist\s*secret' && continue

        # Only check lines that have a credential key
        echo "$line" | grep -qiE "${CRED_KEYS}[[:space:]]*[=:][[:space:]]*.+" || continue

        # Skip env var references
        echo "$line" | grep -qE '\$\{|\$[A-Za-z_]' && continue
        # Skip GitHub Actions secrets
        echo "$line" | grep -qE '\$\{\{' && continue
        # Skip angle-bracket placeholders
        echo "$line" | grep -qE '<[A-Z_]' && continue
        # Skip empty values (KEY: "" or KEY: '')
        echo "$line" | grep -qE "[=:][[:space:]]*(\"\"[[:space:]]*$|''[[:space:]]*$|[[:space:]]*$)" && continue
        # Skip structural references — these are never a literal credential.
        echo "$line" | grep -qE '(secretKeyRef|valueFrom|configMapKeyRef)' && continue

        # Skip known safe placeholder values.
        #
        # Anchored to the VALUE, not matched anywhere in the line. The previous
        # version searched the whole line for 'xxx', 'none', 'null' and 'TBD' as
        # substrings, so a genuine credential that happened to contain one was
        # silently skipped:
        #
        #   - an api-key value beginning 'Sxxx' followed by 20 random
        #     characters was skipped because it contains 'xxx'
        #   - a db-password value beginning 'none' followed by 16 random
        #     characters was skipped because it contains 'none'
        #
        # Both were verified to pass the old check. Long, unambiguous words
        # (placeholder, example, changeme, your-) stay substring matches because
        # they do not occur inside real credentials by accident; the short
        # ambiguous ones must now be the entire value.
        value=$(echo "$line" | sed -E 's/^[^=:]*[=:][[:space:]]*//; s/[[:space:]]*#.*$//; s/^["'"'"']//; s/["'"'"'][[:space:]]*$//; s/[[:space:]]*$//')
        echo "$line" | grep -qiE '(placeholder|example|changeme|change_me|replace_me|your[-_]|ci-placeholder|ci-test)' && continue
        echo "$value" | grep -qiE '^(x+|n/?a|none|null|nil|tbd|todo|secret|password|token|key|dummy|fake|test|redacted|\*+|\.\.\.)$' && continue

        echo -e "${RED}[BLOCKED]${NC} ${YELLOW}${file}:${line_num}${NC}: $line"
        found=1

    done <<< "$content"
}

if $SCAN_ALL; then
    while IFS= read -r -d '' file; do
        [[ -f "$file" ]] || continue
        content=$(cat "$file" 2>/dev/null || true)
        scan_content "$file" "$content"
    done < <(find . -type f \( \
        -name "*.yml" -o -name "*.yaml" -o \
        -name "*.env" -o -name "*.cfg" -o \
        -name "*.ini" -o -name "*.conf" \
    \) -not -path "./.git/*" -print0)
else
    while IFS= read -r file; do
        [[ -f "$file" ]] || continue
        content=$(git show ":$file" 2>/dev/null || true)
        scan_content "$file" "$content"
    done < <(git diff --cached --name-only --diff-filter=ACM)
fi

if [[ $found -ne 0 ]]; then
    echo -e "\n${RED}Commit blocked: plaintext credentials detected.${NC}"
    echo "Replace with environment variable references: \${VAR_NAME}"
    echo "Add '# pragma: allowlist secret' to suppress known-safe CI test values."
    echo "See .env.example for the template."
    exit 1
fi

echo "check_secrets: OK — no plaintext credentials found"
exit 0
