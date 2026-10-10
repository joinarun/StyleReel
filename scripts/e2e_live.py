"""Authorized live acceptance checks using synthetic photos and temporary accounts.

Custom tokens are minted with owner IAM credentials, never by an application route.
No passwords/tokens are printed. All generations pass through normal API quotas/tasks.
"""
import argparse
import datetime as dt
import json
import mimetypes
import pathlib
import secrets
import time
import uuid
import urllib.parse

import firebase_admin
from firebase_admin import auth
from google.cloud import firestore
import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.deployment/live-session.json'
REPORT = ROOT / 'verification/live-evidence.json'
OUT = ROOT / 'verification/results'


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str))
    if '.deployment' in path.parts:
        path.chmod(0o600)


def initialize(config):
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={'projectId': config['project'], 'serviceAccountId': config['runtime_account']})
    return firestore.Client(project=config['project'])


def token(config, uid):
    custom = auth.create_custom_token(uid).decode()
    response = httpx.post('https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken',
                          params={'key': config['firebase']['apiKey']}, json={'token': custom, 'returnSecureToken': True}, timeout=30)
    if response.status_code != 200:
        raise RuntimeError('Temporary account sign-in failed: HTTP ' + str(response.status_code))
    return response.json()['idToken'], custom


def prepare(config, db):
    session = {'url': config['service_url'], 'accounts': {}}
    for role in ['admin', 'user', 'comparison']:
        account = auth.create_user(email='stylereel-' + role + '-' + uuid.uuid4().hex[:8] + '@example.com', password=secrets.token_urlsafe(24))
        db.collection('users').document(account.uid).set({'email': account.email, 'role': 'admin' if role == 'admin' else 'user', 'active': True, 'must_change_password': False, 'created_at': dt.datetime.now(dt.timezone.utc)})
        identity, custom = token(config, account.uid)
        session['accounts'][role] = {'uid': account.uid, 'email': account.email, 'token': identity, 'customToken': custom}
    save(PRIVATE, session)
    save(ROOT / '.deployment/browser-session.json', {'url': session['url'], **session['accounts']['admin'], 'firebase': config['firebase']})
    print('Prepared three temporary acceptance accounts; credentials remain in ignored local files.', flush=True)
    return session


