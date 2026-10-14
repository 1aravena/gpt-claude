#!/bin/sh
set -eu

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "Usa macOS, Linux o Windows con WSL." >&2; exit 1 ;;
esac

command -v uv >/dev/null 2>&1 || {
  echo "Instala uv primero: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
}
command -v claude >/dev/null 2>&1 || {
  echo "Instala Claude Code primero: https://code.claude.com/docs/en/setup" >&2
  exit 1
}

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
uv tool install --python 3.14 --constraints "$repo_dir/requirements.lock" "$repo_dir"
echo "Instalado. Abre una terminal nueva y ejecuta: gpt-claude-service login"
echo "Si no encuentras el comando, ejecuta: uv tool update-shell"
