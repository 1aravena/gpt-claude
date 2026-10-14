#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$Distribution = 'Ubuntu'
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'Instala WSL desde PowerShell como administrador: wsl --install -d Ubuntu. Reinicia Windows y crea tu usuario de Ubuntu.'
}

$installed = @(& wsl.exe --list --quiet)
if ($LASTEXITCODE -ne 0) {
    throw 'WSL no esta listo. Ejecuta wsl --install -d Ubuntu, reinicia e inicializa Ubuntu.'
}
$installed = @($installed | ForEach-Object { ($_ -replace "`0", '').Trim() })
if ($installed -notcontains $Distribution) {
    throw "No se encontro la distribucion '$Distribution'. Revisa wsl --list --quiet o instala Ubuntu con wsl --install -d Ubuntu."
}

$kernel = (& wsl.exe --distribution $Distribution --exec uname -r) -join ''
if ($LASTEXITCODE -ne 0 -or $kernel -notmatch '(?i)WSL2') {
    throw "Se necesita WSL2. Revisa wsl --list --verbose e inicializa '$Distribution' antes de continuar."
}

$bootstrap = @'
set -eu
export PATH="$HOME/.local/bin:$PATH"
if [ "$(id -u)" -eq 0 ]; then
    echo "Abre Ubuntu y configura un usuario normal antes de instalar gpt-claude." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
    if ! command -v sudo >/dev/null 2>&1 || ! command -v apt-get >/dev/null 2>&1; then
        echo "Instala Git y curl dentro de tu distribucion WSL y vuelve a intentar." >&2
        exit 1
    fi
    sudo apt-get update
    sudo apt-get install -y git curl ca-certificates
fi
repo_url='https://github.com/1aravena/gpt-claude.git'
checkout="$HOME/.local/share/gpt-claude-source"
if [ -e "$checkout" ]; then
    if [ "$(git -C "$checkout" remote get-url origin)" != "$repo_url" ]; then
        echo "El directorio de instalacion ya existe y pertenece a otro origen. No se ha reemplazado." >&2
        exit 1
    fi
    git -C "$checkout" pull --ff-only
else
    mkdir -p "$(dirname "$checkout")"
    git clone --depth 1 "$repo_url" "$checkout"
fi
bash "$checkout/install-wsl.sh"
'@

# Base64 avoids native argument quoting differences in Windows PowerShell 5.1.
$bootstrap = $bootstrap -replace "`r`n", "`n"
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($bootstrap))
& wsl.exe --distribution $Distribution --exec bash -lc "printf %s $encoded | base64 -d | bash"
if ($LASTEXITCODE -ne 0) {
    throw 'La instalacion dentro de WSL fallo. Revisa el error anterior y vuelve a ejecutar el instalador.'
}

Write-Host "Listo. Abre tu terminal $Distribution y ejecuta: gpt-claude-service login"
Write-Host 'Despues ejecuta gpt-claude desde la carpeta de tu proyecto dentro de WSL.'
