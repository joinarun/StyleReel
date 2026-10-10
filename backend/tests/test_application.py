from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import base64
from PIL import Image
import pytest
from fastapi import HTTPException
from app.images import normalize_image, InvalidImage
from app.models import Settings, TryOnRequest
from app.infrastructure import now
from app.providers import estimate
from conftest import auth


def photo(client, image_bytes, uid='user', purpose='person'):
    response = client.post('/api/uploads', headers=auth(uid), files={'file': ('test.jpg', image_bytes, 'image/jpeg')}, data={'consent': 'true', 'purpose': purpose})
    assert response.status_code == 201, response.text
    return response.json()['id']


def request(upload_id, garments=None, idem='unique-request-1'):
    return TryOnRequest(upload_id=upload_id, garment_ids=garments or ['shirt'], idempotency_key=idem)


def test_saree_drape_instructions_are_snapshotted_before_catalog_changes(client, services, image_bytes):
    from app.providers import SAREE_INSTRUCTION
    services.objects.put('catalog', 'garments/saree.jpg', image_bytes)
    services.store.set('garments', 'saree', {'name': 'Saree', 'category_id': 'sarees', 'active': True, 'image_key': 'garments/saree.jpg'})
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source, ['saree']), 'catalog')
    assert job['experimental'] and job['expected_calls'] == 1
    assert SAREE_INSTRUCTION in job['render_instructions']
    services.store.set('garments', 'saree', {'name': 'Renamed', 'category_id': 'dresses', 'active': True, 'image_key': 'garments/saree.jpg'})
    stored = services.store.get('generation_jobs', job['id'])
    assert stored['garments'][0]['category_id'] == 'sarees'
    assert SAREE_INSTRUCTION in stored['render_instructions']
    received = []
    submit = services.providers.provider.submit

    def capture_instructions(person, garments, settings, workflow, instructions=None):
        received.append(instructions)
        return submit(person, garments, settings, workflow, instructions)

    services.providers.provider.submit = capture_instructions
    services.jobs.process(job['id'])
    assert services.store.get('generation_jobs', job['id'])['status'] == 'succeeded'
    assert received == [stored['render_instructions']]


def test_public_job_keeps_submitted_provider_metadata_after_settings_change(client, services, image_bytes):
    source = photo(client, image_bytes)
    response = client.post('/api/tryon/catalog', headers=auth(), json={
        'upload_id': source, 'garment_ids': ['shirt'], 'idempotency_key': 'immutable-provider-snapshot',
    })
    assert response.status_code == 202
    original = response.json()
    assert original['provider'] == 'google' and original['model'] == 'gemini-3-pro-image'
    changed = Settings()
    changed.ai.provider, changed.ai.model = 'fashn', 'tryon-max'
    services.store.set('application_settings', 'main', changed.model_dump())
    status = client.get('/api/tryon/jobs/' + original['id'], headers=auth()).json()
    assert (status['provider'], status['provider_label'], status['model']) == (
        original['provider'], original['provider_label'], original['model'])
    assert 'settings' not in status and 'render_instructions' not in status


def test_authentication_and_role_gates(client, services):
    assert client.get('/api/me').status_code == 401
    assert client.get('/api/me', headers=auth('invalid')).status_code == 401
    assert client.get('/api/users', headers=auth()).status_code == 403
    services.store.set('users', 'user', {'active': False, 'role': 'admin'})
    assert client.get('/api/settings', headers=auth()).status_code == 403
    services.store.set('users', 'user', {'active': True, 'role': 'admin', 'must_change_password': True})
    assert client.get('/api/me', headers=auth()).status_code == 200
    assert client.get('/api/admin/settings', headers=auth()).status_code == 403
    assert client.post('/api/me/password', headers=auth(), json={'password': 'NewPassword123!'}).status_code == 200
    assert not services.store.get('users', 'user')['must_change_password']
    assert services.identity.revoked == ['user']


def test_gallery_key_stable_private_and_random(client):
    key = client.get('/api/me/gallery-key', headers=auth()).json()['key']
    assert len(base64.b64decode(key)) == 32
    assert client.get('/api/me/gallery-key', headers=auth()).json()['key'] == key
    assert client.get('/api/me/gallery-key', headers=auth('other')).json()['key'] != key
    assert 'gallery_key' not in client.get('/api/me', headers=auth()).json()


