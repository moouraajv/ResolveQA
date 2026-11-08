"""Explicit opt-in Featherless transport using only the standard library."""
from dataclasses import replace
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from resolveqa.llm import DeterministicMockLLM


class RealLLM:
    """Reuse the public adapter's validation and budget with a real transport."""
    use_real = True
    response_override = None

    def __init__(self, model):
        credential = os.environ.get('FEATHERLESS_API_KEY', '').strip()
        if not credential:
            raise ValueError('Modo real exige FEATHERLESS_API_KEY no ambiente')
        if not model:
            raise ValueError('Modo real exige --model ou FEATHERLESS_MODEL')
        self._credential = credential
        self._model = model
        self._adapter = DeterministicMockLLM(
            provider='featherless', model=model, response_override=self._request,
        )

    def bind_case(self, case):
        self._adapter.bind_case(case)

    def get_llm_calls(self, case=None):
        return self._adapter.get_llm_calls(case)

    def _request(self, purpose, messages, schema):
        instruction = ('Return only executable Python unittest source without markdown.'
                       if purpose == 'reproduction' else
                       'Return only a JSON object matching the requested fields.')
        payload = json.dumps({'model': self._model,
                              'messages': [*messages, {'role': 'system', 'content': instruction}],
                              'temperature': 0, 'max_tokens': 2000}).encode()
        request = Request('https://api.featherless.ai/v1/chat/completions', data=payload,
                          headers={'Authorization': 'Bearer ' + self._credential,
                                   'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=60) as response:
                data = json.load(response)
            return data['choices'][0]['message']['content']
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, IndexError):
            # Provider bodies and exception strings may contain credentials.
            raise OSError('Falha no provedor LLM real; resposta omitida por segurança') from None

    def complete(self, *args, **kwargs):
        result = self._adapter.complete(*args, **kwargs)
        return replace(result, mock=False)
