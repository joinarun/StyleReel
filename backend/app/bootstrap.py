"""Provision initial administrator and categories using ADC.

Run: PYTHONPATH=backend .venv/bin/python -m app.bootstrap
Password is read/written only through Secret Manager; never printed.
"""
import os
import secrets
import firebase_admin
from firebase_admin import auth
from .config import Environment, CATEGORIES
from .infrastructure import FirestoreStore, SecretStore, FirebaseIdentity, now
from .models import Settings


def bootstrap():
    env = Environment()
    identity = FirebaseIdentity(env)
    store = FirestoreStore(env)
    email = os.getenv('BOOTSTRAP_ADMIN_EMAIL', 'joinarun@gmail.com')
    try:
        user = auth.get_user_by_email(email)
        existing = True
    except auth.UserNotFoundError:
        existing = False
        if env.emulator:
            password = 'admin123'
        else:
            secret_store = SecretStore(env)
            password = secret_store.read('bootstrap-password')
            if not password:
                password = secrets.token_urlsafe(24)
                secret_store.write('bootstrap-password', password)
            if password == 'admin123' or len(password) < 12:
                raise RuntimeError('Public bootstrap requires a unique password of at least 12 characters in Secret Manager.')
        user = auth.create_user(email=email, password=password)
    profile = store.get('users', user.uid)
    if not profile:
        store.set('users', user.uid, {'email': email, 'role': 'admin', 'active': True, 'must_change_password': True, 'created_at': now()})
    elif profile.get('role') != 'admin':
        raise RuntimeError('Administrator email belongs to a standard user; refusing to elevate silently.')
    for category in CATEGORIES:
        if not store.get('categories', category['id']):
            store.set('categories', category['id'], category)
    if not store.get('application_settings', 'main'):
        store.set('application_settings', 'main', Settings().model_dump())
    print(f'Administrator profile ready: {email}; uid={user.uid}; existing={existing}. Initial password is in Secret Manager (or admin123 for the emulator only).')


if __name__ == '__main__':
    bootstrap()