class Acceptance:
    def __init__(self, config, session, db, report=REPORT):
        self.config, self.session, self.db = config, session, db
        self.report = report
        self.client = httpx.Client(base_url=session['url'], timeout=60)
        self.evidence = {'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'service_url': session['url'], 'checks': [], 'generations': [], 'photographs': 'Synthetic fictional adult; no customer photographs.'}
        OUT.mkdir(parents=True, exist_ok=True)

    def check(self, description, value):
        self.evidence['checks'].append({'check': description, 'passed': bool(value)})
        save(self.report, self.evidence)
        if not value:
            raise AssertionError(description)
        print('PASS:', description, flush=True)

    def request(self, method, path, role='admin', expected=200, **kw):
        headers = {'Authorization': 'Bearer ' + self.session['accounts'][role]['token']} if role else {}
        response = self.client.request(method, path, headers=headers, **kw)
        if expected is not None and response.status_code != expected:
            raise RuntimeError(f'{method} {path}: HTTP {response.status_code}: {response.text[:500]}')
        return response

    def upload(self, fixture, purpose, role):
        data = (ROOT / 'verification/fixtures' / fixture).read_bytes()
        return self.request('POST', '/api/uploads', role, expected=201, files={'file': (fixture, data, mimetypes.guess_type(fixture)[0] or 'application/octet-stream')}, data={'consent': 'true', 'purpose': purpose}).json()

    def generate(self, name, model, fixture, garments, workflow='catalog', role='user', configure_model=True):
        settings = self.request('GET', '/api/admin/settings').json()
        settings = {k: v for k, v in settings.items() if k not in ['providers', 'processing_notice']}
        if configure_model:
            settings['ai']['model'] = model
            self.request('PUT', '/api/admin/settings', json=settings)
        elif settings['ai']['provider'] != 'google' or settings['ai']['model'] != model or settings['ai']['resolution'] != '2K':
            raise RuntimeError('The revision benchmark requires the existing Google Pro 2K configuration; no settings were changed.')
        estimate = self.request('POST', '/api/tryon/estimate', role, json={'workflow': workflow, 'garment_ids': garments}).json()
        upload = self.upload(fixture, 'holding' if workflow == 'holding' else 'person', role)
        payload = {'upload_id': upload['id'], 'garment_ids': garments, 'idempotency_key': uuid.uuid4().hex}
        endpoint = '/api/tryon/holding-garment' if workflow == 'holding' else '/api/tryon/catalog'
        while True:
            response = self.request('POST', endpoint, role, expected=None, json=payload)
            if response.status_code != 429:
                break
            delay = min(int(response.headers.get('Retry-After', '15')), 60)
            print(f'{name}: quota correctly enforced; waiting {delay}s.', flush=True)
            time.sleep(delay)
        if response.status_code != 202:
            raise RuntimeError(f'{name}: submission HTTP {response.status_code}: {response.text[:300]}')
        job = response.json()
        duplicate = self.request('POST', endpoint, role, expected=202, json=payload).json()
        self.check(name + ' duplicate submission returns the same job', duplicate['id'] == job['id'])
        started, announced = time.monotonic(), 0
        while job['status'] not in ['succeeded', 'failed', 'unknown']:
            if time.monotonic() - started > 1000:
                raise RuntimeError(name + ': exceeded acceptance polling timeout; will not resubmit.')
            time.sleep(3)
            job = self.request('GET', '/api/tryon/jobs/' + job['id'], role).json()
            if time.monotonic() - announced > 30:
                print(name + ': ' + job['status'], flush=True)
                announced = time.monotonic()
        record = self.db.collection('generation_jobs').document(job['id']).get().to_dict()
        receipt = {'name': name, 'model': model, 'workflow': workflow, 'fixture': fixture, 'garments': garments, 'job_id': job['id'], 'status': job['status'], 'error': job.get('error'), 'expected_calls': estimate['expected_calls'], 'reserved_usd': estimate['estimated_cost_usd'], 'estimated_charged_usd': record.get('charged_estimate_usd'), 'attempts': record.get('attempts'), 'duration_seconds': round(time.monotonic() - started, 2)}
        if job['status'] == 'succeeded':
            image = self.request('GET', job['result_url'], role).content
            target = OUT / (name + '.jpg')
            target.write_bytes(image)
            receipt['output_file'] = str(target.relative_to(ROOT))
            receipt['result_bytes'] = len(image)
            self.check(name + ' result denies anonymous access', self.request('GET', job['result_url'], None, expected=None).status_code == 401)
            self.check(name + ' result denies another account', self.request('GET', job['result_url'], 'admin' if role != 'admin' else 'user', expected=None).status_code == 404)
        self.check(name + ' source is deleted after terminal state', self.request('GET', upload['image_url'], role, expected=None).status_code in [404, 410])
        self.evidence['generations'].append(receipt)
        save(self.report, self.evidence)
        print(f'{name}: {job["status"]}; estimated charged ${receipt["estimated_charged_usd"]}', flush=True)
        return job

    def run(self, full):
        self.check('HTTPS and security headers', self.request('GET', '/api/config', None).headers.get('x-content-type-options') == 'nosniff')
        for path in ['/api/settings', '/api/users', '/internal/maintenance']:
            method = 'POST' if path.startswith('/internal') else 'GET'
            self.check(path + ' rejects anonymous requests', self.request(method, path, None, expected=None, json={} if method == 'POST' else None).status_code in [401, 403])
        self.check('User cannot administer accounts', self.request('GET', '/api/users', 'user', expected=None).status_code == 403)
        self.check('Nine garment categories are present', len(self.request('GET', '/api/categories', 'user').json()) == 9)
        self.check('Seed catalog includes license attribution', all(x.get('license') and x.get('source_url') for x in self.request('GET', '/api/garments', 'user').json()))
        uid = auth.get_user_by_email('joinarun@gmail.com').uid
        initial, _ = token(self.config, uid)
        response = self.client.get('/api/settings', headers={'Authorization': 'Bearer ' + initial})
        if self.db.collection('users').document(uid).get().to_dict().get('must_change_password'):
            self.check('Public bootstrap administrator is password-change gated', response.status_code == 403 and 'password' in response.text)
        else:
            self.check('Bootstrap administrator already completed its initial password change', response.status_code == 200)
        malformed = self.request('POST', '/api/uploads', 'user', expected=None, files={'file': ('spoof.jpg', b'not a photo', 'image/jpeg')}, data={'consent': 'true', 'purpose': 'person'})
        self.check('Malformed image is rejected', malformed.status_code == 400)
        original = self.request('GET', '/api/admin/settings').json()
        original = {k: v for k, v in original.items() if k not in ['providers', 'processing_notice']}
        try:
            job = self.generate('pro-tshirt', 'gemini-3-pro-image', 'person.png', ['sample-sports-tshirt'], role='admin')
            self.check('Actual Google Pro generation succeeds', job['status'] == 'succeeded')
            session = json.loads((ROOT / '.deployment/browser-session.json').read_text())
            session.update(jobId=job['id'], resultUrl=job['result_url'])
            save(ROOT / '.deployment/browser-session.json', session)
            share = self.request('POST', '/api/shares', expected=201, json={'result_id': job['id']}).json()
            bearer = urllib.parse.urlparse(share['url']).fragment
            self.check('Anonymous QR bearer downloads image', self.request('POST', '/api/shares/download', None, json={'token': bearer}).headers.get('content-type', '').startswith('image/'))
            self.check('QR expiry is within 15 minutes', 0 < (dt.datetime.fromisoformat(share['expires_at'].replace('Z', '+00:00')) - dt.datetime.now(dt.timezone.utc)).total_seconds() <= 900)
            self.request('DELETE', '/api/shares/' + share['id'])
            self.check('Revoked QR returns Gone', self.request('POST', '/api/shares/download', None, expected=None, json={'token': bearer}).status_code == 410)
            if full:
                cases = [('tshirt', 'person.png', ['sample-sports-tshirt'], 'catalog'), ('outfit', 'person.png', ['sample-sports-tshirt', 'sample-cotton-skirt'], 'catalog'), ('saree', 'person.png', ['sample-saree'], 'catalog'), ('holding-clear', 'holding.png', [], 'holding'), ('holding-ambiguous', 'person.png', [], 'holding')]
                for model, prefix, role in [('gemini-3-pro-image', 'pro', 'user'), ('gemini-nano-banana-2.1', 'nano', 'comparison')]:
                    for name, fixture, garments, workflow in cases:
                        if prefix == 'pro' and name == 'tshirt':
                            continue
                        self.generate(prefix + '-' + name, model, fixture, garments, workflow, role)
                self.generate('pro-dress', 'gemini-3-pro-image', 'person.png', ['sample-cream-dress'], role='user')
            self.evidence['analytics'] = self.request('GET', '/api/admin/analytics').json()
            self.evidence['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        finally:
            self.request('PUT', '/api/admin/settings', json=original)
            save(self.report, self.evidence)


def cleanup(config, session):
    with httpx.Client(base_url=session['url'], timeout=60) as client:
        admin_headers = {'Authorization': 'Bearer ' + session['accounts']['admin']['token']}
        for role in [name for name in session['accounts'] if name != 'admin'] + ['admin']:
            uid = session['accounts'][role]['uid']
            response = client.delete('/api/users/' + uid, headers=admin_headers)
            if role == 'admin' or response.status_code != 200:
                # API correctly forbids self-deletion; privileged cleanup removes final test administrator.
                from app.main import get_services
                services = get_services()
                from app.jobs import TERMINAL
                for job in services.store.list('generation_jobs', {'user_id': uid}):
                    if job['status'] not in TERMINAL:
                        services.jobs.finish(job, 'failed', 'Acceptance account cleanup.')
                    for key in ['source_key', 'result_key', 'intermediate_key']:
                        if job.get(key):
                            services.objects.delete('temp', job[key])
                    services.jobs._update(job['id'], result_deleted=True, result_cleanup_pending=False)
                for upload in services.store.list('uploads', {'user_id': uid}):
                    services.objects.delete('temp', upload['key'])
                    services.store.delete('uploads', upload['id'])
                for share in services.store.list('shares', {'user_id': uid}):
                    services.objects.delete('temp', share['key'])
                    services.store.delete('shares', share['id'])
                try:
                    auth.delete_user(uid)
                except auth.UserNotFoundError:
                    pass
                services.store.delete('users', uid)
    PRIVATE.unlink(missing_ok=True)
    (ROOT / '.deployment/browser-session.json').unlink(missing_ok=True)
    (ROOT / '.deployment/login-test.json').unlink(missing_ok=True)
    print('Removed temporary accounts and application-controlled test images.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--cleanup', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / '.deployment/config.json').read_text())
    db = initialize(config)
    if args.cleanup and not PRIVATE.exists():
        raise SystemExit('No acceptance session exists; cleanup will not create new accounts.')
    session = json.loads(PRIVATE.read_text()) if PRIVATE.exists() else prepare(config, db)
    if args.cleanup:
        cleanup(config, session)
    elif not args.prepare:
        Acceptance(config, session, db).run(args.full)
