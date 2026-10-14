"""Subscription compatibility fix for the pinned LiteLLM 1.105.0."""
from importlib.metadata import version
from litellm.llms.chatgpt.responses.transformation import ChatGPTResponsesAPIConfig

if version('litellm') != '1.105.0':
    raise RuntimeError('Revalidate the subscription adapter before updating LiteLLM.')

_original_transform = ChatGPTResponsesAPIConfig.transform_responses_api_request


def subscription_request(self, *args, **kwargs):
    request = _original_transform(self, *args, **kwargs)
    model = request.get('model')
    effort = request.get('reasoning', {}).get('effort')
    if model in {'gpt-6.1-sol', 'gpt-6-astra'} and effort in {'low', 'medium', 'high', 'xhigh', 'max'}:
        # The supervisor accepts only these public metadata values in its log.
        print(f'wire_request model={model} effort={effort}', flush=True)
    items = request.get('input')
    if not isinstance(items, list):
        return request
    kept = []
    instructions = []
    for item in items:
        if not isinstance(item, dict) or item.get('role') != 'system':
            kept.append(item)
            continue
        content = item.get('content')
        if isinstance(content, str):
            instructions.append(content)
        elif isinstance(content, list) and all(isinstance(block, dict) and isinstance(block.get('text'), str) for block in content):
            instructions.extend(block['text'] for block in content)
        else:
            raise ValueError('Unsupported system instruction content; refusing to discard it.')
    if instructions:
        # LiteLLM's chat bridge emits system input items. The subscription backend
        # rejects them; preserve their priority by moving them to instructions.
        request['instructions'] = '\n\n'.join([request.get('instructions', ''), *instructions])
        request['input'] = kept
    return request


ChatGPTResponsesAPIConfig.transform_responses_api_request = subscription_request

if __name__ == '__main__':
    from litellm.proxy.proxy_cli import run_server
    run_server()
