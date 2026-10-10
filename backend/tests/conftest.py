from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import threading
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app, get_services, Services
from app.config import Environment, CATEGORIES
from app.infrastructure import now
from app.jobs import JobService
from app.providers import ProviderResult, ProviderError


class MemoryStore:
    """Strictly test-only repository with serializable rollback transactions."""
    def __init__(self):
        self.values = {}
        self.lock = threading.RLock()

    def get(self, collection, identifier):
        with self.lock:
            item = self.values.get((collection, identifier))
            return dict(deepcopy(item), id=identifier) if item is not None else None

    def set(self, collection, identifier, value):
        with self.lock:
            self.values[(collection, identifier)] = deepcopy(value)

    def delete(self, collection, identifier):
        with self.lock:
            self.values.pop((collection, identifier), None)

    def list(self, collection, filters=None):
        with self.lock:
            return [dict(deepcopy(v), id=k) for (c, k), v in self.values.items() if c == collection and all(v.get(f) == expected for f, expected in (filters or {}).items())]

    def atomic(self, operation):
        with self.lock:
            before = deepcopy(self.values)
            try:
                return operation(self)
            except Exception:
                self.values = before
                raise


class MemoryObjects:
    def __init__(self):
        self.values = {}
    def put(self, kind, key, data):
        self.values[(kind, key)] = data
    def get(self, kind, key):
        return self.values[(kind, key)]
    def delete(self, kind, key):
        self.values.pop((kind, key), None)


class Tasks:
    def __init__(self):
        self.calls = []
        self.fail = False
    def enqueue(self, job_id, delay=0):
        if self.fail:
            raise RuntimeError('Test enqueue failure')
        self.calls.append((job_id, delay))


class Identity:
    def __init__(self):
        self.revoked = []
        self.deleted = []
        self.created = []
        self.updated = []
    def verify(self, token):
        if token == 'invalid':
            raise ValueError('invalid token')
        return {'uid': token, 'auth_time': now().timestamp()}
    def create(self, email, password):
        uid = f'user-{len(self.created)}'
        self.created.append((uid, email))
        return uid
    def update(self, uid, **fields):
        self.updated.append((uid, fields))
    def revoke(self, uid):
        self.revoked.append(uid)
    def delete(self, uid):
        self.deleted.append(uid)
    def reset_link(self, email):
        return 'https://example.test/reset/one-time'


class Secrets:
    def __init__(self):
        self.values = {}
    def write(self, name, value):
        self.values[name] = value
    def read(self, name):
        return self.values.get(name)


class Provider:
    def __init__(self, image):
        self.image = image
        self.submissions = []
        self.polls = []
        self.preflights = []
        self.async_mode = False
        self.ambiguous = False
        self.suitable = True
        self.pending_polls = 0
    def submit(self, person, garments, settings, workflow, instructions=None):
        self.submissions.append((person, garments, settings, workflow))
        if self.ambiguous:
            raise ProviderError('Test ambiguous connection', ambiguous=True)
        return ProviderResult('processing', prediction_id=f'prediction-{len(self.submissions)}') if self.async_mode else ProviderResult('succeeded', image=self.image, usage={'promptTokenCount': 42})
    def poll(self, prediction_id, settings):
        self.polls.append(prediction_id)
        if self.pending_polls:
            self.pending_polls -= 1
            return ProviderResult('processing', prediction_id)
        return ProviderResult('succeeded', prediction_id, self.image)
    def preflight(self, image, settings):
        self.preflights.append(image)
        return self.suitable, 'Hold one garment clearly in front of your body.', {'promptTokenCount': 17}


class Providers:
    def __init__(self, provider):
        self.provider = provider
        self.configured = True
    def get(self, identifier):
        return self.provider
    def info(self, settings):
        return [{'id': p, 'label': p, 'configured': self.configured, 'status': 'terms_unconfirmed' if p == 'pruna' and not settings.pruna_terms_confirmed else 'configured_not_live_tested', 'models': ['gemini-3-pro-image', 'gemini-nano-banana-2.1'] if p == 'google' else ['tryon-max'] if p == 'fashn' else ['p-image-try-on'], 'supports_holding': p == 'google', 'supports_multi': True, 'prompt_supported': True} for p in ['google', 'fashn', 'pruna']]


@pytest.fixture
def image_bytes():
    buf = BytesIO()
    Image.new('RGB', (320, 480), (170, 120, 100)).save(buf, 'JPEG')
    return buf.getvalue()


@pytest.fixture
def services(image_bytes):
    store, objects, tasks, identity, secrets_store = MemoryStore(), MemoryObjects(), Tasks(), Identity(), Secrets()
    providers = Providers(Provider(image_bytes))
    env = Environment(service_url='https://stylereel.test', task_account='tasks@test.iam.gserviceaccount.com', max_upload_bytes=12 * 1024 * 1024)
    services = Services(env, store, objects, tasks, identity, secrets_store, providers, JobService(store, objects, tasks, providers))
    for uid, role in [('admin', 'admin'), ('user', 'user'), ('other', 'user')]:
        store.set('users', uid, {'email': f'{uid}@test.com', 'role': role, 'active': True, 'must_change_password': False, 'created_at': now()})
    for category in CATEGORIES:
        store.set('categories', category['id'], category)
    for garment_id, category in [('shirt', 'shirts'), ('pants', 'pants'), ('dress', 'dresses')]:
        key = f'garments/{garment_id}.jpg'
        objects.put('catalog', key, image_bytes)
        store.set('garments', garment_id, {'name': garment_id, 'category_id': category, 'active': True, 'image_key': key, 'thumbnail_key': key})
    app.dependency_overrides[get_services] = lambda: services
    yield services
    app.dependency_overrides.clear()


@pytest.fixture
def client(services):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def auth(uid='user'):
    return {'Authorization': f'Bearer {uid}'}