def test_admin_user_lifecycle_and_secret_write_only(client, services):
    response = client.post('/api/users', headers=auth('admin'), json={'email': 'new@test.com', 'password': 'StrongPassword123!', 'role': 'user'})
    assert response.status_code == 201
    uid = response.json()['id']
    assert response.json()['must_change_password']
    assert client.patch('/api/users/' + uid, headers=auth('admin'), json={'active': False}).status_code == 200
    assert client.get('/api/me', headers=auth(uid)).status_code == 403
    assert client.post('/api/users/' + uid + '/reset', headers=auth('admin')).json()['reset_link']
    assert client.delete('/api/users/' + uid, headers=auth('admin')).status_code == 200
    assert uid in services.identity.deleted
    assert client.delete('/api/users/admin', headers=auth('admin')).status_code == 400
    assert client.put('/api/admin/providers/fashn/credential', headers=auth('admin'), json={'api_key': 'private-key-value'}).status_code == 200
    assert 'private-key-value' not in client.get('/api/admin/settings', headers=auth('admin')).text


def test_images_validate_contents_strip_metadata_and_orientation(image_bytes):
    normalized = normalize_image(image_bytes)
    assert (normalized.width, normalized.height) == (320, 480)
    assert not Image.open(BytesIO(normalized.data)).getexif()
    for invalid in [b'<script>alert(1)</script>', b'notanimage', image_bytes[:50]]:
        with pytest.raises(InvalidImage):
            normalize_image(invalid)
    with pytest.raises(InvalidImage):
        normalize_image(image_bytes, max_bytes=10)
    image = Image.new('RGB', (160, 240))
    exif = Image.Exif()
    exif[274] = 6
    buf = BytesIO()
    image.save(buf, 'JPEG', exif=exif)
    rotated = normalize_image(buf.getvalue())
    assert (rotated.width, rotated.height) == (240, 160)


def test_upload_privacy_consent_and_delete(client, image_bytes):
    assert client.post('/api/uploads', headers=auth(), files={'file': ('a.jpg', image_bytes)}, data={'purpose': 'person', 'consent': 'false'}).status_code == 400
    upload = photo(client, image_bytes)
    assert client.get(f'/api/uploads/{upload}/image', headers=auth('other')).status_code == 404
    assert client.get(f'/api/uploads/{upload}/image', headers=auth()).status_code == 200
    assert client.delete(f'/api/uploads/{upload}', headers=auth()).status_code == 200
    assert client.get(f'/api/uploads/{upload}/image', headers=auth()).status_code == 410


def test_catalog_admin_crud_and_hidden_private_keys(client, image_bytes):
    category = client.post('/api/categories', headers=auth('admin'), json={'name': 'Jackets', 'slot': 'upper'}).json()
    assert category['id'] == 'jackets'
    response = client.post('/api/garments', headers=auth('admin'), files={'file': ('item.jpg', image_bytes)}, data={'name': 'Jacket', 'category_id': 'jackets', 'license': 'CC0'})
    assert response.status_code == 201
    g = response.json()
    assert 'image_key' not in g
    assert client.patch('/api/garments/' + g['id'], headers=auth('admin'), json={'active': False}).status_code == 200
    assert client.get(g['image_url'], headers=auth()).status_code == 404
    assert client.get(g['image_url'], headers=auth('admin')).status_code == 200
    assert client.delete('/api/garments/' + g['id'], headers=auth('admin')).status_code == 200


def test_successful_job_and_duplicate_task_no_duplicate_ai(client, services, image_bytes):
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source), 'catalog')
    assert job['status'] == 'queued'
    assert services.jobs.submit('user', request(source), 'catalog')['id'] == job['id']
    assert len(services.tasks.calls) == 1
    services.jobs.process(job['id'])
    services.jobs.process(job['id'])
    assert len(services.providers.provider.submissions) == 1
    response = client.get('/api/tryon/jobs/' + job['id'], headers=auth()).json()
    assert response['status'] == 'succeeded'
    assert client.get(response['result_url'], headers=auth()).status_code == 200
    assert client.get(response['result_url'], headers=auth('other')).status_code == 404
    assert ('temp', job['source_key']) not in services.objects.values
    budget = services.store.get('budget_months', job['budget_month'])
    assert budget['reserved'] == 0 and budget['spent'] == job['estimated_cost_usd']


def test_idempotency_conflict_and_bad_combinations(client, services, image_bytes):
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source), 'catalog')
    with pytest.raises(HTTPException) as exc:
        services.jobs.submit('user', request(source, ['pants']), 'catalog')
    assert exc.value.status_code == 409
    source2 = photo(client, image_bytes, 'other')
    for garment_ids in [['shirt', 'dress'], ['shirt', 'shirt'], ['shirt', 'missing']]:
        with pytest.raises(HTTPException) as exc:
            services.jobs.submit('other', request(source2, garment_ids, 'another-unique'), 'catalog')
        assert exc.value.status_code == 400


