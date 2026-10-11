from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from PIL import Image

from conftest import auth


def test_type_labels_support_names_outside_ascii(client):
    response = client.post('/api/admin/categories', headers=auth('admin'), json={'name': 'பட்டு பாவாடை', 'slot': 'full'})
    assert response.status_code == 201
    assert response.json()['name'] == 'பட்டு பாவாடை'
    assert response.json()['id'].startswith('type-')


def test_combined_photo_upload_limit_leaves_no_partial_storage(client, services, image_bytes, monkeypatch):
    import app.main as application
    monkeypatch.setattr(application, 'MAX_CATALOG_UPLOAD_BYTES', len(image_bytes) * 2 - 1)
    before_objects = dict(services.objects.values)
    before_garments = services.store.list('garments')
    response = client.post('/api/admin/garments', headers=auth('admin'),
                           data={'name': 'Too large together', 'category_id': 'dresses'},
                           files=[('files', ('one.jpg', image_bytes)), ('files', ('two.jpg', image_bytes))])
    assert response.status_code == 413
    assert services.store.list('garments') == before_garments
    assert services.objects.values == before_objects


def label(client, kind, name):
    response = client.post('/api/admin/catalog/labels', headers=auth('admin'), json={'kind': kind, 'name': name})
    assert response.status_code == 201, response.text
    return response.json()


def test_catalog_labels_are_persistent_authenticated_and_admin_only(client, services):
    assert client.get('/api/catalog/labels').status_code == 401
    assert client.post('/api/admin/catalog/labels', headers=auth(), json={'kind': 'store', 'name': 'Store'}).status_code == 403
    store = label(client, 'store', '  Town   Boutique  ')
    brand = label(client, 'brand', 'Silk House')
    assert store['name'] == 'Town Boutique'
    assert services.store.get('catalog_stores', store['id'])['name'] == store['name']
    assert client.get('/api/catalog/labels', headers=auth()).json() == {'stores': [store], 'brands': [brand]}
    for payload in [{'kind': 'type', 'name': 'Blouse'}, {'kind': 'store', 'name': '   '}, {'kind': 'brand', 'name': 'x' * 101}]:
        assert client.post('/api/admin/catalog/labels', headers=auth('admin'), json=payload).status_code == 422


def test_catalog_labels_reuse_normalized_names_under_concurrent_creation(client, services):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda name: label(client, 'brand', name), ['ＡＣＭＥ', 'acme', 'Acme', '  Acme  ']))
    assert len({result['id'] for result in results}) == 1
    assert len(services.store.list('catalog_brands')) == 1
    # The same display name may be used independently as a store label.
    assert label(client, 'store', 'Acme')['id'] != results[0]['id']


def test_multiple_garment_photos_persist_and_delete_all_references(client, services, image_bytes):
    store, brand = label(client, 'store', 'Chennai Store'), label(client, 'brand', 'Saree Brand')
    second = BytesIO()
    Image.new('RGB', (400, 300), (5, 180, 190)).save(second, 'PNG')
    response = client.post('/api/admin/garments', headers=auth('admin'), data={
        'name': 'Blue Saree', 'category_id': 'sarees', 'store_id': store['id'], 'brand_id': brand['id'],
    }, files=[('files', ('front.jpg', image_bytes, 'image/jpeg')), ('files', ('back.png', second.getvalue(), 'image/png'))])
    assert response.status_code == 201, response.text
    garment = response.json()
    assert garment['store_id'] == store['id'] and garment['brand_id'] == brand['id']
    assert len(garment['image_urls']) == 2
    assert not {'image_key', 'image_keys', 'thumbnail_key'} & garment.keys()
    record = services.store.get('garments', garment['id'])
    assert len(record['image_keys']) == 2 and record['image_keys'][0] == record['image_key']
    primary = client.get(garment['image_url'], headers=auth())
    first = client.get(garment['image_urls'][0], headers=auth())
    second = client.get(garment['image_urls'][1], headers=auth())
    assert primary.content == first.content
    assert second.status_code == 200 and second.content != first.content
    assert Image.open(BytesIO(second.content)).format == 'JPEG'
    assert Image.open(BytesIO(second.content)).size == (400, 300)
    assert client.get(garment['image_urls'][1]).status_code == 401
    for index in [-1, 2]:
        assert client.get(f'/api/garments/{garment["id"]}/photos/{index}', headers=auth()).status_code == 404
    assert client.patch('/api/garments/' + garment['id'], headers=auth('admin'), json={'active': False}).status_code == 200
    assert client.get(garment['image_urls'][1], headers=auth()).status_code == 404
    assert client.get(garment['image_urls'][1], headers=auth('admin')).status_code == 200
    assert client.delete('/api/garments/' + garment['id'], headers=auth('admin')).status_code == 200
    assert services.store.get('garments', garment['id']) is None
    assert all(('catalog', key) not in services.objects.values for key in record['image_keys'] + [record['thumbnail_key']])


def test_legacy_garment_photo_and_create_remain_compatible(client, services, image_bytes):
    legacy = next(g for g in client.get('/api/garments', headers=auth()).json() if g['id'] == 'shirt')
    assert legacy['store_id'] is None and legacy['brand_id'] is None
    assert legacy['image_urls'] == ['/api/garments/shirt/photos/0']
    assert client.get(legacy['image_urls'][0], headers=auth()).content == image_bytes
    response = client.post('/api/garments', headers=auth('admin'), data={'name': 'Legacy photo', 'category_id': 'shirts'}, files={'file': ('one.jpg', image_bytes, 'image/jpeg')})
    assert response.status_code == 201, response.text
    record = services.store.get('garments', response.json()['id'])
    assert record['image_keys'] == [record['image_key']]
    assert len(response.json()['image_urls']) == 1


