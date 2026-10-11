"""Reference-role, immutable-photo and durable multi-view regression checks."""
import base64
from io import BytesIO
from PIL import Image
from app.config import Environment
from app.models import Settings, TryOnRequest
from app.providers import GoogleProvider, IMAGE_ROLE_INSTRUCTION
from conftest import auth


def upload(client, image_bytes, purpose='person'):
    response = client.post('/api/uploads', headers=auth(),
                           files={'file': ('person.jpg', image_bytes, 'image/jpeg')},
                           data={'consent': 'true', 'purpose': purpose})
    assert response.status_code == 201, response.text
    return response.json()['id']


def add_views(services, identifier, colors):
    garment = services.store.get('garments', identifier)
    views = []
    keys = []
    for number, color in enumerate(colors):
        output = BytesIO()
        Image.new('RGB', (320, 480), color).save(output, 'JPEG')
        views.append(output.getvalue())
        keys.append(f'garments/{identifier}-view-{number}.jpg')
        services.objects.put('catalog', keys[-1], views[-1])
    services.store.set('garments', identifier, {**garment, 'image_keys': keys})
    return keys, views


def test_google_job_snapshots_and_uses_all_views_grouped_by_garment(client, services, image_bytes):
    shirt_keys, shirt_views = add_views(services, 'shirt', ['red', 'blue'])
    pants_keys, pants_views = add_views(services, 'pants', ['green', 'yellow', 'black'])
    source = upload(client, image_bytes)
    job = services.jobs.submit('user', TryOnRequest(upload_id=source, garment_ids=['pants', 'shirt'],
                                                  idempotency_key='multiview-google'), 'catalog')
    assert job['garment_reference_groups'] == [
        {'garment_id': 'shirt', 'image_keys': shirt_keys},
        {'garment_id': 'pants', 'image_keys': pants_keys},
    ]
    assert job['reference_count'] == 5
    assert job['expected_calls'] == 1 and job['estimated_cost_usd'] == 0.28
    assert any('references 1, 2 are all views of the same upper garment' in instruction for instruction in job['render_instructions'])
    assert any('references 3, 4, 5 are all views of the same lower garment' in instruction for instruction in job['render_instructions'])
    assert IMAGE_ROLE_INSTRUCTION in job['render_instructions']
    # Later edits cannot change an accepted job's references or garment grouping.
    shirt = services.store.get('garments', 'shirt')
    services.store.set('garments', 'shirt', {**shirt, 'image_keys': ['replacement.jpg'], 'name': 'Changed'})
    uploaded_person = services.objects.get('temp', job['source_key'])
    services.jobs.process(job['id'])
    submission = services.providers.provider.submissions[0]
    assert submission[0] == uploaded_person
    assert submission[1] == shirt_views + pants_views
    assert services.store.get('generation_jobs', job['id'])['status'] == 'succeeded'


def test_jobs_accepted_by_previous_release_still_use_legacy_photo_key(client, services, image_bytes):
    source = upload(client, image_bytes)
    job = services.jobs.submit('user', TryOnRequest(upload_id=source, garment_ids=['shirt'],
                                                  idempotency_key='legacy-image-job'), 'catalog')
    stored = services.store.get('generation_jobs', job['id'])
    stored.pop('garment_reference_groups')
    stored['garments'][0].pop('image_keys')
    services.store.set('generation_jobs', job['id'], stored)
    services.jobs.process(job['id'])
    assert services.providers.provider.submissions[0][1] == [image_bytes]
    assert services.store.get('generation_jobs', job['id'])['status'] == 'succeeded'


