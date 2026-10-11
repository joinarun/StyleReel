"""Live catalog/reference and child holding checks with synthetic/licensed photos.

Reuses saved idempotency keys after interruption; never starts a replacement paid
job for an existing outcome. Credentials and replay state stay in .deployment.
"""
import datetime as dt
import json
import time
import uuid

from e2e_live import ROOT, PRIVATE, Acceptance, initialize, save


STATE = ROOT / '.deployment/catalog-verification.json'
REPORT = ROOT / 'verification/catalog-upgrade-live.json'


def main():
    config = json.loads((ROOT / '.deployment/config.json').read_text())
    session = json.loads(PRIVATE.read_text())
    db = initialize(config)
    run = Acceptance(config, session, db, report=REPORT)
    if REPORT.exists():
        run.evidence = json.loads(REPORT.read_text())
    run.evidence['photographs'] = 'Fictional adult and fictional child, plus licensed dress/mannequin references; no customer photographs.'
    state = json.loads(STATE.read_text()) if STATE.exists() else {'run_id': uuid.uuid4().hex[:10], 'jobs': {}}
    save(STATE, state)

    for path in ['/api/catalog/labels', '/api/garments']:
        run.check(path + ' denies anonymous access', run.request('GET', path, None, expected=None).status_code == 401)
    run.check('Regular user cannot create labels', run.request('POST', '/api/admin/catalog/labels', 'user', expected=None, json={'kind': 'store', 'name': 'Forbidden'}).status_code == 403)
    if 'garment' not in state:
        for kind in ['store', 'brand']:
            label = run.request('POST', '/api/admin/catalog/labels', expected=201, json={'kind': kind, 'name': f'Verification {kind} {state["run_id"]}'}).json()
            state[kind] = label
            save(STATE, state)
        category = run.request('POST', '/api/admin/categories', expected=201, json={'name': 'Verification dresses ' + state['run_id'], 'slot': 'full'}).json()
        state['category'] = category
        save(STATE, state)
        references = [('files', ('dress-mannequin.jpg', (ROOT / 'sample_assets/cream-dress.jpg').read_bytes(), 'image/jpeg')),
                      ('files', ('dress-worn.jpg', (ROOT / 'verification/results/pro-dress.jpg').read_bytes(), 'image/jpeg'))]
        garment = run.request('POST', '/api/admin/garments', expected=201, files=references,
                              data={'name': 'Verification multi-view dress ' + state['run_id'], 'category_id': category['id'],
                                    'store_id': state['store']['id'], 'brand_id': state['brand']['id'],
                                    'license': 'Licensed sample plus fictional generated reference',
                                    'attribution': 'StyleReel verification fixture; not a retail catalog item.'}).json()
        state['garment'] = garment
        save(STATE, state)
    garment = state['garment']
    pieces = run.request('GET', '/api/garments', 'user').json()
    current = next(piece for piece in pieces if piece['id'] == garment['id'])
    run.check('Store/brand/type metadata persists with two ordered garment photos', current['store_id'] == state['store']['id'] and current['brand_id'] == state['brand']['id'] and current['category_id'] == state['category']['id'] and len(current['image_urls']) == 2)
    for index, url in enumerate(current['image_urls']):
        run.check(f'Garment photo {index + 1} requires authentication', run.request('GET', url, None, expected=None).status_code == 401)
        run.check(f'Garment photo {index + 1} can be retrieved by regular users', run.request('GET', url, 'user').headers.get('content-type', '').startswith('image/'))

    settings = run.request('GET', '/api/admin/settings').json()
    run.check('Live verification uses existing Google Pro 2K configuration', settings['ai']['provider'] == 'google' and settings['ai']['model'] == 'gemini-3-pro-image' and settings['ai']['resolution'] == '2K')
    # The child is deliberately different from the adult in the garment photo,
    # making identity/age leakage visible in the resulting reference test.
    cases = [('catalog-multi-model-reference', 'child-holding.png', [garment['id']], 'catalog', 'user'),
             ('holding-fictional-child', 'child-holding.png', [], 'holding', 'comparison')]
    for name, fixture, garment_ids, workflow, role in cases:
        endpoint = '/api/tryon/catalog' if workflow == 'catalog' else '/api/tryon/holding-garment'
        existing = state['jobs'].get(name)
        if not existing:
            quote = run.request('POST', '/api/tryon/estimate', role, json={'workflow': workflow, 'garment_ids': garment_ids}).json()
            upload = run.upload(fixture, 'person' if workflow == 'catalog' else 'holding', role)
            existing = {'role': role, 'workflow': workflow, 'quote': quote, 'upload': upload,
                        'payload': {'upload_id': upload['id'], 'garment_ids': garment_ids, 'idempotency_key': uuid.uuid4().hex}}
            state['jobs'][name] = existing
            save(STATE, state)
        if not existing.get('job_id'):
            response = run.request('POST', endpoint, role, expected=None, json=existing['payload'])
            if response.status_code != 202:
                raise RuntimeError(f'{name}: HTTP {response.status_code}; no replacement request was issued.')
            existing['job_id'] = response.json()['id']
            save(STATE, state)
        job = run.request('GET', '/api/tryon/jobs/' + existing['job_id'], role).json()
        duplicate = run.request('POST', endpoint, role, expected=202, json=existing['payload']).json()
        run.check(name + ' replay returns the same paid job', duplicate['id'] == job['id'])
        started = time.monotonic()
        while job['status'] not in ['succeeded', 'failed', 'unknown']:
            if time.monotonic() - started > 900:
                raise RuntimeError('Polling timed out; saved job ID will be reconciled without resubmission.')
            time.sleep(5)
            job = run.request('GET', '/api/tryon/jobs/' + job['id'], role).json()
            print(name + ': ' + job['status'], flush=True)
        snapshot = db.collection('generation_jobs').document(job['id']).get().to_dict()
        receipt = {'name': name, 'job_id': job['id'], 'status': job['status'], 'workflow': workflow,
                   'attempts': snapshot.get('attempts'), 'reference_count': snapshot.get('reference_count'),
                   'reserved_usd': snapshot['estimated_cost_usd'], 'estimated_charged_usd': snapshot.get('charged_estimate_usd'),
                   'error': job.get('error')}
        run.evidence['generations'] = [x for x in run.evidence.get('generations', []) if x['name'] != name] + [receipt]
        save(REPORT, run.evidence)
        run.check(name + ' succeeds through Google', job['status'] == 'succeeded')
        run.check(name + ' quote matches immutable cost reservation', existing['quote']['estimated_cost_usd'] == snapshot['estimated_cost_usd'])
        run.check(name + ' source photo is deleted on completion', run.request('GET', existing['upload']['image_url'], role, expected=None).status_code in [404, 410])
        if workflow == 'catalog':
            run.check('Both mannequin/model garment photos reach the immutable job snapshot', snapshot['reference_count'] == 2 and len(snapshot['garment_reference_groups'][0]['image_keys']) == 2 and snapshot['attempts'] == 1)
        else:
            run.check('Fictional child passes held-garment check and reaches image generation', snapshot['preflight_done'] and snapshot['attempts'] == 2)
        (ROOT / 'verification/results' / (name + '.jpg')).write_bytes(run.request('GET', job['result_url'], role).content)
        run.check(name + ' result denies anonymous access', run.request('GET', job['result_url'], None, expected=None).status_code == 401)
        print(f'{name}: succeeded; estimated AI usage ${snapshot.get("charged_estimate_usd")}', flush=True)
    run.evidence['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    save(REPORT, run.evidence)


if __name__ == '__main__':
    main()