def test_garment_labels_are_validated_and_patch_can_clear_them(client, image_bytes):
    store, brand = label(client, 'store', 'Shop'), label(client, 'brand', 'Brand')
    response = client.post('/api/garments', headers=auth('admin'), data={'name': 'Dress', 'category_id': 'dresses', 'store_id': store['id']}, files={'file': ('dress.jpg', image_bytes)})
    garment = response.json()
    updated = client.patch('/api/garments/' + garment['id'], headers=auth('admin'), json={'brand_id': brand['id'], 'store_id': None})
    assert updated.status_code == 200
    assert updated.json()['store_id'] is None and updated.json()['brand_id'] == brand['id']
    for changes in [{'store_id': brand['id']}, {'brand_id': store['id']}, {'brand_id': 'missing'}]:
        assert client.patch('/api/garments/' + garment['id'], headers=auth('admin'), json=changes).status_code == 400
    response = client.post('/api/garments', headers=auth('admin'), data={'name': 'Dress', 'category_id': 'dresses', 'brand_id': 'missing'}, files={'file': ('dress.jpg', image_bytes)})
    assert response.status_code == 400


def test_garment_upload_photo_limits_and_bad_photo_do_not_persist_partial_data(client, services, image_bytes):
    before_garments, before_objects = services.store.list('garments'), dict(services.objects.values)
    data = {'name': 'Many photos', 'category_id': 'dresses'}
    assert client.post('/api/garments', headers=auth('admin'), data=data).status_code == 400
    seven = [('files', (f'{index}.jpg', image_bytes, 'image/jpeg')) for index in range(7)]
    assert client.post('/api/garments', headers=auth('admin'), data=data, files=seven).status_code == 400
    bad = [('files', ('good.jpg', image_bytes)), ('files', ('bad.jpg', b'not-an-image'))]
    assert client.post('/api/garments', headers=auth('admin'), data=data, files=bad).status_code == 400
    assert services.store.list('garments') == before_garments
    assert services.objects.values == before_objects
    response = client.post('/api/garments', headers=auth('admin'), data=data, files=seven[:6])
    assert response.status_code == 201 and len(response.json()['image_urls']) == 6


def test_garment_object_failure_cleans_already_written_photos(client, services, image_bytes, monkeypatch):
    before_objects = dict(services.objects.values)
    before_garments = services.store.list('garments')
    original_put = services.objects.put
    calls = 0

    def fail_second(kind, key, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('Temporary object write failure')
        original_put(kind, key, data)

    monkeypatch.setattr(services.objects, 'put', fail_second)
    response = client.post('/api/admin/garments', headers=auth('admin'), data={'name': 'Dress', 'category_id': 'dresses'}, files=[('files', ('a.jpg', image_bytes)), ('files', ('b.jpg', image_bytes))])
    assert response.status_code == 503
    assert services.objects.values == before_objects
    assert services.store.list('garments') == before_garments


def test_new_admin_catalog_aliases_require_admin(client, image_bytes):
    category = {'name': 'Jackets', 'slot': 'upper'}
    assert client.post('/api/admin/categories', headers=auth(), json=category).status_code == 403
    response = client.post('/api/admin/categories', headers=auth('admin'), json=category)
    assert response.status_code == 201 and response.json()['id'] == 'jackets'
    assert client.post('/api/admin/garments', headers=auth(), data={'name': 'Jacket', 'category_id': 'jackets'}, files={'file': ('a.jpg', image_bytes)}).status_code == 403


def test_multi_photo_quote_matches_reserved_job_cost(client, services, image_bytes):
    garment = client.post('/api/garments', headers=auth('admin'), data={'name': 'Dress', 'category_id': 'dresses'}, files=[('files', ('front.jpg', image_bytes)), ('files', ('back.jpg', image_bytes))]).json()
    quote = client.post('/api/tryon/estimate', headers=auth(), json={'workflow': 'catalog', 'garment_ids': [garment['id']]})
    assert quote.status_code == 200
    one_reference = client.post('/api/tryon/estimate', headers=auth(), json={'workflow': 'catalog', 'garment_ids': ['dress']}).json()
    assert quote.json()['estimated_cost_usd'] > one_reference['estimated_cost_usd']
    upload = client.post('/api/uploads', headers=auth(), data={'purpose': 'person', 'consent': 'true'}, files={'file': ('person.jpg', image_bytes)}).json()
    job = client.post('/api/tryon/catalog', headers=auth(), json={'upload_id': upload['id'], 'garment_ids': [garment['id']], 'idempotency_key': 'two-reference-catalog-quote'})
    assert job.status_code == 202, job.text
    assert job.json()['estimated_cost_usd'] == quote.json()['estimated_cost_usd']
    assert job.json()['expected_calls'] == quote.json()['expected_calls'] == 1
    stored = services.store.get('generation_jobs', job.json()['id'])
    assert services.store.get('budget_months', stored['budget_month'])['reserved'] == quote.json()['estimated_cost_usd']
    assert client.post('/api/tryon/estimate', headers=auth(), json={'garment_ids': ['missing']}).status_code == 400
