"""Exercise the real local proxy with fake Claude/auth; never call GPT."""
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time

from gpt_claude import launcher as app


def wait_idle():
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not app.private_proxy_running() and not app.port_busy():
            return
        time.sleep(0.1)
    raise AssertionError('The proxy remained alive without clients.')


def started(process):
    readable, _, _ = select.select([process.stdout], [], [], 40)
    if not readable:
        raise AssertionError('Launcher timed out before starting fake Claude.')
    line = process.stdout.readline()
    if not line:
        raise AssertionError(process.stderr.read())
    return json.loads(line)


def launch(seconds):
    return subprocess.Popen(
        [sys.executable, '-m', 'gpt_claude.launcher', 'claude', '--model', 'sol', str(seconds)],
        env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def check():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        os.environ['GPT_CLAUDE_PORT'] = str(reservation.getsockname()[1])
    assert not app.port_busy(), 'Selected test port is busy; do not stop the unrelated process.'
    with tempfile.TemporaryDirectory(prefix='gpt claude lifecycle ') as temporary:
        app.ROOT = Path(temporary) / 'state with spaces'
        app.initialize()
        (app.ROOT / 'auth/auth.json').write_text(json.dumps({
            'access_token': 'fixture-only', 'refresh_token': 'fixture-only',
            'expires_at': time.time() + 3600, 'account_id': 'fixture-account',
        }))
        binaries = Path(temporary) / 'bin'
        binaries.mkdir()
        fake = binaries / 'claude'
        fake.write_text('#!' + sys.executable + '\n'
            'import json,os,sys,time\n'
            'if "--version" in sys.argv:\n'
            '    print("fixture-claude"); sys.exit(0)\n'
            'print(json.dumps({"ready":True,"pid":os.getpid()}),flush=True)\n'
            'time.sleep(float(sys.argv[-1]))\n')
        fake.chmod(0o700)
        os.environ['GPT_CLAUDE_HOME'] = str(app.ROOT)
        os.environ['PATH'] = str(binaries) + os.pathsep + os.environ['PATH']
        version = subprocess.run(
            [sys.executable, '-m', 'gpt_claude.launcher', 'claude', '--version'],
            capture_output=True, text=True, timeout=10,
        )
        assert version.returncode == 0, version.stderr
        assert not app.private_proxy_running()

        long = launch(6)
        short = launch(1)
        try:
            started(long)
            started(short)
            assert app.ready() and app.clients_active()
            pid = int((app.ROOT / 'proxy.pid').read_text())
            short.wait(timeout=10)
            assert short.returncode == 0
            assert long.poll() is None and app.ready()
            assert int((app.ROOT / 'proxy.pid').read_text()) == pid
            long.wait(timeout=20)
            assert long.returncode == 0
            wait_idle()
        finally:
            for process in [short, long]:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
                process.stdout.close()
                process.stderr.close()

        crashed = launch(60)
        info = None
        try:
            info = started(crashed)
            assert app.ready()
            crashed.kill()
            crashed.wait(timeout=5)
            wait_idle()
        finally:
            if crashed.poll() is None:
                crashed.kill()
                crashed.wait(timeout=5)
            if info is not None:
                try:
                    os.kill(info['pid'], signal.SIGTERM)
                except ProcessLookupError:
                    pass
            crashed.stdout.close()
            crashed.stderr.close()
        print('PASS: on-demand start, shared proxy, last-client shutdown, killed launcher, version, paths with spaces')


if __name__ == '__main__':
    check()
