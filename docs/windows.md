# gpt-claude en Windows con WSL2

Esta versión usa una terminal Ubuntu en Windows. Claude Code, Python,
LiteLLM y las credenciales se instalan dentro de Linux. El mismo paquete
también funciona en Mac; no necesitas cambiar los modelos ni comandos.

## 1. Preparar WSL2

Necesitas Windows 11 o Windows 10 versión 2004/build 19041 o posterior
para el flujo `wsl --install`. Abre **PowerShell como administrador**:

```powershell
wsl --install -d Ubuntu
```

Reinicia si Windows lo solicita. Abre Ubuntu desde el menú Inicio y
crea tu usuario Linux y contraseña. Usa un usuario normal; no ejecutes
el instalador como `root` ni con `sudo`.

Comprueba desde PowerShell:

```powershell
wsl --list --verbose
```

Ubuntu debe mostrar versión **2**. Si ya usabas WSL1, consulta la
[guía de instalación y conversión de Microsoft](https://learn.microsoft.com/en-us/windows/wsl/install).
El instalador de gpt-claude comprueba WSL2 y utiliza la distro seleccionada.

## 2. Instalar gpt-claude

Abre **PowerShell normal**, sin permisos de administrador:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/1aravena/gpt-claude/main/install-windows.ps1 -OutFile install-windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1
```

`ExecutionPolicy Bypass` se aplica a ese proceso de PowerShell. No
cambia la política permanente de Windows.

Para otra distro Ubuntu instalada:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1 -Distribution Ubuntu-24.04
```

El instalador:

1. Comprueba la distro y que use WSL2.
2. Prepara Git y curl dentro de Ubuntu si faltan. Puede pedir tu
   contraseña Linux para instalar esos paquetes con `sudo apt-get`.
3. Clona el repo en `~/.local/share/gpt-claude-source` dentro de WSL.
4. Instala [uv](https://docs.astral.sh/uv/getting-started/installation/)
   y [Claude Code](https://code.claude.com/docs/en/setup) mediante sus
   instaladores oficiales cuando faltan.
5. Instala gpt-claude con Python 3.14 y sus dependencias fijadas, y
   agrega el directorio de comandos al perfil del shell Linux.

Cierra y vuelve a abrir Ubuntu al terminar. Toda la ejecución se hace
desde esa terminal. Si clonaste el repo directamente dentro de WSL,
también puedes ejecutar `./install-wsl.sh` desde su carpeta.

## 3. Autorizar tu cuenta

Dentro de **Ubuntu**:

```sh
gpt-claude-service login
gpt-claude-service status
```

El login muestra una URL y un código. Abre esa URL en tu navegador de
Windows, autoriza tu cuenta ChatGPT y espera a que la terminal confirme
el login. `status` debe mostrar `chatgpt_login_present: true` y el proxy
apagado mientras no haya sesiones.

Las credenciales quedan en
`~/.local/share/gpt-claude/auth/auth.json` dentro de WSL. Cada equipo
realiza su propio login; no copies los tokens desde tu Mac.

## 4. Primera prueba

Dentro de Ubuntu:

```sh
mkdir -p ~/gpt-claude-prueba
cd ~/gpt-claude-prueba
gpt-claude --model sol -p "Responde solo WINDOWS_OK"
gpt-claude-service status
```

Debe responder `WINDOWS_OK`. Al terminar, el proxy debe apagarse y
`active_sessions`, `proxy_process_running` y `proxy_ready` deben ser
`false`. El comando espera unos segundos para completar el cierre.

Para probar el selector y Astra:

```sh
gpt-claude --model astra
```

Abre `/model` y comprueba que aparezcan GPT-6.1 Sol y GPT-6 Astra.
Sal con `/exit`. Usa `cd ~/tu-proyecto` para trabajar en un repo dentro
de Linux; los archivos de Windows también son accesibles en `/mnt/c/`.

## Diagnóstico

Desde PowerShell:

```powershell
wsl --list --verbose
```

Desde Ubuntu:

```sh
uname -r
command -v claude
claude --version
uv tool list
gpt-claude-service status
```

Si no aparecen los comandos, ejecuta `uv tool update-shell` y abre otra
terminal Ubuntu. Si el puerto 4000 está ocupado, elige otro antes de
iniciar la sesión:

```sh
export GPT_CLAUDE_PORT=14000
gpt-claude --model sol
```

Si el instalador informa que la distro no existe, usa el nombre exacto
de `wsl --list --quiet` con `-Distribution`. Si el login por dispositivo
está deshabilitado, habilítalo en tu cuenta ChatGPT antes de reintentar.
Para reportar un problema, comparte el error y estos diagnósticos; no
compartas `auth.json`, la clave local ni el código de autorización.

## Actualizar o desinstalar

Cierra las sesiones. Para actualizar, vuelve a descargar y ejecutar
`install-windows.ps1`, o usa desde Ubuntu:

```sh
cd ~/.local/share/gpt-claude-source
git pull --ff-only
./install-wsl.sh
```

Para retirar los comandos:

```sh
uv tool uninstall gpt-claude
```

Los datos y credenciales se conservan en `~/.local/share/gpt-claude/`.