def test_fashn_contact_sheets_keep_garment_views_and_two_sequential_calls(client, services, image_bytes):
    settings = Settings()
    settings.ai.provider, settings.ai.model = 'fashn', 'tryon-max'
    services.store.set('application_settings', 'main', settings.model_dump())
    add_views(services, 'shirt', ['red', 'blue'])
    add_views(services, 'pants', ['green', 'yellow'])
    source = upload(client, image_bytes)
    job = services.jobs.submit('user', TryOnRequest(upload_id=source, garment_ids=['shirt', 'pants'],
                                                  idempotency_key='fashn-multiview'), 'catalog')
    assert job['expected_calls'] == 2
    received_instructions = []
    submit = services.providers.provider.submit
    def capture(person, garments, settings, workflow, instructions=None):
        received_instructions.append(instructions)
        return submit(person, garments, settings, workflow, instructions)
    services.providers.provider.submit = capture
    services.jobs.process(job['id'])
    current = services.store.get('generation_jobs', job['id'])
    assert current['step'] == 1 and current['status'] == 'processing'
    services.jobs.process(job['id'])
    assert services.store.get('generation_jobs', job['id'])['status'] == 'succeeded'
    assert len(services.providers.provider.submissions) == 2
    for index, expected in enumerate([('red', 'blue'), ('green', 'yellow')]):
        submission = services.providers.provider.submissions[index]
        assert len(submission[1]) == 1
        with Image.open(BytesIO(submission[1][0])) as sheet:
            assert sheet.size == (1536, 768)
            for view, color in enumerate(expected):
                actual = sheet.getpixel((view * 768 + 384, 384))
                target = Image.new('RGB', (1, 1), color).getpixel((0, 0))
                assert all(abs(left - right) <= 8 for left, right in zip(actual, target))
        assert any('multi-view sheet of ONE garment' in instruction for instruction in received_instructions[index])


def test_multiview_async_job_polls_prediction_without_resubmitting_views(client, services, image_bytes):
    _, views = add_views(services, 'shirt', ['red', 'blue', 'green'])
    services.providers.provider.async_mode = True
    services.providers.provider.pending_polls = 1
    source = upload(client, image_bytes)
    job = services.jobs.submit('user', TryOnRequest(upload_id=source, garment_ids=['shirt'],
                                                  idempotency_key='async-multiview'), 'catalog')
    services.jobs.process(job['id'])
    services.jobs.process(job['id'])
    services.jobs.process(job['id'])
    assert len(services.providers.provider.submissions) == 1
    assert services.providers.provider.submissions[0][1] == views
    assert services.providers.provider.polls == ['prediction-1', 'prediction-1']
    assert services.store.get('generation_jobs', job['id'])['status'] == 'succeeded'


def test_inconclusive_own_garment_preflight_continues_and_records_both_billed_calls(client, services, image_bytes, monkeypatch):
    provider = GoogleProvider(Environment())
    requests = []
    preflight_usage = {'promptTokenCount': 100, 'candidatesTokenCount': 10}
    def generate(model, body, timeout):
        requests.append((model, body))
        if model == 'gemini-3.8-flash':
            return {'candidates': [{'content': {'parts': [{'text': 'inconclusive structured response'}]}}],
                    'usageMetadata': preflight_usage}
        return {'candidates': [{'content': {'parts': [{'inlineData': {
            'mimeType': 'image/jpeg', 'data': base64.b64encode(image_bytes).decode()}}]}}],
            'usageMetadata': {'promptTokenCount': 50, 'candidatesTokenCount': 1120}}
    monkeypatch.setattr(provider, '_generate', generate)
    monkeypatch.setattr(services.providers, 'get', lambda identifier: provider)
    source = upload(client, image_bytes, 'holding')
    job = services.jobs.submit('user', TryOnRequest(upload_id=source, idempotency_key='tolerant-preflight-job'), 'holding')
    services.jobs.process(job['id'])
    after_preflight = services.store.get('generation_jobs', job['id'])
    assert after_preflight['preflight_done'] and after_preflight['attempts'] == 1
    assert '1' in after_preflight['call_costs']
    services.jobs.process(job['id'])
    finished = services.store.get('generation_jobs', job['id'])
    assert finished['status'] == 'succeeded' and finished['attempts'] == 2
    assert list(finished['call_costs']) == ['1', '2']
    assert [model for model, _ in requests] == ['gemini-3.8-flash', 'gemini-3-pro-image']
    results = services.store.list('usage_events', {'event': 'provider_result'})
    assert any(event['model'] == 'gemini-3.8-flash' and event['reported_usage'] == preflight_usage for event in results)