def test_atomic_concurrent_submission_and_budget_ceiling(client, services, image_bytes):
    sources = [photo(client, image_bytes) for _ in range(6)]
    def submit(index):
        try:
            return services.jobs.submit('user', request(sources[index], idem=f'simultaneous-{index}'), 'catalog')
        except HTTPException as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(submit, range(6)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert results.count(429) == 5
    assert len(services.store.list('generation_jobs')) == 1
    settings = Settings()
    settings.rate_limits.monthly_budget_usd = 0.1
    services.store.set('application_settings', 'main', settings.model_dump())
    source = photo(client, image_bytes, 'other')
    with pytest.raises(HTTPException) as exc:
        services.jobs.submit('other', request(source), 'catalog')
    assert exc.value.status_code == 429


def test_async_fashn_pipeline_resumes_known_prediction(client, services, image_bytes):
    settings = Settings()
    settings.ai.provider, settings.ai.model = 'fashn', 'tryon-max'
    services.store.set('application_settings', 'main', settings.model_dump())
    services.providers.provider.async_mode = True
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source, ['shirt', 'pants']), 'catalog')
    assert job['expected_calls'] == 2
    services.jobs.process(job['id'])  # submit first
    services.jobs.process(job['id'])  # poll first; store intermediate
    services.jobs.process(job['id'])  # submit second with intermediate
    services.jobs.process(job['id'])  # poll second
    assert len(services.providers.provider.submissions) == 2
    assert services.providers.provider.polls == ['prediction-1', 'prediction-2']
    assert services.store.get('generation_jobs', job['id'])['status'] == 'succeeded'
    calls = [e for e in services.store.list('usage_events') if e['event'] == 'provider_call']
    assert len(calls) == 2


def test_ambiguous_provider_no_paid_retry_and_reservation_charged(client, services, image_bytes):
    services.providers.provider.ambiguous = True
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source), 'catalog')
    services.jobs.process(job['id'])
    services.jobs.process(job['id'])
    assert len(services.providers.provider.submissions) == 1
    assert services.store.get('generation_jobs', job['id'])['status'] == 'unknown'
    assert services.store.get('budget_months', job['budget_month'])['spent'] == job['estimated_cost_usd']


def test_enqueue_failure_and_stale_submission_recovery(client, services, image_bytes):
    services.tasks.fail = True
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source), 'catalog')
    assert services.store.get('generation_jobs', job['id'])['enqueue_state'] == 'pending'
    services.tasks.fail = False
    assert services.jobs.maintenance()['jobs_recovered'] == 1
    services.jobs._update(job['id'], stage='submitting', attempts=1, lease_until=now() - timedelta(seconds=1))
    services.jobs.maintenance()
    assert services.store.get('generation_jobs', job['id'])['status'] == 'unknown'
    assert not services.providers.provider.submissions


def test_holding_preflight_rejects_before_generation_and_usage(client, services, image_bytes):
    services.providers.provider.suitable = False
    source = photo(client, image_bytes, purpose='holding')
    body = TryOnRequest(upload_id=source, idempotency_key='holding-reject-1')
    job = services.jobs.submit('user', body, 'holding')
    services.jobs.process(job['id'])
    assert services.store.get('generation_jobs', job['id'])['status'] == 'failed'
    assert not services.providers.provider.submissions
    assert len(services.providers.provider.preflights) == 1
    assert services.store.get('budget_months', job['budget_month'])['reserved'] == 0


def test_sharing_expiry_revoke_and_delete_cascade(client, services, image_bytes):
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source), 'catalog')
    services.jobs.process(job['id'])
    share = client.post('/api/shares', headers=auth(), json={'result_id': job['id']}).json()
    token = share['url'].split('#')[1]
    assert token not in repr(services.store.list('shares'))
    assert client.post('/api/shares/download', json={'token': token}).status_code == 200
    assert client.delete('/api/shares/' + share['id'], headers=auth('other')).status_code == 404
    assert client.delete('/api/shares/' + share['id'], headers=auth()).status_code == 200
    assert client.post('/api/shares/download', json={'token': token}).status_code == 410
    share2 = client.post('/api/shares', headers=auth(), json={'result_id': job['id']}).json()
    assert client.delete('/api/tryon/results/' + job['id'], headers=auth()).status_code == 200
    assert client.post('/api/shares/download', json={'token': share2['url'].split('#')[1]}).status_code == 410
    assert client.get('/api/tryon/results/' + job['id'], headers=auth()).status_code == 410


