# Shared helpers for the cstef/actions composite actions.
# Sourced from an action's script (after `set -euo pipefail`):
#   source "$GITHUB_ACTION_PATH/../_lib/common.sh"

# Validate a version/tag before it flows into a download URL (no shell/URL injection).
wa_check_version() {
  case "$1" in
    *[!A-Za-z0-9._-]*) echo "invalid version: $1" >&2; exit 1 ;;
  esac
}

# Normalized CPU arch. Echoes `x86_64` or `aarch64`; aborts on anything else.
# Use as: arch=$(wa_arch)  -- the assignment propagates the abort under `set -e`.
wa_arch() {
  case "$(uname -m)" in
    x86_64|amd64)  echo x86_64 ;;
    aarch64|arm64) echo aarch64 ;;
    *) echo "unsupported arch: $(uname -m)" >&2; exit 1 ;;
  esac
}
