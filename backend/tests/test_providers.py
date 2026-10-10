import base64
import json
import httpx
import pytest
from app.config import Environment
from app.models import Settings
from app.providers import GoogleProvider, FashnProvider, PrunaProvider, ProviderError, json_request, render_instructions, SAREE_INSTRUCTION


class MockClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(result[0], json=result[1], headers=result[2] if len(result) > 2 else {}, request=httpx.Request(method, url))
    def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        return httpx.Response(200, content=b'imagebytes', request=httpx.Request('GET', url))


def test_google_preserves_multi_reference_request_and_reported_usage(monkeypatch, image_bytes):
    provider = GoogleProvider(Environment())
    captured = {}
    def generate(model, body, timeout):
        captured.update(model=model, body=body, timeout=timeout)
        return {'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(image_bytes).decode()}}]}}], 'usageMetadata': {'promptTokenCount': 99}}
    monkeypatch.setattr(provider, '_generate', generate)
    result = provider.submit(image_bytes, [image_bytes, image_bytes], Settings(), 'catalog')
    assert result.image == image_bytes
    assert result.usage == {'promptTokenCount': 99}
    body = captured['body']
    assert captured['model'] == 'gemini-3-pro-image'
    assert body['generationConfig']['imageConfig']['imageSize'] == '2K'
    assert len([p for p in body['contents'][0]['parts'] if 'inlineData' in p]) == 3
    assert body['generationConfig']['candidateCount'] == 1


def test_saree_request_replaces_full_outfit_without_changing_model_or_call_count(monkeypatch, image_bytes):
    provider = GoogleProvider(Environment())
    requests = []
    def generate(model, body, timeout):
        requests.append((model, body))
        return {'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(image_bytes).decode()}}]}}]}
    monkeypatch.setattr(provider, '_generate', generate)
    settings = Settings()
    provider.submit(image_bytes, [image_bytes], settings, 'catalog', render_instructions([{'category_id': 'sarees'}], 'catalog'))
    assert len(requests) == 1
    texts = [part.get('text', '') for part in requests[0][1]['contents'][0]['parts']]
    assert SAREE_INSTRUCTION in texts
    assert settings.ai.catalog_prompt in texts  # Administrator prompt remains intact.
    assert requests[0][0] == 'gemini-3-pro-image'
    assert requests[0][1]['generationConfig']['candidateCount'] == 1
    assert SAREE_INSTRUCTION not in render_instructions([{'category_id': 'dresses'}], 'catalog')
    assert SAREE_INSTRUCTION not in render_instructions([], 'holding')


def test_google_preflight_fail_closed_and_no_fake_output(monkeypatch, image_bytes):
    provider = GoogleProvider(Environment())
    monkeypatch.setattr(provider, '_generate', lambda *args: {'candidates': [{'content': {'parts': [{'text': '{"suitable":false,"reason":"Retake a clear photo."}'}]}}]})
    suitable, guidance, usage = provider.preflight(image_bytes, Settings())
    assert not suitable and guidance == 'Retake a clear photo.'
    with pytest.raises(ProviderError):
        provider.submit(image_bytes, [image_bytes], Settings(), 'catalog')
    monkeypatch.setattr(provider, '_generate', lambda *args: {'candidates': []})
    with pytest.raises(ProviderError):
        provider.preflight(image_bytes, Settings())


def test_fashn_documented_submit_poll_and_credits(monkeypatch, image_bytes):
    data_uri = 'data:image/jpeg;base64,' + base64.b64encode(image_bytes).decode()
    client = MockClient([(200, {'id': 'abc-123'}), (200, {'status': 'completed', 'output': [data_uri]}, {'x-fashn-credits-used': '3'})])
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client)
    settings = Settings()
    settings.ai.provider, settings.ai.model = 'fashn', 'tryon-max'
    provider = FashnProvider('secret-api-key')
    result = provider.submit(image_bytes, [image_bytes], settings, 'catalog')
    assert result.prediction_id == 'abc-123'
    payload = client.calls[0][2]['json']
    assert payload['model_name'] == 'tryon-max'
    assert payload['inputs']['return_base64']
    assert payload['inputs']['num_images'] == 1
    result = provider.poll('abc-123', settings)
    assert result.image == image_bytes and result.usage == {'credits': 3.0}
    assert client.calls[1][1] == 'https://api.fashn.ai/v1/status/abc-123'


def test_pruna_native_multi_image_upload_and_prediction_reconciliation(monkeypatch, image_bytes):
    client = MockClient([(200, {'urls': {'get': f'https://api.pruna.ai/v1/files/file-{i}'}}) for i in range(3)] + [(200, {'id': 'prediction'}), (200, {'status': 'succeeded', 'generation_url': 'https://api.pruna.ai/v1/predictions/delivery/key/result.jpg'})])
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client)
    provider = PrunaProvider('secret')
    result = provider.submit(image_bytes, [image_bytes, image_bytes], Settings(), 'catalog')
    assert result.prediction_id == 'prediction'
    assert len(client.calls[3][2]['json']['input']['garment_images']) == 2
    assert client.calls[3][2]['headers']['Model'] == 'p-image-try-on'
    assert provider.poll('prediction', Settings()).image == b'imagebytes'
    assert client.calls[4][1] == 'https://api.pruna.ai/v1/predictions/status/prediction'
    assert client.calls[5][2]['follow_redirects'] is False


def test_http_error_redaction_and_ambiguous_timeouts():
    client = MockClient([(500, {'error': 'echoed-private-photo-secret'})])
    with pytest.raises(ProviderError) as exc:
        json_request(client, 'POST', 'https://example.test')
    assert exc.value.ambiguous
    assert 'private' not in str(exc.value)
    client = MockClient([httpx.ReadTimeout('timeout')])
    with pytest.raises(ProviderError) as exc:
        json_request(client, 'POST', 'https://example.test')
    assert exc.value.ambiguous
    client = MockClient([httpx.ReadTimeout('timeout')])
    with pytest.raises(ProviderError) as exc:
        json_request(client, 'GET', 'https://example.test')
    assert not exc.value.ambiguous


def test_pruna_rejects_external_delivery_and_prevents_key_exposure(monkeypatch):
    client = MockClient([(200, {'status': 'succeeded', 'generation_url': 'https://evil.example/private'})])
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client)
    with pytest.raises(ProviderError):
        PrunaProvider('private-api-key').poll('prediction', Settings())
    assert len(client.calls) == 1