def test_share_expiry_and_private_data_cleanup(client, services, image_bytes):
    upload = photo(client, image_bytes, purpose='share')
    share = client.post('/api/shares', headers=auth(), json={'upload_id': upload}).json()
    stored = services.store.get('shares', share['id'])
    stored['expires_at'] = now() - timedelta(seconds=1)
    services.store.set('shares', share['id'], stored)
    assert client.post('/api/shares/download', json={'token': share['url'].split('#')[1]}).status_code == 410
    services.jobs.maintenance()
    assert not services.store.get('shares', share['id'])
    assert ('temp', stored['key']) not in services.objects.values


def test_settings_validation_and_provider_capabilities(client, services):
    current = client.get('/api/admin/settings', headers=auth('admin')).json()
    update = {k: current[k] for k in ['ai', 'gallery', 'rate_limits']}
    update['gallery']['max_images'] = 12
    assert client.put('/api/admin/settings', headers=auth('admin'), json=update).status_code == 200
    assert services.jobs.settings().gallery.max_images == 12
    update['ai']['model'] = 'unsupported-model'
    assert client.put('/api/admin/settings', headers=auth('admin'), json=update).status_code == 400
    assert client.post('/api/admin/providers/google/test', headers=auth('admin')).status_code == 200
    assert not services.providers.provider.submissions
    assert estimate(Settings(), 2) == (1, 0.25)
    settings = Settings()
    settings.ai.provider, settings.ai.model = 'fashn', 'tryon-max'
    assert estimate(settings, 2) == (2, 0.45)


def test_internal_task_requires_real_oidc_and_security_headers(client):
    assert client.post('/internal/tasks', json={'job_id': 'a' * 32}).status_code == 401
    assert client.post('/internal/maintenance', headers=auth()).status_code == 401
    response = client.get('/healthz')
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']


def test_analytics_records_actual_calls_without_customer_images(client, services, image_bytes):
    upload = photo(client, image_bytes)
    job = services.jobs.submit('user', request(upload), 'catalog')
    services.jobs.process(job['id'])
    metrics = client.get('/api/admin/analytics', headers=auth('admin')).json()
    assert metrics['totals']['uploads'] == 1
    assert metrics['totals']['generations'] == 1
    assert metrics['totals']['succeeded'] == 1
    assert metrics['by_provider'] == [{'name': 'google', 'calls': 1}]
    history = client.get('/api/admin/usage?limit=2', headers=auth('admin')).json()
    assert len(history['items']) == 2 and history['next_cursor']
    assert 'image_key' not in repr(history)
    assert 'promptTokenCount' in client.get('/api/admin/usage', headers=auth('admin')).text


def test_transparency_normalizes_on_white_and_input_limit():
    buf = BytesIO()
    Image.new('RGBA', (320, 320), (0, 0, 0, 0)).save(buf, 'PNG')
    image = Image.open(BytesIO(normalize_image(buf.getvalue()).data))
    assert image.getpixel((20, 20)) == (255, 255, 255)
    assert len(normalize_image(buf.getvalue()).data) < 7 * 1024 * 1024


def test_holding_stage_cost_fallback_is_preflight_only(client, services, image_bytes):
    services.providers.provider.suitable = False
    source = photo(client, image_bytes, purpose='holding')
    job = services.jobs.submit('user', TryOnRequest(upload_id=source, idempotency_key='stagecost-holding'), 'holding')
    services.jobs.process(job['id'])
    budget = services.store.get('budget_months', job['budget_month'])
    assert budget['spent'] == 0.02 and budget['reserved'] == 0


def test_reported_token_costs_reconcile_without_invented_tokens():
    from app.providers import reported_cost_usd
    usage = {'promptTokenCount': 1200, 'candidatesTokenCount': 1140, 'thoughtsTokenCount': 100, 'candidatesTokensDetails': [{'modality': 'IMAGE', 'tokenCount': 1120}, {'modality': 'TEXT', 'tokenCount': 20}]}
    assert reported_cost_usd(Settings(), usage) == 0.13824
    assert reported_cost_usd(Settings(), {'promptTokenCount': 42}) is None
    assert reported_cost_usd(Settings(), {'promptTokenCount': 1000, 'candidatesTokenCount': 100}, 'gemini-3.8-flash') == 0.000562


def test_worker_does_not_persist_result_if_user_deactivated_during_call(client, services, image_bytes):
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source), 'catalog')
    original_submit = services.providers.provider.submit
    def deactivate(*args):
        profile = services.store.get('users', 'user')
        services.store.set('users', 'user', {**profile, 'active': False})
        return original_submit(*args)
    services.providers.provider.submit = deactivate
    services.jobs.process(job['id'])
    assert services.store.get('generation_jobs', job['id'])['status'] == 'failed'
    assert not [k for kind, k in services.objects.values if kind == 'temp' and k.startswith('results/')]


