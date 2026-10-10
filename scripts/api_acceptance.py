"""Additional live API checks; no AI calls. Uses the temporary acceptance session."""
import datetime as dt
import io
import json
import pathlib
import secrets
import uuid
from PIL import Image
import pillow_heif
from e2e_live import Acceptance, initialize, token

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / '.deployment/config.json').read_text())
    session = json.loads((ROOT / '.deployment/live-session.json').read_text())
    db = initialize(config)
    a = Acceptance(config, session, db, report=ROOT / 'verification/api-evidence.json')
    a.evidence['generations'] = []
    created = []
    try:
        image = Image.open(ROOT / 'verification/fixtures/person.png')
        raw = io.BytesIO()
        pillow_heif.from_pillow(image).save(raw, quality=80)
        response = a.request('POST', '/api/uploads', 'admin', expected=201, files={'file': ('iphone.heic', raw.getvalue(), 'image/heic')}, data={'consent': 'true', 'purpose': 'share'})
        upload = response.json()
        normalized = a.request('GET', upload['image_url']).content
        decoded = Image.open(io.BytesIO(normalized))
        a.check('Real HEIC upload decodes to normalized JPEG with metadata stripped', decoded.format == 'JPEG' and not decoded.getexif())
        share = a.request('POST', '/api/shares', expected=201, json={'upload_id': upload['id']}).json()
        import urllib.parse
        secret = urllib.parse.urlparse(share['url']).fragment
        db.collection('shares').document(share['id']).update({'expires_at': dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)})
        a.check('Expired bearer is denied at read time before maintenance cleanup', a.request('POST', '/api/shares/download', None, expected=None, json={'token': secret}).status_code == 410)
        a.request('DELETE', '/api/shares/' + share['id'])
        a.request('DELETE', '/api/uploads/' + upload['id'])
        a.check('Explicit upload deletion is enforced', a.request('GET', upload['image_url'], expected=None).status_code == 410)
        # A separate upload tests consent without touching billable generation.
        response = a.request('POST', '/api/uploads', 'admin', expected=None, files={'file': ('person.png', (ROOT / 'verification/fixtures/person.png').read_bytes(), 'image/png')}, data={'consent': 'false', 'purpose': 'person'})
        a.check('Transmission consent is required server-side', response.status_code == 400)
        garment = a.request('POST', '/api/garments', expected=201, files={'file': ('sample.png', (ROOT / 'sample_assets/sports-tshirt.png').read_bytes(), 'image/png')}, data={'name': 'Acceptance hidden garment', 'description': 'Temporary licensed sample copy', 'category_id': 'tshirts', 'license': 'CC0', 'source_url': 'https://commons.wikimedia.org/wiki/File:Sports_T-Shirt.png', 'attribution': 'Kuttos2, CC0', 'active': 'false'}).json()
        created.append(('garment', garment['id']))
        a.check('Inactive garment stays hidden from ordinary users', garment['id'] not in [g['id'] for g in a.request('GET', '/api/garments', 'user').json()])
        changed = a.request('PATCH', '/api/garments/' + garment['id'], json={'active': True, 'attribution': 'Acceptance CC0 attribution'}).json()
        a.check('Administrator can edit garment metadata and activation', changed['active'] and changed['attribution'] == 'Acceptance CC0 attribution')
        a.request('DELETE', '/api/garments/' + garment['id'])
        created.remove(('garment', garment['id']))
        user = a.request('POST', '/api/users', expected=201, json={'email': 'stylereel-revocation-' + uuid.uuid4().hex[:8] + '@example.com', 'password': secrets.token_urlsafe(24), 'role': 'user'}).json()
        created.append(('user', user['id']))
        current, _ = token(config, user['id'])
        session['accounts']['revocation'] = {'uid': user['id'], 'token': current}
        a.check('New user cannot access studio before replacing password', a.request('GET', '/api/settings', 'revocation', expected=None).status_code == 403)
        a.request('POST', '/api/me/password', 'revocation', json={'password': secrets.token_urlsafe(24)})
        # Firebase token auth_time is second resolution; wait across timestamp boundary.
        import time
        time.sleep(1.2)
        current, _ = token(config, user['id'])
        session['accounts']['revocation']['token'] = current
        a.check('Changed-password user gains studio access after reauthentication', a.request('GET', '/api/settings', 'revocation').status_code == 200)
        reset = a.request('POST', '/api/users/' + user['id'] + '/reset').json()
        a.check('Admin reset initiation returns an HTTPS action link', reset['reset_link'].startswith('https://'))
        a.check('Reset initiation revokes the old session', a.request('GET', '/api/me', 'revocation', expected=None).status_code in [401, 403])
        a.request('PATCH', '/api/users/' + user['id'], json={'active': False})
        a.check('Deactivation denies existing session', a.request('GET', '/api/me', 'revocation', expected=None).status_code in [401, 403])
        a.request('PATCH', '/api/users/' + user['id'], json={'active': True})
        a.request('DELETE', '/api/users/' + user['id'])
        created.remove(('user', user['id']))
        a.check('Account deletion removes application profile', not db.collection('users').document(user['id']).get().exists)
    finally:
        for kind, identifier in created:
            a.request('DELETE', ('/api/garments/' if kind == 'garment' else '/api/users/') + identifier, expected=None)
        a.evidence['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        (ROOT / 'verification/api-evidence.json').write_text(json.dumps(a.evidence, indent=2, default=str))


if __name__ == '__main__':
    main()
