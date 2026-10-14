"""Local Claude Code launcher and lifecycle for the dedicated LiteLLM proxy."""
from __future__ import annotations

try:
    import fcntl
except ImportError:
    fcntl = None
from contextlib import contextmanager
from importlib.resources import files
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import secrets
import shutil
import socket
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.request

ROOT = Path(os.environ.get('GPT_CLAUDE_HOME', str(Path.home() / '.local/share/gpt-claude'))).expanduser().resolve()
MODELS = {'gpt-sol', 'gpt-astra'}
MODEL_ALIASES = {'sol': 'sonnet', 'astra': 'opus', 'gpt-6.1-sol': 'sonnet', 'gpt-6-astra': 'opus'}


class SetupError(Exception):
    pass


def proxy_port() -> int:
    try:
        port = int(os.environ.get('GPT_CLAUDE_PORT', '4000'))
    except ValueError:
        raise SetupError('GPT_CLAUDE_PORT debe ser un número entre 1 y 65535.') from None
    if not 1 <= port <= 65535:
        raise SetupError('GPT_CLAUDE_PORT debe ser un número entre 1 y 65535.')
    return port


def proxy_url() -> str:
    return f'http://127.0.0.1:{proxy_port()}'


def find_claude() -> str:
    executable = shutil.which('claude')
    if executable is None:
        raise SetupError('No se encontró Claude Code en PATH. Instálalo antes de usar gpt-claude.')
    return executable


def initialize() -> None:
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lifecycle_lock():
        for folder in [ROOT, ROOT / 'auth', ROOT / 'logs']:
            folder.mkdir(mode=0o700, exist_ok=True)
            folder.chmod(0o700)
        for name in ['config.yaml', 'claude-settings.json']:
            destination = ROOT / name
            if not destination.exists():
                with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
                    handle.write(files('gpt_claude').joinpath(name).read_text())
        key_path = ROOT / 'proxy.key'
        if not key_path.exists():
            with os.fdopen(os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
                handle.write('sk-' + secrets.token_hex(32) + '\n')
        key_path.chmod(0o600)


def read_key() -> str:
    try:
        key = (ROOT / 'proxy.key').read_text().strip()
    except OSError:
        raise SetupError('Falta la clave local del proxy; revisa la instalación.') from None
    if not key.startswith('sk-') or len(key) < 40:
        raise SetupError('La clave local del proxy no tiene un formato válido.')
    return key


def proxy_environment() -> dict[str, str]:
    env = os.environ.copy()
    # Never inherit another provider or a development .env into this service.
    for name in list(env):
        if name.startswith(('OPENAI_', 'ANTHROPIC_', 'CHATGPT_', 'LITELLM_')) or name in {'DATABASE_URL', 'REDIS_URL'}:
            env.pop(name)
    env.update(
        CHATGPT_TOKEN_DIR=str(ROOT / 'auth'),
        CHATGPT_AUTH_FILE='auth.json',
        LITELLM_MASTER_KEY=read_key(),
        LITELLM_LOG='ERROR',
        LITELLM_LOCAL_MODEL_COST_MAP='True',
        PYTHONUNBUFFERED='1',
        GPT_CLAUDE_HOME=str(ROOT),
        GPT_CLAUDE_PORT=str(proxy_port()),
    )
    return env


def auth_present() -> bool:
    try:
        data = json.loads((ROOT / 'auth/auth.json').read_text())
        return bool(data.get('access_token') and data.get('refresh_token'))
    except (OSError, ValueError):
        return False


def private_proxy_running() -> bool:
    try:
        pid = int((ROOT / 'proxy.pid').read_text())
        os.kill(pid, 0)
        # A stale PID reused by another program is not our proxy.
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True)
        return 'gpt_claude.proxy' in result.stdout and str(ROOT / 'config.yaml') in result.stdout
    except (OSError, ValueError):
        return False


def http_json(path: str, authenticated: bool = False) -> object:
    headers = {'Authorization': f'Bearer {read_key()}'} if authenticated else {}
    request = urllib.request.Request(proxy_url() + path, headers=headers)
    # Do not route a local readiness request through inherited HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=1) as response:
        return json.load(response)


def ready() -> bool:
    if not private_proxy_running():
        return False
    try:
        health = http_json('/health/readiness')
        data = http_json('/v1/models', authenticated=True)
        return health.get('status') == 'healthy' and MODELS <= {m['id'] for m in data.get('data', [])}
    except (OSError, ValueError, KeyError, SetupError):
        return False


