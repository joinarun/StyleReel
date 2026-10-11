import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('catalog_verify_cleanup', Path(__file__).resolve().parents[2] / 'scripts/catalog_verify_cleanup.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def save_state(tmp_path, filename, state):
    directory = tmp_path / '.deployment'
    directory.mkdir(exist_ok=True)
    (directory / filename).write_text(json.dumps(state))


def test_cleanup_scope_uses_only_pinned_catalog_ids_and_accepts_interrupted_runs(tmp_path):
    run_id = '0123456789'
    identifier = 'a' * 32
    save_state(tmp_path, 'catalog-verification.json', {'run_id': run_id, 'garment': {'id': identifier, 'name': 'Verification multi-view dress ' + run_id}, 'jobs': {'unrelated': {'id': 'should-not-be-used'}}})
    save_state(tmp_path, 'catalog-browser-state.json', {'run_id': 'abcdef0123', 'store': {'id': 'store-' + 'b' * 24, 'name': 'Browser Store abcdef0123'}})
    scope = cleanup.load_scope(tmp_path)
    assert scope['resources']['garments'] == {identifier: 'Verification multi-view dress ' + run_id}
    assert scope['resources']['catalog_stores'] == {'store-' + 'b' * 24: 'Browser Store abcdef0123'}
    assert scope['resources']['categories'] == scope['resources']['catalog_brands'] == {}


def test_cleanup_scope_refuses_missing_manifest_or_non_fixture_name(tmp_path):
    with pytest.raises(ValueError, match='No pinned'):
        cleanup.load_scope(tmp_path)
    save_state(tmp_path, 'catalog-verification.json', {'run_id': '0123456789', 'garment': {'id': 'a' * 32, 'name': 'Customer dress'}})
    with pytest.raises(ValueError, match='unrecognized garment'):
        cleanup.load_scope(tmp_path)


def test_cleanup_scope_refuses_invalid_run_and_identifier(tmp_path):
    save_state(tmp_path, 'catalog-browser-state.json', {'run_id': 'unknown'})
    with pytest.raises(ValueError, match='run ID'):
        cleanup.load_scope(tmp_path)
    save_state(tmp_path, 'catalog-browser-state.json', {'run_id': '0123456789', 'store': {'id': '../../users', 'name': 'Browser Store 0123456789'}})
    with pytest.raises(ValueError, match='invalid store'):
        cleanup.load_scope(tmp_path)


def test_cleanup_object_keys_are_limited_to_one_pinned_garment():
    identifier = 'a' * 32
    keys = ['garments/' + identifier + '.jpg', 'garments/' + identifier + '/1.jpg']
    thumbnail = 'thumbnails/' + identifier + '.jpg'
    assert cleanup.garment_object_keys(identifier, {'image_key': keys[0], 'image_keys': keys, 'thumbnail_key': thumbnail}) == sorted(keys + [thumbnail])
    with pytest.raises(ValueError, match='outside'):
        cleanup.garment_object_keys(identifier, {'image_key': keys[0], 'image_keys': [keys[0], 'garments/customer.jpg'], 'thumbnail_key': thumbnail})


def test_cleanup_accounts_are_only_recognized_disposable_fixtures():
    session = {'accounts': {'admin': {'uid': 'temp-admin', 'email': 'stylereel-revision-admin-01234567@example.com'}, 'user': {'uid': 'temp-user', 'email': 'stylereel-user-89abcdef@example.com'}}}
    assert cleanup.disposable_accounts(session) == ['temp-admin', 'temp-user']
    session['accounts']['admin']['email'] = 'joinarun@gmail.com'
    with pytest.raises(ValueError, match='not a disposable'):
        cleanup.disposable_accounts(session)
