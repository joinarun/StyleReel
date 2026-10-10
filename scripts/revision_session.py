"""Create disposable revision-test accounts without service-account impersonation.

Use browser_signin.mjs for ordinary CAPTCHA-protected email/password sign-in,
then e2e_live.py --cleanup to remove only these accounts and their images.
Credentials stay in ignored, owner-readable files and are never printed.
"""
import datetime as dt
import json
import secrets
import uuid

from e2e_live import ROOT, PRIVATE, initialize, save
from firebase_admin import auth


def main():
    if PRIVATE.exists():
        raise SystemExit('An acceptance session already exists; do not create duplicate test accounts.')
    config = json.loads((ROOT / '.deployment/config.json').read_text())
    db = initialize(config)
    session = {'url': config['service_url'], 'accounts': {}, 'authentication': 'ordinary email/password with enforced reCAPTCHA'}
    save(PRIVATE, session)
    for role in ['admin', 'user', 'comparison']:
        password = secrets.token_urlsafe(24)
        account = auth.create_user(email='stylereel-revision-' + role + '-' + uuid.uuid4().hex[:8] + '@example.com', password=password)
        session['accounts'][role] = {'uid': account.uid, 'email': account.email, 'password': password}
        save(PRIVATE, session)
        db.collection('users').document(account.uid).set({
            'email': account.email, 'role': 'admin' if role == 'admin' else 'user',
            'active': True, 'must_change_password': False, 'created_at': dt.datetime.now(dt.timezone.utc),
        })
    save(ROOT / '.deployment/browser-session.json', {'url': session['url'], **session['accounts']['admin'], 'firebase': config['firebase'], 'authentication': session['authentication']})
    print('Prepared three disposable accounts for ordinary browser sign-in; credentials remain private.', flush=True)


if __name__ == '__main__':
    main()
