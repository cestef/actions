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

# Install s5cmd (if missing) and export S3 creds/region. Expects these env vars set by
# the action: INPUT_ACCESS_KEY_ID, INPUT_SECRET_ACCESS_KEY, INPUT_REGION. Pair with s5().
wa_s3_init() {
  if ! command -v s5cmd >/dev/null; then
    local a sl ver=2.3.0 d="$HOME/.local/bin"
    a=$(wa_arch)
    case "$a" in
      x86_64)  sl=Linux-64bit ;;
      aarch64) sl=Linux-arm64 ;;
    esac
    mkdir -p "$d"
    curl -fsSL "https://github.com/peak/s5cmd/releases/download/v$ver/s5cmd_${ver}_${sl}.tar.gz" \
      | tar -xz -C "$d" s5cmd
    export PATH="$d:$PATH"
    echo "$d" >> "$GITHUB_PATH"
  fi
  export AWS_ACCESS_KEY_ID="$INPUT_ACCESS_KEY_ID"
  export AWS_SECRET_ACCESS_KEY="$INPUT_SECRET_ACCESS_KEY"
  export AWS_REGION="$INPUT_REGION" AWS_DEFAULT_REGION="$INPUT_REGION"
}

# Run s5cmd against INPUT_ENDPOINT if set (R2), else default AWS S3.
s5() {
  if [ -n "${INPUT_ENDPOINT:-}" ]; then s5cmd --endpoint-url "$INPUT_ENDPOINT" "$@"; else s5cmd "$@"; fi
}