def wait_ready(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready():
            return
        time.sleep(0.25)
    raise SetupError('El proxy no quedó listo en 30 segundos. Ejecuta gpt-claude-service status.')


def port_busy() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', proxy_port())) == 0


@contextmanager
def lifecycle_lock():
    with (ROOT / 'lifecycle.lock').open('a') as handle:
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise SetupError('Otro inicio, cierre o login sigue en curso. Vuelve a intentar.') from None
                time.sleep(0.1)
        yield


def clients_active() -> bool:
    if not ROOT.exists():
        return False
    with (ROOT / 'clients.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True


def start() -> None:
    if not auth_present():
        raise SetupError('Falta el login de ChatGPT. Ejecuta gpt-claude-service login.')
    if not private_proxy_running():
        if port_busy():
            raise SetupError(f'El puerto {proxy_port()} está ocupado por otro proceso. No se ha detenido ese proceso.')
        subprocess.Popen([sys.executable, '-m', 'gpt_claude.launcher', 'proxy'], cwd=ROOT, env=proxy_environment(), start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_ready()


@contextmanager
def proxy_lease():
    if not auth_present():
        raise SetupError('Falta el login de ChatGPT. Ejecuta gpt-claude-service login.')
    lease = (ROOT / 'clients.lock').open('a')
    try:
        # Serialize start/stop with the idle watchdog. Kernel locks disappear
        # even if a launcher is killed, so there is no stale reference count.
        with lifecycle_lock():
            fcntl.flock(lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
            start()
        yield
    finally:
        lease.close()
        deadline = time.monotonic() + 8
        while private_proxy_running() and not clients_active() and time.monotonic() < deadline:
            time.sleep(0.1)


def translate_arguments(arguments: list[str]) -> list[str]:
    result = []
    i = 0
    while i < len(arguments):
        arg = arguments[i]
        if arg == '--':
            result.extend(arguments[i:])
            break
        if arg == '--model':
            if i + 1 == len(arguments):
                raise SetupError('--model necesita un valor: sol o astra.')
            value = arguments[i + 1]
            result.extend([arg, MODEL_ALIASES.get(value, value)])
            i += 2
            continue
        if arg.startswith('--model='):
            value = arg.partition('=')[2]
            arg = '--model=' + MODEL_ALIASES.get(value, value)
        result.append(arg)
        i += 1
    return result


def claude_command(arguments: list[str]) -> tuple[list[str], dict[str, str]]:
    args = translate_arguments(arguments)
    env = os.environ.copy()
    for name in list(env):
        if name.startswith('ANTHROPIC_') or name in {'CLAUDE_CONFIG_DIR', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY', 'CLAUDE_CODE_SUBAGENT_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE'}:
            env.pop(name)
    env.update(ANTHROPIC_BASE_URL=proxy_url(), ANTHROPIC_AUTH_TOKEN=read_key(), CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY='0', ENABLE_TOOL_SEARCH='false', CLAUDE_CODE_MAX_CONTEXT_TOKENS='922000', ENABLE_CLAUDEAI_MCP_SERVERS='false')
    for tier, model, name in [('SONNET', 'gpt-sol', 'GPT-6.1 Sol'), ('OPUS', 'gpt-astra', 'GPT-6 Astra'), ('HAIKU', 'gpt-sol', 'GPT-6.1 Sol'), ('FABLE', 'gpt-astra', 'GPT-6 Astra')]:
        env[f'ANTHROPIC_DEFAULT_{tier}_MODEL'] = model
        env[f'ANTHROPIC_DEFAULT_{tier}_MODEL_NAME'] = name
        env[f'ANTHROPIC_DEFAULT_{tier}_MODEL_SUPPORTED_CAPABILITIES'] = 'effort,xhigh_effort,max_effort,thinking,adaptive_thinking'
    return [find_claude(), '--settings', str(ROOT / 'claude-settings.json'), *args], env


def launch_claude(arguments: list[str]) -> int:
    # Help and version remain usable even while the service is stopped.
    if any(a in {'--help', '-h', '--version', '-v'} for a in arguments):
        executable = find_claude()
        os.execve(executable, [executable, *translate_arguments(arguments)], os.environ.copy())
    initialize()
    command, env = claude_command(arguments)
    with proxy_lease():
        child = subprocess.Popen(command, env=env)
        old_handlers = {}
        def forward(signum, frame):
            # Terminal Ctrl-C already reaches the child's foreground group.
            if signum == signal.SIGINT and os.isatty(0):
                return
            if child.poll() is None:
                child.send_signal(signum)
        for signum in [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]:
            old_handlers[signum] = signal.signal(signum, forward)
        try:
            code = child.wait()
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait()
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)
    if code < 0:
        signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
    return code


def login_when_idle() -> None:
    if clients_active() or private_proxy_running():
        raise SetupError('Cierra las sesiones de gpt-claude antes de renovar el login.')
    login_env = proxy_environment()
    os.environ.clear()
    os.environ.update(login_env)
    os.umask(0o077)
    auth_path = ROOT / 'auth/auth.json'
    backup = ROOT / 'auth/auth.previous.json'
    ROOT.joinpath('auth').mkdir(mode=0o700, exist_ok=True)
    # Only the dedicated login is replaced; Codex's cache and Keychain are untouched.
    if auth_path.exists():
        auth_path.replace(backup)
    try:
        from litellm.llms.chatgpt.authenticator import Authenticator
        Authenticator().get_access_token()
        auth_path.chmod(0o600)
        backup.unlink(missing_ok=True)
    except KeyboardInterrupt:
        if backup.exists():
            backup.replace(auth_path)
        raise
    except Exception:
        if backup.exists():
            backup.replace(auth_path)
        raise SetupError('El login no se completó. Comprueba el acceso por dispositivo y vuelve a ejecutar gpt-claude-service login.') from None
    print('Login de ChatGPT completado. Credenciales guardadas en el entorno dedicado.', flush=True)


def service_login() -> None:
    with lifecycle_lock():
        login_when_idle()


def safe_log_event(line: str) -> str | None:
    # Log an allowlisted event, never upstream text, exception bodies or payloads.
    if line.strip() in {f'wire_request model={model} effort={effort}' for model in ['gpt-6.1-sol', 'gpt-6-astra'] for effort in ['low', 'medium', 'high', 'xhigh', 'max']}:
        return line.strip()
    lowered = line.lower()
    if 'application startup complete' in lowered:
        return 'proxy_ready'
    if 'application shutdown complete' in lowered:
        return 'proxy_shutdown'
    if 'device-code login needs a human' in lowered or 'refresh token failed' in lowered:
        return 'chatgpt_login_required'
    if 'address already in use' in lowered:
        return 'proxy_port_busy'
    if 'error' in lowered or 'traceback' in lowered:
        return 'proxy_error_details_omitted'
    return None


def run_proxy() -> int:
    os.umask(0o077)
    lock_file = (ROOT / 'proxy.lock').open('a')
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SetupError('Ya hay una instancia de este proxy en ejecución.') from None
    log_dir = ROOT / 'logs'
    log_dir.mkdir(mode=0o700, exist_ok=True)
    logger = logging.getLogger('gpt-claude-service')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_dir / 'service.log', maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(handler)
    if not auth_present():
        logger.info('chatgpt_login_required')
        raise SetupError('Falta el login de ChatGPT; no se inicia el proxy en segundo plano.')
    if port_busy():
        logger.info('proxy_port_busy')
        raise SetupError(f'El puerto {proxy_port()} está ocupado.')
    child = subprocess.Popen([sys.executable, '-m', 'gpt_claude.proxy', '--config', str(ROOT / 'config.yaml'), '--host', '127.0.0.1', '--port', str(proxy_port()), '--num_workers', '1'], cwd=ROOT, env=proxy_environment(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    (ROOT / 'proxy.pid').write_text(str(child.pid))
    finished = threading.Event()
    idle_shutdown = threading.Event()
    def idle_watchdog():
        while not finished.wait(0.5):
            with (ROOT / 'lifecycle.lock').open('a') as mutex:
                try:
                    fcntl.flock(mutex, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                if clients_active():
                    continue
                idle_shutdown.set()
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                # Keep the lifecycle lock until PID cleanup and proxy.lock
                # release, so a new session cannot race the last shutdown.
                finished.wait(8)
                return
    watchdog = threading.Thread(target=idle_watchdog, daemon=True)
    watchdog.start()
    def forward(signum, frame):
        if child.poll() is None:
            child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    logger.info('proxy_start pid=%s', child.pid)
    try:
        for line in child.stdout:
            event = safe_log_event(line)
            if event:
                logger.info(event)
        code = child.wait()
        logger.info('proxy_exit code=%s', code)
        return 0 if idle_shutdown.is_set() else code
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        (ROOT / 'proxy.pid').unlink(missing_ok=True)
        lock_file.close()
        finished.set()
        watchdog.join(timeout=1)


def service(arguments: list[str]) -> int:
    if len(arguments) != 1 or arguments[0] not in {'status', 'login'}:
        print('Uso: gpt-claude-service status|login. LiteLLM inicia y termina con gpt-claude.')
        return 2
    action = arguments[0]
    if action == 'status':
        state = {'mode': 'on_demand', 'active_sessions': clients_active(), 'proxy_process_running': private_proxy_running(), 'proxy_ready': ready(), 'chatgpt_login_present': auth_present()}
        print(json.dumps(state, indent=2))
        print('Este estado es local: no comprueba cuota ni hace llamadas a GPT.')
        return 0
    if action == 'login':
        initialize()
        service_login()
    return 0


def main(mode: str | None = None) -> int:
    try:
        if fcntl is None:
            raise SetupError('Usa macOS, Linux o Windows con WSL; Windows nativo no está soportado.')
        arguments = sys.argv[1:]
        if mode is None and arguments:
            mode, arguments = arguments[0], arguments[1:]
        if mode is None:
            return 2
        if mode == 'claude':
            return launch_claude(arguments)
        elif mode == 'service':
            return service(arguments)
        elif mode == 'proxy':
            return run_proxy()
        return 2
    except SetupError as error:
        print(f'gpt-claude: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def claude_main() -> int:
    return main('claude')


def service_main() -> int:
    return main('service')


if __name__ == '__main__':
    raise SystemExit(main())
