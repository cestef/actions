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

# Install cargo-nextest onto PATH if it is not already there. $1 is the version
# channel or tag ("latest", "0.9.100").
wa_install_nextest() {
  if command -v cargo-nextest >/dev/null; then
    return 0
  fi
  local slug dest
  case "$(uname -s)-$(uname -m)" in
    Linux-aarch64|Linux-arm64) slug=linux-arm-musl ;;
    Linux-x86_64|Linux-amd64)  slug=linux-musl ;;
    Darwin-*)                  slug=mac ;;
    *) echo "unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
  esac
  dest="$HOME/.cargo/bin"; mkdir -p "$dest"
  # Only the version tag flows into the URL; validate it's a plausible channel/tag.
  wa_check_version "$1"
  curl -fsSL "https://get.nexte.st/$1/$slug" | tar -xz -C "$dest" cargo-nextest
  echo "$dest" >> "$GITHUB_PATH"
  export PATH="$dest:$PATH"
}
