import base64
from io import BytesIO
import json
import random
import httpx
import pytest
from PIL import Image
from app.config import Environment
from app.models import Settings
from app.providers import GoogleProvider, FashnProvider, PrunaProvider, ProviderError, json_request, render_instructions, SAREE_INSTRUCTION, IMAGE_ROLE_INSTRUCTION, HOLDING_INSTRUCTION, estimate, bounded_inline_images, MAX_INLINE_INPUT_BYTES


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
    texts = [p.get('text', '') for p in body['contents'][0]['parts']]
    assert IMAGE_ROLE_INSTRUCTION in texts
    assert IMAGE_ROLE_INSTRUCTION in [p['text'] for p in body['systemInstruction']['parts']]
    image_labels = [texts[i - 1] for i, p in enumerate(body['contents'][0]['parts']) if 'inlineData' in p]
    assert image_labels[0].startswith('END USER PERSON PHOTO')
    assert all(label.startswith('GARMENT REFERENCE') and 'ignore any model identity' in label for label in image_labels[1:])


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


@pytest.mark.parametrize('code, expected', [('no_person', 'No person'), ('no_garment', 'No garment')])
def test_google_preflight_rejects_only_unprocessable_missing_input(monkeypatch, image_bytes, code, expected):
    provider = GoogleProvider(Environment())
    monkeypatch.setattr(provider, '_generate', lambda *args: {'candidates': [{'content': {'parts': [{'text': json.dumps({'processable': False, 'failure_code': code, 'reason': 'internal reason'})}]}}], 'usageMetadata': {'promptTokenCount': 37}})
    suitable, guidance, usage = provider.preflight(image_bytes, Settings())
    assert not suitable and guidance.startswith(expected)
    assert usage == {'promptTokenCount': 37}


@pytest.mark.parametrize('text', [
    '{"processable":true,"failure_code":"none","reason":"A child holding a folded dress"}',
    '{"processable":false,"failure_code":"poor_quality","reason":"Photo is dark"}',
    '{"suitable":false,"reason":"A teenager should retake a clearer photo"}',
    'not-json', 'null', '[]',
])
def test_google_preflight_accepts_age_imperfect_photos_and_inconclusive_output(monkeypatch, image_bytes, text):
    provider = GoogleProvider(Environment())
    captured = {}
    def generate(model, body, timeout):
        captured.update(model=model, body=body)
        return {'candidates': [{'content': {'parts': [{'text': text}]}}], 'usageMetadata': {'promptTokenCount': 37}}
    monkeypatch.setattr(provider, '_generate', generate)
    suitable, guidance, usage = provider.preflight(image_bytes, Settings())
    assert suitable and guidance == ''
    assert usage == {'promptTokenCount': 37}
    prompt = captured['body']['contents'][0]['parts'][0]['text']
    assert 'Children, adolescents and adults are all eligible' in prompt
    assert 'never reject because of age' in prompt
    assert 'folded, partially visible or already worn' in prompt
    assert captured['model'] == 'gemini-3.8-flash'


def test_google_preflight_empty_result_keeps_usage_and_image_failure_does_not_demand_recapture(monkeypatch, image_bytes):
    provider = GoogleProvider(Environment())
    monkeypatch.setattr(provider, '_generate', lambda *args: {'candidates': [], 'usageMetadata': {'promptTokenCount': 37}})
    assert provider.preflight(image_bytes, Settings()) == (True, '', {'promptTokenCount': 37})
    with pytest.raises(ProviderError):
        provider.submit(image_bytes, [image_bytes], Settings(), 'catalog')


