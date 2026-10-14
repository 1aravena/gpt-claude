"""Run installer control flow with mocked tools; no installs or downloads."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def run_wsl(self, *, os_name='Linux', kernel='6.6.87-microsoft-standard-WSL2', uid='1000', missing_uv=False):
        with tempfile.TemporaryDirectory(prefix='installer with spaces ') as temporary:
            root = Path(temporary)
            functions = root / 'mock-tools.sh'
            log = root / 'calls.txt'
            functions.write_text('''
uname() { if [ "$1" = '-s' ]; then echo "$TEST_OS"; else echo "$TEST_KERNEL"; fi; }
id() { echo "$TEST_UID"; }
uv() { printf '%s\\n' "$*" >> "$TEST_CALLS"; }
claude() { return 0; }
curl() { echo 'mock download failure' >&2; return 22; }
command() {
  if [ "$1" = '-v' ] && [ "$2" = 'uv' ] && [ "$TEST_MISSING_UV" = '1' ]; then
    echo /mnt/c/Windows/uv.exe
    return 0
  fi
  builtin command "$@"
}
''')
            env = os.environ.copy()
            env.update(BASH_ENV=str(functions), TEST_OS=os_name, TEST_KERNEL=kernel,
                       TEST_UID=uid, TEST_MISSING_UV=str(int(missing_uv)), TEST_CALLS=str(log))
            result = subprocess.run(['bash', str(REPO / 'install-wsl.sh')],
                                    env=env, capture_output=True, text=True, timeout=10)
            calls = log.read_text() if log.exists() else ''
            return result, calls

    def test_wsl_installs_shared_package_and_updates_linux_path(self):
        result, calls = self.run_wsl()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('tool install --reinstall --python 3.14 --constraints', calls)
        self.assertIn(str(REPO / 'requirements.lock'), calls)
        self.assertIn('tool update-shell', calls)

    def test_macos_and_wsl1_do_not_run_wsl_installer(self):
        for settings in [{'os_name': 'Darwin'}, {'kernel': '4.4.0-Microsoft'}]:
            with self.subTest(settings=settings):
                result, calls = self.run_wsl(**settings)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('WSL2', result.stderr)
                self.assertEqual(calls, '')

    def test_root_is_rejected_before_installing(self):
        result, calls = self.run_wsl(uid='0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sin sudo', result.stderr)
        self.assertEqual(calls, '')

    def test_windows_uv_is_not_used_and_download_failure_stops_install(self):
        result, calls = self.run_wsl(missing_uv=True)
        self.assertEqual(result.returncode, 22)
        self.assertIn('mock download failure', result.stderr)
        self.assertEqual(calls, '')

    def test_powershell_bootstrap_has_valid_bash_syntax(self):
        source = (REPO / 'install-windows.ps1').read_text()
        bootstrap = source.split("$bootstrap = @'\n", 1)[1].split("\n'@", 1)[0]
        result = subprocess.run(['bash', '-n'], input=bootstrap, text=True,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
