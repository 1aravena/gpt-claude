# gpt-claude

[![CI](https://github.com/1aravena/gpt-claude/actions/workflows/ci.yml/badge.svg)](https://github.com/1aravena/gpt-claude/actions/workflows/ci.yml)

Usa **Claude Code con modelos GPT** mediante un proxy local de LiteLLM y un
login dedicado de ChatGPT. Ejecuta `gpt-claude` desde cualquier proyecto:
el proxy arranca al abrir la primera sesión y se apaga al cerrar la última.

- GPT-6.1 Sol y GPT-6 Astra en el selector `/model`.
- Una sola instancia local compartida entre sesiones simultáneas.
- Conserva los plugins, instrucciones, MCP locales y sesiones de Claude Code.
- Credenciales propias en cada máquina, fuera del repo.
- Sin servicio permanente ni inicio automático al entrar al sistema.

Proyecto independiente, sin afiliación con OpenAI ni Anthropic. Claude Code
se instala por separado; este repo distribuye el launcher y su adaptador.

| Plataforma | Instalador |
|---|---|
| Mac (Intel y Apple Silicon) / Linux | [`install.sh`](install.sh) |
| Windows 10/11 con WSL2 | [`install-windows.ps1`](install-windows.ps1), [guía de Windows](docs/windows.md) |

## Requisitos

- **macOS o Linux**. En Windows, usa **WSL2** e instala todo dentro de WSL.
  Windows nativo no está soportado.
- [Claude Code](https://code.claude.com/docs/en/setup), accesible como `claude`
  en `PATH`.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) y Git.
- Una cuenta ChatGPT con acceso a los modelos usados por Codex.
  Disponibilidad, cuotas y acceso dependen de tu cuenta.
- Puerto local `4000` libre, o un puerto alternativo con `GPT_CLAUDE_PORT`.

El instalador usa Python **3.14**, descargado por uv si hace falta,
LiteLLM **1.105.0** y las versiones fijadas en `requirements.lock`.

## Instalación en Mac / Linux

```sh
git clone https://github.com/1aravena/gpt-claude.git
cd gpt-claude
./install.sh
```

Abre una terminal nueva y completa tu propio login:

```sh
gpt-claude-service login
gpt-claude-service status
```

El login muestra una URL y un código para autorizar en el navegador.
Si el acceso por dispositivo está deshabilitado en tu cuenta, habilítalo
antes de reintentar. Nunca compartas el código de autorización.

Si el shell no encuentra los comandos, ejecuta `uv tool update-shell`
y abre otra terminal.

## Instalación en Windows

La versión de Windows ejecuta Claude Code y el proxy dentro de **WSL2**.
Primero instala Ubuntu desde PowerShell como administrador:

```powershell
wsl --install -d Ubuntu
```

Reinicia si Windows lo solicita, abre Ubuntu y crea tu usuario Linux.
Después, desde PowerShell normal:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/1aravena/gpt-claude/main/install-windows.ps1 -OutFile install-windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1
```

El instalador comprueba WSL2, prepara Git/curl si faltan, instala uv y
Claude Code dentro de Linux y ejecuta el instalador compartido. Luego
abre una terminal Ubuntu y ejecuta `gpt-claude-service login` y
`gpt-claude`. Puedes elegir otra distro Ubuntu con
`-Distribution Ubuntu-24.04`.

La [guía de Windows](docs/windows.md) incluye la primera prueba y los
comandos de diagnóstico. Mac y WSL mantienen sus propios datos y
configuración. El instalador no reinicia Windows ni convierte distros.

## Uso

```sh
cd /ruta/a/tu/proyecto
gpt-claude
gpt-claude --model sol
gpt-claude --model astra
gpt-claude -p "Explica este proyecto"
gpt-claude --resume
gpt-claude --permission-mode plan
```

Los argumentos se pasan a Claude Code. Los nombres `sol` y `astra` se
traducen a sus aliases `sonnet` y `opus`; también se aceptan
`gpt-6.1-sol` y `gpt-6-astra`.

`/model` permite elegir GPT-6.1 Sol o GPT-6 Astra. La selección usa los
aliases de Claude y se comparte con tu Claude habitual: elegir Astra
guarda `opus`, por ejemplo. `--model` elige el modelo para ese arranque.

La configuración inicial usa esfuerzo `xhigh`. Puedes ajustar
`effortLevel` en `~/.local/share/gpt-claude/claude-settings.json`.

Se conservan los permisos normales de Claude Code. Para omitir las
confirmaciones explícitamente:

```sh
gpt-claude --dangerously-skip-permissions
```

Ese flag permite ejecutar herramientas sin pedir aprobación; úsalo
solamente en proyectos y entornos que hayas decidido confiar.

## Estado y credenciales

```sh
gpt-claude-service status
gpt-claude-service login
```

`status` revisa el estado local sin arrancar el proxy ni hacer llamadas
a GPT. En reposo, `active_sessions`, `proxy_process_running` y
`proxy_ready` son `false`.

Cierra las sesiones antes de renovar el login. Las credenciales quedan
en `~/.local/share/gpt-claude/auth/auth.json`; no se reutiliza ni modifica
el login de Codex. Un login fallido restaura las credenciales anteriores.

La configuración, clave local y logs viven en
`~/.local/share/gpt-claude/`. Para un entorno separado:

```sh
export GPT_CLAUDE_HOME="$HOME/.local/share/gpt-claude-alternativo"
export GPT_CLAUDE_PORT=14000
gpt-claude-service login
```

El proxy escucha exclusivamente en `127.0.0.1` (puerto `4000` por defecto) y exige una clave
local generada por instalación. No lo expongas a la red. Los logs
`logs/service.log` registran solamente eventos permitidos, sin guardar
prompts, respuestas ni credenciales; rotan a 5 MB con tres respaldos.

## Límites conocidos

- El login y acceso mediante el proveedor `chatgpt` dependen de LiteLLM
  y del backend de suscripción. No hay garantía de estabilidad ni de
  compatibilidad futura; revisa las condiciones vigentes de tu cuenta.
- Los conectores de claude.ai y Remote Control no están disponibles
  mediante este gateway. Los MCP locales siguen habilitados.
- Claude Code puede mostrar estimaciones de coste o «API Usage Billing»
  al clasificar la conexión como gateway. Este paquete no configura una
  API key de OpenAI; esas estimaciones no verifican tu facturación.
- Un puerto ocupado produce un error; no se detiene el proceso
  que lo ocupa. El cierre del proxy puede tardar unos segundos.
- El selector y capacidades anunciadas dependen de la versión de
  Claude Code. Las cuotas y acceso real a los modelos no se comprueban
  con `status`.
- El adaptador corrige el traslado de instrucciones `system` a
  `instructions` para LiteLLM 1.105.0. Rechaza otra versión hasta que
  se haya verificado la compatibilidad.

## Actualización y desinstalación

Cierra las sesiones antes de actualizar:

```sh
cd gpt-claude
git pull --ff-only
uv tool install --reinstall --python 3.14 --constraints requirements.lock .
```

Los datos y la configuración del usuario se conservan. No actualices
LiteLLM por separado sin validar el adaptador.

Para retirar los comandos, cierra las sesiones y ejecuta:

```sh
uv tool uninstall gpt-claude
```

La desinstalación conserva la carpeta de datos y las credenciales.
Si también quieres borrarlas, elimina manualmente el directorio
`~/.local/share/gpt-claude/` o el indicado por `GPT_CLAUDE_HOME`.

## Desarrollo y pruebas

```sh
uv venv --python 3.14
uv pip install --python .venv/bin/python --constraints requirements.lock .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/check_adapter.py
.venv/bin/python tests/check_lifecycle.py
```

Las pruebas del adaptador simulan el servidor remoto. La prueba de
ciclo de vida abre un proxy real en localhost con un Claude simulado y
credenciales ficticias: verifica sesiones simultáneas, cierre de la
última sesión y limpieza al matar el launcher, sin llamadas a GPT.
Usa un puerto efímero aislado. CI ejecuta estas pruebas en macOS y Linux,
y verifica el instalador con PowerShell 5.1 y 7 en un runner Windows
usando WSL simulado. La prueba en una máquina Windows con WSL2 real y
login ChatGPT se realiza con la [guía de Windows](docs/windows.md).

## Licencia

[MIT](LICENSE). Las dependencias y Claude Code conservan sus propias licencias.
