"""Remove only pinned catalog-upgrade verification fixtures and disposable accounts.

Default execution is a local dry run. Pass --execute after verification finishes.
This never discovers catalog resources by a global name search and never deletes
generation, usage or budget history. No new accounts or AI requests are created.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STATE_NAMES = ('catalog-verification.json', 'catalog-browser-state.json')
COLLECTIONS = {'garment': 'garments', 'category': 'categories', 'store': 'catalog_stores', 'brand': 'catalog_brands'}
NAME_PREFIXES = {
    'catalog-verification.json': {'garment': 'Verification multi-view dress ', 'category': 'Verification dresses ', 'store': 'Verification store ', 'brand': 'Verification brand '},
    'catalog-browser-state.json': {'garment': 'Browser multi-photo dress ', 'category': 'Browser dresses ', 'store': 'Browser Store ', 'brand': 'Browser Brand '},
}


def load_scope(root: Path = ROOT) -> dict:
    resources = {collection: {} for collection in COLLECTIONS.values()}
    manifests = []
    for filename in STATE_NAMES:
        path = root / '.deployment' / filename
        if not path.exists():
            continue
        state = json.loads(path.read_text())
        run_id = state.get('run_id', '')
        if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{10}', run_id):
            raise ValueError(f'{filename} does not contain a recognized verification run ID.')
        manifests.append(filename)
        for kind, collection in COLLECTIONS.items():
            record = state.get(kind)
            if record is None:  # Interrupted runs can contain only some fixtures.
                continue
            expected_name = NAME_PREFIXES[filename][kind] + run_id
            if not isinstance(record, dict) or record.get('name') != expected_name:
                raise ValueError(f'{filename} contains an unrecognized {kind} fixture.')
            identifier = record.get('id', '')
            pattern = r'[a-f0-9]{32}' if kind == 'garment' else (r'[a-z][a-z0-9-]{1,50}' if kind == 'category' else kind + r'-[a-f0-9]{24}')
            if not isinstance(identifier, str) or not re.fullmatch(pattern, identifier):
                raise ValueError(f'{filename} contains an invalid {kind} fixture ID.')
            previous = resources[collection].get(identifier)
            if previous is not None and previous != expected_name:
                raise ValueError('The verification manifests disagree on a fixture identity.')
            resources[collection][identifier] = expected_name
    if not manifests:
        raise ValueError('No pinned catalog verification manifests exist; nothing will be deleted.')
    return {'manifests': manifests, 'resources': resources}


def garment_object_keys(identifier: str, garment: dict) -> list[str]:
    keys = set(garment.get('image_keys') or [garment.get('image_key')])
    keys.update([garment.get('image_key'), garment.get('thumbnail_key')])
    allowed = re.compile(r'(?:garments/' + re.escape(identifier) + r'(?:/[0-5])?|thumbnails/' + re.escape(identifier) + r')\.jpg')
    if any(not isinstance(key, str) or not allowed.fullmatch(key) for key in keys):
        raise ValueError('A verification garment references an object outside its pinned fixture path.')
    return sorted(keys)


def disposable_accounts(session: dict) -> list[str]:
    accounts = session.get('accounts', {})
    if not isinstance(accounts, dict) or 'admin' not in accounts:
        raise ValueError('A disposable acceptance administrator session is required for account cleanup.')
    uids = []
    for role, account in accounts.items():
        if role not in {'admin', 'user', 'comparison'} or not isinstance(account, dict):
            raise ValueError('The acceptance session contains an unrecognized account role.')
        uid, email = account.get('uid'), account.get('email')
        pattern = r'stylereel-(?:revision-)?' + role + r'-[a-f0-9]{8}@example\.com'
        if not isinstance(uid, str) or not uid or '/' in uid or not isinstance(email, str) or not re.fullmatch(pattern, email):
            raise ValueError('The acceptance session contains an account that is not a disposable fixture.')
        uids.append(uid)
    if len(set(uids)) != len(uids):
        raise ValueError('The acceptance session contains duplicate account IDs.')
    return uids


def configure_environment(config: dict):
    # Existing e2e cleanup's privileged self-admin fallback uses these exact buckets.
    os.environ.update({
        'GOOGLE_CLOUD_PROJECT': config['project'],
        'STORAGE_CATALOG_BUCKET': config['catalog_bucket'],
        'STORAGE_TEMP_BUCKET': config['temp_bucket'],
        'SERVICE_URL': config['service_url'],
        'TASKS_LOCATION': config['region'],
        'TASKS_SERVICE_ACCOUNT': config['task_account'],
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Delete only resources pinned in the catalog verification manifests.')
    args = parser.parse_args()
    scope = load_scope()
    session_path = ROOT / '.deployment/live-session.json'
    session = json.loads(session_path.read_text()) if session_path.exists() else None
    uids = disposable_accounts(session) if session is not None else []
    counts = {collection: len(records) for collection, records in scope['resources'].items()}
    if not args.execute:
        print(json.dumps({'mode': 'dry_run', 'pinned_catalog_resources': counts, 'disposable_accounts': len(uids), 'preserves': ['generation_jobs', 'usage_events', 'budget_months']}))
        return

    config = json.loads((ROOT / '.deployment/config.json').read_text())
    if session is not None and session.get('url') != config['service_url']:
        raise ValueError('The acceptance session and deployment refer to different services.')
    configure_environment(config)
    from e2e_live import initialize, cleanup, save
    from firebase_admin import auth
    from app.main import get_services
    from google.cloud.firestore_v1.base_query import FieldFilter

    db = initialize(config)
    get_services.cache_clear()
    services = get_services()
    current = {collection: {} for collection in scope['resources']}
    # Validate every pinned fixture and account before making the first deletion.
    for collection, records in scope['resources'].items():
        for identifier, expected_name in records.items():
            record = services.store.get(collection, identifier)
            if record is not None:
                if record.get('name') != expected_name:
                    raise ValueError('A pinned resource was changed outside verification; cleanup is refused.')
                if collection == 'garments':
                    garment_object_keys(identifier, record)
                current[collection][identifier] = record
    for collection, field in [('categories', 'category_id'), ('catalog_stores', 'store_id'), ('catalog_brands', 'brand_id')]:
        for identifier in scope['resources'][collection]:
            linked = db.collection('garments').where(filter=FieldFilter(field, '==', identifier)).stream()
            if any(document.id not in scope['resources']['garments'] for document in linked):
                raise ValueError('A verification label is used by a garment outside this cleanup scope.')
    for account in (session or {}).get('accounts', {}).values():
        profile = services.store.get('users', account['uid'])
        if profile and profile.get('email') != account['email']:
            raise ValueError('A disposable account ID now belongs to a different user.')
        try:
            identity = auth.get_user(account['uid'])
        except auth.UserNotFoundError:
            continue
        if identity.email != account['email']:
            raise ValueError('A disposable Firebase identity no longer matches the saved fixture.')

    removed = {collection: 0 for collection in scope['resources']}
    for identifier, garment in current['garments'].items():
        # Object keys are checked above, so only this fixture's ordered references are removed.
        for key in garment_object_keys(identifier, garment):
            services.objects.delete('catalog', key)
        services.store.delete('garments', identifier)
        removed['garments'] += 1
    for collection in ['categories', 'catalog_stores', 'catalog_brands']:
        for identifier in current[collection]:
            services.store.delete(collection, identifier)
            removed[collection] += 1

    if session is not None:
        # Missing/expired tokens are handled by existing cleanup's privileged fallback.
        session['accounts']['admin'].setdefault('token', '')
        cleanup(config, session)

    checks = []
    for collection, records in scope['resources'].items():
        checks.append({'name': collection + ' pinned documents removed', 'passed': all(services.store.get(collection, identifier) is None for identifier in records)})
    if uids:
        checks.append({'name': 'Disposable Firestore profiles removed', 'passed': all(services.store.get('users', uid) is None for uid in uids)})
        checks.append({'name': 'Disposable uploads and shares removed', 'passed': all(not services.store.list(collection, {'user_id': uid}) for uid in uids for collection in ['uploads', 'shares'])})
        identities_removed = True
        for uid in uids:
            try:
                auth.get_user(uid)
                identities_removed = False
            except auth.UserNotFoundError:
                pass
        checks.append({'name': 'Disposable Firebase identities removed', 'passed': identities_removed})
    report = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'scope': 'Only IDs pinned by catalog verification manifests and their disposable acceptance accounts.', 'pinned_catalog_resources': counts, 'removed_catalog_resources': removed, 'disposable_accounts': len(uids), 'preserved_collections': ['generation_jobs', 'usage_events', 'budget_months'], 'checks': checks}
    save(ROOT / 'verification/catalog-upgrade-cleanup.json', report)
    if not all(check['passed'] for check in checks):
        raise RuntimeError('Scoped verification cleanup did not complete; rerun with the same pinned state.')
    # This file is the browser persistence snapshot for these disposable sessions.
    if uids:
        (ROOT / '.deployment/catalog-auth-storage.json').unlink(missing_ok=True)
    for filename in scope['manifests']:
        (ROOT / '.deployment' / filename).unlink(missing_ok=True)
    print(json.dumps({'mode': 'executed', 'removed_catalog_resources': removed, 'disposable_accounts': len(uids), 'checks': len(checks), 'history': 'preserved'}))


if __name__ == '__main__':
    main()
