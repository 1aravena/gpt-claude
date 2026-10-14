import asyncio
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
temp = tempfile.TemporaryDirectory()
os.environ['CHATGPT_TOKEN_DIR'] = temp.name
import httpx
import litellm
import yaml
from gpt_claude import proxy
from litellm.llms.chatgpt.authenticator import Authenticator
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

litellm.suppress_debug_info = True
litellm.turn_off_message_logging = True
requests = []


async def fake_post(self, url, **kwargs):
    body = kwargs.get('json') or json.loads(kwargs.get('data') or kwargs.get('content'))
    assert url == 'https://chatgpt.com/backend-api/codex/responses', url
    assert body['reasoning']['effort'] == 'xhigh', body.get('reasoning')
    assert body['store'] is False
    assert body['stream'] is True
    assert body['tools'][0]['type'] == 'function'
    assert body['tools'][0]['name'] == 'echo_local'
    assert 'fixture system instruction' in body['instructions']
    assert all(x.get('role') != 'system' for x in body['input'])
    requests.append({'endpoint': url, 'model': body['model'], 'effort': body['reasoning']['effort'], 'tool_type': body['tools'][0]['type']})
    payload = {'id': 'resp_fixture', 'object': 'response', 'created_at': 1, 'status': 'completed',
               'model': body['model'], 'output': [{'type': 'message', 'id': 'msg_fixture', 'status': 'completed', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'fixture_ok', 'annotations': []}]}],
               'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}}
    completed = {'type': 'response.completed', 'response': payload}
    stream = 'event: response.completed\ndata: ' + json.dumps(completed) + '\n\n'
    return httpx.Response(200, content=stream, headers={'content-type': 'text/event-stream'}, request=httpx.Request('POST', url))


async def check():
    from importlib.resources import files
    data = yaml.safe_load(files('gpt_claude').joinpath('config.yaml').read_text())
    with patch.object(Authenticator, 'get_access_token', return_value='fixture-token'), patch.object(Authenticator, 'get_account_id', return_value='fixture-account'), patch.object(AsyncHTTPHandler, 'post', fake_post):
        router = litellm.Router(model_list=data['model_list'], num_retries=0, disable_cooldowns=True)
        for alias in ['gpt-sol', 'gpt-astra']:
            result = await router.aanthropic_messages(model=alias, max_tokens=32,
                system='fixture system instruction',
                messages=[{'role': 'user', 'content': 'fixture request'}],
                thinking={'type': 'adaptive'}, output_config={'effort': 'xhigh'},
                tools=[{'name': 'echo_local', 'description': 'Local fixture', 'input_schema': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']}}])
            assert result['content'][0]['text'] == 'fixture_ok', result
    assert {r['model'] for r in requests} == {'gpt-6.1-sol', 'gpt-6-astra'}
    print(json.dumps({'adapter_requests_verified': requests}, indent=2))


asyncio.run(check())
