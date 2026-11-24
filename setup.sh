#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
elif [ -x "$HOME/.local/bin/uv" ]; then
    uv_bin="$HOME/.local/bin/uv"
else
    echo 'Installing uv 0.11.24 from astral.sh...'
    curl --fail --location --silent --show-error https://astral.sh/uv/0.11.24/install.sh | sh
    uv_bin="$HOME/.local/bin/uv"
fi
exec "$uv_bin" run --no-project --managed-python --python 3.10.20 "$repo_dir/scripts/setup_envs.py" --uv "$uv_bin" "$@"
