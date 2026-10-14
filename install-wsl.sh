#!/bin/bash
set -euo pipefail

case "$(uname -s):$(uname -r)" in
  Linux:*WSL2*) ;;
  *) echo "Este instalador requiere Windows con WSL2. En macOS o Linux usa ./install.sh." >&2; exit 1 ;;
esac
if [ "$(id -u)" -eq 0 ]; then
  echo "Ejecuta este instalador con tu usuario de Ubuntu, sin sudo." >&2
  exit 1
fi

export PATH="$HOME/.local/bin:$PATH"
command -v curl >/dev/null 2>&1 || {
  echo "Instala curl dentro de WSL: sudo apt-get update && sudo apt-get install -y curl ca-certificates" >&2
  exit 1
}

native_command() {
  local executable
  executable=$(command -v "$1") || return 1
  case "$executable" in
    /mnt/*|*.exe|*.cmd) return 1 ;;
    *) return 0 ;;
  esac
}

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
if ! native_command uv; then
  curl --fail --silent --show-error --location https://astral.sh/uv/install.sh -o "$temporary/uv.sh"
  UV_NO_MODIFY_PATH=1 sh "$temporary/uv.sh"
fi
if ! native_command claude; then
  curl --fail --silent --show-error --location https://claude.ai/install.sh -o "$temporary/claude.sh"
  bash "$temporary/claude.sh" stable
fi
native_command uv && native_command claude || {
  echo "No se encontraron uv y Claude Code instalados dentro de Linux. Revisa los errores anteriores." >&2
  exit 1
}

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bash "$repo_dir/install.sh"
uv tool update-shell
echo "Cierra y vuelve a abrir Ubuntu. Luego ejecuta: gpt-claude-service login"