def test_actual_call_rate_and_lease_renewal(client, services, image_bytes):
    source = photo(client, image_bytes)
    job = services.jobs.submit('user', request(source), 'catalog')
    quota = services.store.get('quota_users', 'user')
    services.store.set('quota_users', 'user', {**quota, 'actual_call_times': [now(), now()]})
    services.jobs.process(job['id'])
    assert not services.providers.provider.submissions
    assert services.tasks.calls[-1][1] == 60
    assert services.store.get('generation_jobs', job['id'])['stage'] == 'ready'


def test_upload_metadata_and_daily_limits(client, services, image_bytes):
    source = photo(client, image_bytes)
    upload_event = next(e for e in services.store.list('usage_events') if e['event'] == 'upload')
    assert upload_event['original_size_bytes'] == len(image_bytes)
    assert upload_event['filename'] == 'test.jpg'
    settings = Settings()
    settings.rate_limits.daily_global_calls = 1
    services.store.set('application_settings', 'main', settings.model_dump())
    services.jobs.submit('user', request(source), 'catalog')
    other = photo(client, image_bytes, 'other')
    with pytest.raises(HTTPException) as exc:
        services.jobs.submit('other', request(other), 'catalog')
    assert exc.value.status_code == 429


def test_holding_success_uses_two_durable_deliveries(client, services, image_bytes):
    source = photo(client, image_bytes, purpose='holding')
    job = services.jobs.submit('user', TryOnRequest(upload_id=source, idempotency_key='holding-success'), 'holding')
    services.jobs.process(job['id'])
    assert len(services.providers.provider.preflights) == 1
    assert not services.providers.provider.submissions
    assert services.store.get('generation_jobs', job['id'])['preflight_done']
    assert services.store.get('generation_jobs', job['id'])['stage'] == 'ready'
    services.jobs.process(job['id'])
    assert len(services.providers.provider.submissions) == 1
    assert services.store.get('generation_jobs', job['id'])['status'] == 'succeeded'
    assert services.store.get('generation_jobs', job['id'])['attempts'] == 2


def test_catalog_creation_visibility_and_editable_attribution(client, image_bytes):
    response = client.post('/api/garments', headers=auth('admin'), files={'file': ('item.jpg', image_bytes)}, data={'name': 'Private Shirt', 'category_id': 'shirts', 'active': 'false'})
    assert response.status_code == 201
    garment = response.json()
    assert garment['active'] is False
    assert garment['id'] not in [g['id'] for g in client.get('/api/garments', headers=auth()).json()]
    patch = {'license': 'CC BY 4.0', 'source_url': 'https://example.test/garment', 'attribution': 'Example designer'}
    response = client.patch('/api/garments/' + garment['id'], headers=auth('admin'), json=patch)
    assert response.status_code == 200
    assert {key: response.json()[key] for key in patch} == patch
    assert client.patch('/api/garments/' + garment['id'], headers=auth('admin'), json={'source_url': 'javascript:alert(1)'}).status_code == 422


def test_maintenance_stops_revisiting_cleaned_objects(client, services, image_bytes):
    upload = photo(client, image_bytes)
    job = services.jobs.submit('user', request(upload), 'catalog')
    services.jobs.process(job['id'])
    assert services.store.get('uploads', upload)['cleanup_pending'] is False
    services.jobs._update(job['id'], result_expires_at=now() - timedelta(seconds=1))
    first = services.jobs.maintenance()
    assert first['objects_deleted'] == 1
    assert services.store.get('generation_jobs', job['id'])['result_cleanup_pending'] is False
    assert services.jobs.maintenance()['objects_deleted'] == 0


def test_expired_upload_cleanup_remains_retryable_on_storage_failure(client, services, image_bytes):
    upload = photo(client, image_bytes)
    item = services.store.get('uploads', upload)
    services.store.set('uploads', upload, {**item, 'expires_at': now() - timedelta(seconds=1)})
    original = services.objects.delete
    services.objects.delete = lambda *args: (_ for _ in ()).throw(RuntimeError('temporary storage outage'))
    with pytest.raises(RuntimeError):
        services.jobs.maintenance()
    assert services.store.get('uploads', upload)['cleanup_pending'] is True
    services.objects.delete = original
    assert services.jobs.maintenance()['objects_deleted'] == 1
    assert services.store.get('uploads', upload)['cleanup_pending'] is False
