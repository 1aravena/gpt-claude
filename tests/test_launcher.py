import importlib.util
import json
import os
from pathlib import Path
import tempfile
import signal
import subprocess
import sys
import unittest
import types
import contextlib
import io
from unittest.mock import patch

from gpt_claude import launcher as app

SOURCE = Path(app.__file__)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root.joinpath('proxy.key').write_text('sk-' + 'a' * 64)
        self.old_root = app.ROOT
        app.ROOT = self.root
        self.claude = patch.object(app, 'find_claude', return_value='/fixture/claude')
        self.claude.start()

    def tearDown(self):
        self.claude.stop()
        app.ROOT = self.old_root
        self.temp.cleanup()

    def test_models_translate_without_touching_prompt_or_delimiter(self):
        self.assertEqual(app.translate_arguments(['--model', 'astra', '-p', 'literal $() and "quotes"']), ['--model', 'opus', '-p', 'literal $() and "quotes"'])
        self.assertEqual(app.translate_arguments(['--model=sol', '--', '--model', 'astra']), ['--model=sonnet', '--', '--model', 'astra'])
        with self.assertRaises(app.SetupError):
            app.translate_arguments(['--model'])

    def test_native_permissions_and_saved_model_are_not_overridden(self):
        args, env = app.claude_command(['--resume'])
        self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertNotIn('--model', args)
        self.assertEqual(args[-1], '--resume')
        self.assertEqual(env['ANTHROPIC_DEFAULT_OPUS_MODEL'], 'gpt-astra')

    def test_explicit_permission_mode_respected(self):
        for args in [['--permission-mode', 'plan'], ['--permission-mode=manual'], ['--dangerously-skip-permissions']]:
            command, _ = app.claude_command(args)
            self.assertEqual(command[3:], args)

    def test_provider_credentials_are_process_scoped(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'secret', 'ANTHROPIC_BASE_URL': 'https://other', 'CLAUDE_CONFIG_DIR': '/different', 'CLAUDE_CODE_USE_VERTEX': '1', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE': '1', 'ENABLE_CLAUDEAI_MCP_SERVERS': 'true'}):
            command, env = app.claude_command([])
            self.assertNotIn('ANTHROPIC_API_KEY', env)
            self.assertNotIn('CLAUDE_CONFIG_DIR', env)
            self.assertNotIn('CLAUDE_CODE_USE_VERTEX', env)
            self.assertNotIn('CLAUDE_CODE_SUBAGENT_MODEL_FORCE', env)
            self.assertEqual(os.environ['ANTHROPIC_API_KEY'], 'secret')
            self.assertEqual(env['ANTHROPIC_BASE_URL'], app.proxy_url())
            self.assertEqual(env['ENABLE_CLAUDEAI_MCP_SERVERS'], 'false')
            self.assertEqual(os.environ['ENABLE_CLAUDEAI_MCP_SERVERS'], 'true')
            self.assertNotIn(env['ANTHROPIC_AUTH_TOKEN'], json.dumps(command))

    def test_log_event_never_contains_body_or_secret(self):
        for line in ['ERROR sk-secret prompt: private response: secret', 'Traceback payload=user-secret', 'Application startup complete sk-secret']:
            self.assertNotIn('secret', app.safe_log_event(line))
        self.assertIsNone(app.safe_log_event('user prompt and response without event'))

    def test_readiness_requires_our_authenticated_model_inventory(self):
        with patch.object(app, 'private_proxy_running', return_value=True), patch.object(app, 'http_json', side_effect=[{'status': 'healthy'}, {'data': [{'id': 'wrong'}]}]):
            self.assertFalse(app.ready())
        with patch.object(app, 'private_proxy_running', return_value=True), patch.object(app, 'http_json', side_effect=[{'status': 'healthy'}, {'data': [{'id': 'gpt-sol'}, {'id': 'gpt-astra'}]}]):
            self.assertTrue(app.ready())

    def test_launch_preserves_same_cwd_and_arguments(self):
        original = os.getcwd()
        with patch.object(app, 'proxy_lease', return_value=contextlib.nullcontext()), patch.object(app.subprocess, 'Popen') as execute:
            execute.return_value.wait.return_value = 0
            app.launch_claude(['-p', 'read only'])
            self.assertEqual(os.getcwd(), original)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[0][-2:], ['-p', 'read only'])

    def test_start_does_not_kill_unrelated_listener(self):
        with patch.object(app, 'auth_present', return_value=True), patch.object(app, 'private_proxy_running', return_value=False), patch.object(app, 'port_busy', return_value=True), patch.object(app.subprocess, 'Popen') as run:
            with self.assertRaisesRegex(app.SetupError, 'puerto 4000'):
                app.start()
            run.assert_not_called()

    def integration_runner(self, fake_body):
        fake = self.root / 'fake-claude'
        fake.write_text('#!' + sys.executable + '\n' + fake_body)
        fake.chmod(0o700)
        runner = f'''import importlib.util
from pathlib import Path
from contextlib import nullcontext
s=importlib.util.spec_from_file_location('launcher', {str(SOURCE)!r})
a=importlib.util.module_from_spec(s); s.loader.exec_module(a)
a.ROOT=Path({str(self.root)!r}); a.find_claude=lambda: {str(fake)!r}
a.proxy_lease=lambda: nullcontext()
raise SystemExit(a.launch_claude(['--model', 'sol', '-p', 'literal $() and "quotes"']))
'''
        return [sys.executable, '-c', runner]

    def test_real_exec_preserves_exit_code_arguments_and_directory(self):
        runner = self.integration_runner("import json,os,sys\nprint(json.dumps({'cwd':os.getcwd(),'argv':sys.argv[1:]}))\nsys.exit(37)\n")
        result = subprocess.run(runner, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 37)
        data = json.loads(result.stdout)
        self.assertEqual(Path(data['cwd']).resolve(), self.root.resolve())
        self.assertEqual(data['argv'][-4:], ['--model', 'sonnet', '-p', 'literal $() and "quotes"'])

    def test_real_exec_preserves_sigterm(self):
        runner = self.integration_runner("import time\nprint('ready',flush=True)\ntime.sleep(60)\n")
        child = subprocess.Popen(runner, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            child.send_signal(signal.SIGTERM)
            self.assertEqual(child.wait(timeout=5), -signal.SIGTERM)
        finally:
            if child.poll() is None:
                child.kill()
            child.stdout.close()

    def test_login_discards_inherited_provider_overrides(self):
        fake_module = types.ModuleType('litellm.llms.chatgpt.authenticator')
        root = self.root
        class FakeAuthenticator:
            def get_access_token(self):
                assert 'CHATGPT_API_BASE' not in os.environ
                assert 'OPENAI_API_KEY' not in os.environ
                assert 'DATABASE_URL' not in os.environ
                assert os.environ['CHATGPT_TOKEN_DIR'] == str(root/'auth')
                (root/'auth/auth.json').write_text(json.dumps({'access_token':'fixture', 'refresh_token':'fixture'}))
        fake_module.Authenticator = FakeAuthenticator
        with patch.dict(os.environ, {'CHATGPT_API_BASE':'https://other', 'OPENAI_API_KEY':'private', 'DATABASE_URL':'private'}), patch.dict(sys.modules, {'litellm.llms.chatgpt.authenticator':fake_module}), patch.object(app, 'private_proxy_running', return_value=False), contextlib.redirect_stdout(io.StringIO()):
            app.service_login()
        self.assertEqual((root/'auth/auth.json').stat().st_mode & 0o777, 0o600)

    def test_client_lease_is_released_on_exception(self):
        with patch.object(app, 'auth_present', return_value=True), patch.object(app, 'start'), patch.object(app, 'private_proxy_running', return_value=False):
            with self.assertRaises(ValueError):
                with app.proxy_lease():
                    self.assertTrue(app.clients_active())
                    raise ValueError('fixture failure')
            self.assertFalse(app.clients_active())

    def test_nested_clients_keep_proxy_lease_until_last_exit(self):
        with patch.object(app, 'auth_present', return_value=True), patch.object(app, 'start'), patch.object(app, 'private_proxy_running', return_value=False):
            with app.proxy_lease():
                with app.proxy_lease():
                    self.assertTrue(app.clients_active())
                self.assertTrue(app.clients_active())
            self.assertFalse(app.clients_active())

    def test_help_does_not_start_proxy(self):
        with patch.object(app, 'proxy_lease') as lease, patch.object(app.os, 'execve', side_effect=SystemExit(0)) as execute:
            with self.assertRaises(SystemExit):
                app.launch_claude(['--version'])
            lease.assert_not_called()
            execute.assert_called_once()

    def test_initialize_preserves_key_and_custom_settings(self):
        app.initialize()
        original_key = (self.root / 'proxy.key').read_text()
        settings = self.root / 'claude-settings.json'
        settings.write_text('{"effortLevel":"high"}')
        app.initialize()
        self.assertEqual(settings.read_text(), '{"effortLevel":"high"}')
        self.assertEqual((self.root / 'proxy.key').read_text(), original_key)
        for path in [self.root, self.root / 'auth', self.root / 'logs']:
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        for path in [settings, self.root / 'proxy.key', self.root / 'config.yaml']:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_initialize_creates_unique_private_keys(self):
        (self.root / 'proxy.key').unlink()
        app.initialize()
        first = app.read_key()
        self.assertGreaterEqual(len(first), 40)
        (self.root / 'proxy.key').unlink()
        app.initialize()
        self.assertNotEqual(app.read_key(), first)

    def test_missing_claude_has_actionable_error(self):
        self.claude.stop()
        with patch.object(app.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(app.SetupError, 'PATH'):
                app.find_claude()

    def test_status_on_fresh_install_does_not_create_state(self):
        app.ROOT = self.root / 'not-created'
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app.service(['status']), 0)
        self.assertIn('"proxy_process_running": false', output.getvalue())
        self.assertFalse(app.ROOT.exists())

    def test_port_override_is_validated_and_forwarded(self):
        with patch.dict(os.environ, {'GPT_CLAUDE_PORT': '14000'}):
            self.assertEqual(app.proxy_url(), 'http://127.0.0.1:14000')
            _, env = app.claude_command([])
            self.assertEqual(env['ANTHROPIC_BASE_URL'], app.proxy_url())
            self.assertEqual(app.proxy_environment()['GPT_CLAUDE_PORT'], '14000')
        for value in ['no', '0', '65536']:
            with patch.dict(os.environ, {'GPT_CLAUDE_PORT': value}):
                with self.assertRaisesRegex(app.SetupError, 'GPT_CLAUDE_PORT'):
                    app.proxy_port()

    def test_login_failure_restores_existing_credentials(self):
        app.initialize()
        auth = self.root / 'auth/auth.json'
        auth.write_text('{"access_token":"previous","refresh_token":"previous"}')
        fake_module = types.ModuleType('litellm.llms.chatgpt.authenticator')
        class FailingAuthenticator:
            def get_access_token(self):
                raise RuntimeError('private upstream body')
        fake_module.Authenticator = FailingAuthenticator
        with patch.dict(os.environ), patch.dict(sys.modules, {'litellm.llms.chatgpt.authenticator': fake_module}), patch.object(app, 'private_proxy_running', return_value=False):
            with self.assertRaisesRegex(app.SetupError, 'login no se completó'):
                app.service_login()
        self.assertEqual(json.loads(auth.read_text())['access_token'], 'previous')
        self.assertFalse((self.root / 'auth/auth.previous.json').exists())


if __name__ == '__main__':
    unittest.main()
