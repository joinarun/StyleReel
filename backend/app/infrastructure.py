"""Production cloud implementations. Tests inject their own isolated doubles."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Any, Callable
from google.cloud import firestore, storage, tasks_v2, secretmanager
from google.protobuf import timestamp_pb2, duration_pb2
from google.api_core.exceptions import NotFound
import firebase_admin
from firebase_admin import auth
from .config import Environment


def now() -> datetime:
    return datetime.now(timezone.utc)


class TransactionView:
    def __init__(self, store: 'FirestoreStore', transaction):
        self.store, self.transaction = store, transaction
        self.pending: dict[tuple[str, str], dict | None] = {}

    def get(self, collection: str, identifier: str) -> dict | None:
        key = (collection, identifier)
        if key in self.pending:
            return self.pending[key]
        snap = self.store.client.collection(collection).document(identifier).get(transaction=self.transaction)
        return dict(snap.to_dict(), id=snap.id) if snap.exists else None

    def set(self, collection: str, identifier: str, value: dict):
        self.pending[(collection, identifier)] = dict(value)

    def delete(self, collection: str, identifier: str):
        self.pending[(collection, identifier)] = None

    def flush(self):
        for (collection, identifier), value in self.pending.items():
            ref = self.store.client.collection(collection).document(identifier)
            if value is None:
                self.transaction.delete(ref)
            else:
                self.transaction.set(ref, {k: v for k, v in value.items() if k != 'id'})


class FirestoreStore:
    def __init__(self, env: Environment):
        self.client = firestore.Client(project=env.project)

    def get(self, collection: str, identifier: str) -> dict | None:
        snap = self.client.collection(collection).document(identifier).get()
        return dict(snap.to_dict(), id=snap.id) if snap.exists else None

    def set(self, collection: str, identifier: str, value: dict):
        self.client.collection(collection).document(identifier).set({k: v for k, v in value.items() if k != 'id'})

    def delete(self, collection: str, identifier: str):
        self.client.collection(collection).document(identifier).delete()

    def list(self, collection: str, filters: dict | None = None) -> list[dict]:
        query = self.client.collection(collection)
        for key, value in (filters or {}).items():
            query = query.where(filter=firestore.FieldFilter(key, '==', value))
        return [dict(s.to_dict(), id=s.id) for s in query.stream()]

    def atomic(self, operation: Callable):
        @firestore.transactional
        def execute(transaction):
            view = TransactionView(self, transaction)
            result = operation(view)
            view.flush()
            return result
        return execute(self.client.transaction(max_attempts=5))


class ObjectStorage:
    def __init__(self, env: Environment):
        self.client, self.env = storage.Client(project=env.project), env

    def bucket(self, kind: str):
        name = self.env.catalog_bucket if kind == 'catalog' else self.env.temp_bucket
        if not name:
            raise RuntimeError('Storage bucket configuration is missing')
        return self.client.bucket(name)

    def put(self, kind: str, key: str, data: bytes):
        blob = self.bucket(kind).blob(key)
        blob.cache_control = 'private, no-store' if kind != 'catalog' else 'private, max-age=300'
        blob.upload_from_string(data, content_type='image/jpeg')

    def get(self, kind: str, key: str) -> bytes:
        return self.bucket(kind).blob(key).download_as_bytes()

    def delete(self, kind: str, key: str):
        try:
            self.bucket(kind).blob(key).delete()
        except NotFound:
            pass


class TaskDispatcher:
    def __init__(self, env: Environment):
        self.env, self.client = env, tasks_v2.CloudTasksClient()

    def enqueue(self, job_id: str, delay: int = 0):
        if not self.env.service_url or not self.env.task_account:
            raise RuntimeError('Task dispatcher has not been configured')
        task = {
            'http_request': {
                'http_method': tasks_v2.HttpMethod.POST,
                'url': f'{self.env.service_url}/internal/tasks',
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'job_id': job_id}).encode(),
                'oidc_token': {'service_account_email': self.env.task_account, 'audience': self.env.service_url},
            },
            'dispatch_deadline': duration_pb2.Duration(seconds=600),
        }
        if delay:
            timestamp = timestamp_pb2.Timestamp()
            timestamp.FromDatetime(now() + timedelta(seconds=delay))
            task['schedule_time'] = timestamp
        parent = self.client.queue_path(self.env.project, self.env.location, self.env.queue)
        self.client.create_task(request={'parent': parent, 'task': task})


class SecretStore:
    def __init__(self, env: Environment):
        self.env, self.client = env, secretmanager.SecretManagerServiceClient()

    def read(self, name: str) -> str | None:
        resource = f'projects/{self.env.project}/secrets/{self.env.secret_prefix}-{name}/versions/latest'
        try:
            return self.client.access_secret_version(request={'name': resource}).payload.data.decode()
        except NotFound:
            return None

    def write(self, name: str, value: str):
        # Infrastructure provisions these secrets; runtime only needs version-adder/accessor permissions.
        parent = f'projects/{self.env.project}/secrets/{self.env.secret_prefix}-{name}'
        self.client.add_secret_version(request={'parent': parent, 'payload': {'data': value.encode()}})


class FirebaseIdentity:
    def __init__(self, env: Environment):
        if not firebase_admin._apps:
            firebase_admin.initialize_app(options={'projectId': env.project})

    def verify(self, token: str):
        return auth.verify_id_token(token, check_revoked=True)

    def create(self, email: str, password: str):
        return auth.create_user(email=email, password=password).uid

    def update(self, uid: str, **fields):
        auth.update_user(uid, **fields)

    def revoke(self, uid: str):
        auth.revoke_refresh_tokens(uid)

    def delete(self, uid: str):
        try:
            auth.delete_user(uid)
        except auth.UserNotFoundError:
            pass

    def reset_link(self, email: str):
        return auth.generate_password_reset_link(email)