def test_mandatory_own_garment_roles_apply_to_legacy_saved_instructions(monkeypatch, image_bytes):
    provider = GoogleProvider(Environment())
    captured = {}
    def generate(model, body, timeout):
        captured.update(body=body)
        return {'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(image_bytes).decode()}}]}}]}
    monkeypatch.setattr(provider, '_generate', generate)
    provider.submit(image_bytes, [], Settings(), 'holding', ['Existing custom instructions'])
    texts = [part.get('text', '') for part in captured['body']['contents'][0]['parts']]
    assert IMAGE_ROLE_INSTRUCTION in texts
    assert HOLDING_INSTRUCTION in texts
    assert 'Existing custom instructions' in texts


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
    assert IMAGE_ROLE_INSTRUCTION in payload['inputs']['prompt']
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
    assert IMAGE_ROLE_INSTRUCTION in client.calls[3][2]['json']['input']['prompt']
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


def test_multiple_reference_views_reserve_input_cost_without_extra_google_calls():
    settings = Settings()
    assert estimate(settings, 1, reference_count=6) == (1, 0.30)
    assert estimate(settings, 2, reference_count=12) == (1, 0.35)
    settings.ai.provider = 'fashn'
    assert estimate(settings, 2, reference_count=12) == estimate(settings, 2)


def test_small_inline_inputs_are_preserved_byte_for_byte(image_bytes):
    inputs = [image_bytes, image_bytes]
    assert bounded_inline_images(inputs) is inputs


def test_oversized_google_multiview_payload_keeps_all_images_roles_order_and_framing(monkeypatch, image_bytes):
    provider = GoogleProvider(Environment())
    width, height = 1024, 1536
    generator = random.Random(2718)
    noise = Image.frombytes('RGB', (width, height), generator.randbytes(width * height * 3))
    inputs = []
    colors = []
    for number in range(13):  # One end user and all twelve views of two garments.
        color = (15 + number * 16, 230 - number * 15, 30 + number * 12)
        colors.append(color)
        photo = noise.copy()
        photo.paste(color, (0, 0, 96, 96))
        photo.paste(color, (width - 96, height - 96, width, height))
        output = BytesIO()
        photo.save(output, 'JPEG', quality=100)
        inputs.append(output.getvalue())
        photo.close()
    noise.close()
    assert sum(len(data) for data in inputs) > MAX_INLINE_INPUT_BYTES
    assert max(len(data) for data in inputs) < 7 * 1024 * 1024
    captured = {}
    def generate(model, body, timeout):
        captured.update(body=body)
        return {'candidates': [{'content': {'parts': [{'inlineData': {
            'mimeType': 'image/jpeg', 'data': base64.b64encode(image_bytes).decode()}}]}}]}
    monkeypatch.setattr(provider, '_generate', generate)
    instructions = render_instructions([
        {'image_keys': [str(i) for i in range(6)], 'slot': 'upper'},
        {'image_keys': [str(i) for i in range(6)], 'slot': 'lower'},
    ], 'catalog')
    provider.submit(inputs[0], inputs[1:], Settings(), 'catalog', instructions)
    parts = captured['body']['contents'][0]['parts']
    images = [base64.b64decode(part['inlineData']['data']) for part in parts if 'inlineData' in part]
    assert len(images) == 13
    assert sum(len(data) for data in images) <= MAX_INLINE_INPUT_BYTES
    # Allow prompt/JSON overhead above the sixteen MiB base64 image budget.
    assert len(json.dumps(captured['body']).encode()) < 17 * 1024 * 1024
    labels = [parts[index - 1]['text'] for index, part in enumerate(parts) if 'inlineData' in part]
    assert labels[0].startswith('END USER PERSON PHOTO')
    assert [label.split(' —')[0] for label in labels[1:]] == [f'GARMENT REFERENCE {i}' for i in range(1, 13)]
    for data, color in zip(images, colors):
        with Image.open(BytesIO(data)) as photo:
            assert abs(photo.width / photo.height - width / height) < 0.002
            for position in [(8, 8), (photo.width - 8, photo.height - 8)]:
                assert all(abs(channel - expected) < 10 for channel, expected in zip(photo.getpixel(position), color))
    assert any('references 1, 2, 3, 4, 5, 6 are all views' in part.get('text', '') for part in parts)
    assert any('references 7, 8, 9, 10, 11, 12 are all views' in part.get('text', '') for part in parts)


def test_unrepresentably_small_inline_budget_fails_before_generation(image_bytes):
    with pytest.raises(ProviderError, match='processing size limit'):
        bounded_inline_images([image_bytes], max_bytes=1)
