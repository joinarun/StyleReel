from __future__ import annotations
import base64
from datetime import timedelta
from functools import lru_cache
import hashlib
from pathlib import Path
import secrets
import uuid
from collections import Counter
from dataclasses import dataclass
import os
from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.oauth2 import id_token
from google.auth.transport.requests import Request as GoogleRequest
from .config import Environment, CATEGORIES
from .infrastructure import FirestoreStore, ObjectStorage, TaskDispatcher, SecretStore, FirebaseIdentity, now
from .models import Settings, UserCreate, UserPatch, PasswordChange, CategoryCreate, GarmentPatch, TryOnRequest, ShareRequest, ShareDownload, Credential, TaskBody
from .models import UserResponse, CategoryResponse, GarmentResponse, UploadResponse, JobResponse, ShareResponse, SettingsResponse, EstimateRequest, EstimateResponse
from .models import CatalogLabelCreate, CatalogLabelResponse, CatalogLabelsResponse
from .jobs import JobService, owned, public_job, TERMINAL
from .images import normalize_image, InvalidImage
from .providers import ProviderRegistry, estimate


@dataclass
class Services:
    env: Environment
    store: object
    objects: object
    tasks: object
    identity: object
    secrets: object
    providers: object
    jobs: JobService


@lru_cache
def get_services() -> Services:
    env = Environment()
    store, objects, tasks, identity, secret_store = FirestoreStore(env), ObjectStorage(env), TaskDispatcher(env), FirebaseIdentity(env), SecretStore(env)
    providers = ProviderRegistry(env, secret_store)
    return Services(env, store, objects, tasks, identity, secret_store, providers, JobService(store, objects, tasks, providers))


app = FastAPI(title='StyleReel API', version='1.0.0', docs_url=None, redoc_url=None, openapi_url='/api/openapi.json')
env = Environment()
if env.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=list(env.cors_origins), allow_credentials=False, allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])
bearer = HTTPBearer(auto_error=False)
MAX_GARMENT_PHOTOS = 6
MAX_CATALOG_UPLOAD_BYTES = 28 * 1024 * 1024
LABEL_COLLECTIONS = {'store': 'catalog_stores', 'brand': 'catalog_brands'}


@app.middleware('http')
async def security_headers(request: Request, call_next):
    # Reject oversized requests before multipart parser buffers them.
    length = request.headers.get('content-length')
    photo_count = MAX_GARMENT_PHOTOS if request.method == 'POST' and request.url.path in {'/api/garments', '/api/admin/garments'} else 1
    request_limit = min(env.max_upload_bytes * photo_count, MAX_CATALOG_UPLOAD_BYTES) + 1024 * 1024
    if length and (not length.isdigit() or int(length) > request_limit):
        return Response('Request exceeds the upload size limit.', status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=()'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    if request.url.path.startswith(('/api', '/share', '/internal')):
        response.headers['Cache-Control'] = 'no-store'
    # Firebase/reCAPTCHA inject scripts and styles; permit only their documented hosts.
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://www.google.com https://www.gstatic.com https://www.recaptcha.net https://apis.google.com; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data: https://www.gstatic.com; connect-src 'self' https://*.googleapis.com https://*.firebaseapp.com https://*.google.com" + (' http://localhost:* http://127.0.0.1:*' if env.emulator else '') + "; frame-src https://www.google.com https://www.recaptcha.net https://*.firebaseapp.com; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response


@app.exception_handler(InvalidImage)
async def image_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail': str(exc)}, status_code=400)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    import logging
    logging.getLogger('stylereel').error('Request failed: path=%s type=%s', request.url.path, type(exc).__name__)
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail': 'The operation could not complete. Please try again.'}, status_code=503)


def authenticated(credentials: HTTPAuthorizationCredentials = Depends(bearer), services: Services = Depends(get_services)):
    if not credentials:
        raise HTTPException(401, 'Sign in to continue.', headers={'WWW-Authenticate': 'Bearer'})
    try:
        claims = services.identity.verify(credentials.credentials)
    except Exception:
        raise HTTPException(401, 'Your session expired. Sign in again.')
    user = services.store.get('users', claims['uid'])
    if not user or not user.get('active'):
        raise HTTPException(403, 'This account has been deactivated or is not registered.')
    return {**user, '_claims': claims}


def ready_user(user=Depends(authenticated)):
    if user.get('must_change_password'):
        raise HTTPException(403, 'Change your initial password before continuing.')
    return user


def admin(user=Depends(ready_user)):
    if user.get('role') != 'admin':
        raise HTTPException(403, 'Administrator access required.')
    return user


def view_user(value):
    return {k: value[k] for k in ['id', 'email', 'role', 'active', 'must_change_password', 'created_at'] if k in value}


def image_response(data):
    return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})


def settings_response(services):
    settings = services.jobs.settings()
    return {**settings.model_dump(), 'providers': services.providers.info(settings), 'processing_notice': 'Photos are sent to the selected AI provider. Google global processing can occur outside India. Application source photos are deleted when generation finishes; server results expire within 24 hours. Provider retention is governed separately by its terms.'}


def view_garment(g):
    keys = g.get('image_keys') or [g['image_key']]
    return {k: v for k, v in g.items() if k not in {'image_key', 'image_keys', 'thumbnail_key'}} | {
        'image_url': f'/api/garments/{g["id"]}/image',
        'image_urls': [f'/api/garments/{g["id"]}/photos/{index}' for index in range(len(keys))],
        'thumbnail_url': f'/api/garments/{g["id"]}/thumbnail',
    }


@app.get('/healthz')
@app.get('/api/health')
def health():
    return {'status': 'ok', 'application': 'StyleReel'}


@app.get('/api/docs', include_in_schema=False)
def api_contract():
    # The generated contract works with the application's strict script policy.
    return RedirectResponse('/api/openapi.json')


@app.get('/api/config')
def public_config():
    value = {'application_name': 'StyleReel', 'firebase': {'apiKey': env.firebase_api_key, 'authDomain': env.firebase_auth_domain, 'projectId': env.project, 'appId': env.firebase_app_id}, 'captcha_mode': 'identity_platform_enterprise_enforced'}
    if env.emulator:
        value['auth_emulator_url'] = 'http://' + os.environ['FIREBASE_AUTH_EMULATOR_HOST']
        value['captcha_mode'] = 'emulator_not_enforced'
    return value


@app.get('/api/me', response_model=UserResponse)
def me(user=Depends(authenticated)):
    return view_user(user)


@app.post('/api/me/password')
def change_password(body: PasswordChange, user=Depends(authenticated), services: Services = Depends(get_services)):
    auth_time = user['_claims'].get('auth_time', 0)
    if now().timestamp() - auth_time > 300:
        raise HTTPException(401, 'Sign in again before changing your password.')
    services.identity.update(user['id'], password=body.password)
    services.identity.revoke(user['id'])
    record = {k: v for k, v in user.items() if k != '_claims'}
    services.store.set('users', user['id'], {**record, 'must_change_password': False})
    return {'success': True, 'reauthenticate': True}


@app.get('/api/me/gallery-key')
def gallery_key(user=Depends(ready_user), services: Services = Depends(get_services)):
    def get_key(tx):
        value = tx.get('users', user['id'])
        if not value.get('gallery_key'):
            value['gallery_key'] = base64.b64encode(secrets.token_bytes(32)).decode()
            tx.set('users', user['id'], value)
        return value['gallery_key']
    return {'key': services.store.atomic(get_key)}


@app.get('/api/settings', response_model=SettingsResponse)
def settings(user=Depends(ready_user), services: Services = Depends(get_services)):
    return settings_response(services)


@app.get('/api/users', response_model=list[UserResponse])
def users(user=Depends(admin), services: Services = Depends(get_services)):
    return [view_user(u) for u in services.store.list('users')]


@app.post('/api/users', status_code=201, response_model=UserResponse)
def create_user(body: UserCreate, user=Depends(admin), services: Services = Depends(get_services)):
    uid = services.identity.create(body.email, body.password)
    value = {'id': uid, 'email': body.email, 'role': body.role, 'active': True, 'must_change_password': True, 'created_at': now()}
    try:
        services.store.set('users', uid, value)
    except Exception:
        services.identity.delete(uid)
        raise
    return view_user(value)


@app.patch('/api/users/{uid}', response_model=UserResponse)
def update_user(uid: str, body: UserPatch, user=Depends(admin), services: Services = Depends(get_services)):
    if uid == user['id'] and (body.active is False or body.role == 'user'):
        raise HTTPException(400, 'An administrator cannot deactivate or demote their own account.')
    record = services.store.get('users', uid)
    if not record:
        raise HTTPException(404, 'User not found.')
    changes = body.model_dump(exclude_none=True)
    if body.active is False:
        # Backend state changes first, denying existing sessions even if Firebase update fails.
        services.store.set('users', uid, {**record, **changes})
        services.identity.update(uid, disabled=True)
        services.identity.revoke(uid)
    else:
        if body.active is True:
            services.identity.update(uid, disabled=False)
        services.identity.revoke(uid)
        services.store.set('users', uid, {**record, **changes})
    return view_user({**record, **changes})


def remove_private_data(uid, services):
    for job in services.store.list('generation_jobs', {'user_id': uid}):
        if job['status'] not in TERMINAL:
            services.jobs.finish(job, 'failed', 'Account or result was deleted.')
        for key in ['result_key', 'intermediate_key', 'source_key']:
            if job.get(key):
                services.objects.delete('temp', job[key])
        services.jobs._update(job['id'], result_deleted=True)
    for upload in services.store.list('uploads', {'user_id': uid}):
        services.objects.delete('temp', upload['key'])
        services.store.delete('uploads', upload['id'])
    for share in services.store.list('shares', {'user_id': uid}):
        services.objects.delete('temp', share['key'])
        services.store.delete('shares', share['id'])


@app.delete('/api/users/{uid}')
def delete_user(uid: str, user=Depends(admin), services: Services = Depends(get_services)):
    if uid == user['id']:
        raise HTTPException(400, 'An administrator cannot delete their own account.')
    record = services.store.get('users', uid)
    if not record:
        raise HTTPException(404, 'User not found.')
    services.store.set('users', uid, {**record, 'active': False})
    services.identity.revoke(uid)
    remove_private_data(uid, services)
    services.identity.delete(uid)
    services.store.delete('users', uid)
    return {'success': True}


@app.post('/api/users/{uid}/reset')
def reset_user(uid: str, user=Depends(admin), services: Services = Depends(get_services)):
    record = services.store.get('users', uid)
    if not record:
        raise HTTPException(404, 'User not found.')
    services.identity.revoke(uid)
    return {'reset_link': services.identity.reset_link(record['email'])}


@app.get('/api/categories', response_model=list[CategoryResponse])
def categories(user=Depends(ready_user), services: Services = Depends(get_services)):
    return services.store.list('categories') or CATEGORIES


@app.post('/api/categories', status_code=201, response_model=CategoryResponse)
@app.post('/api/admin/categories', status_code=201, response_model=CategoryResponse)
def create_category(body: CategoryCreate, user=Depends(admin), services: Services = Depends(get_services)):
    body.name = body.name.strip()
    if not body.name:
        raise HTTPException(400, 'Enter a type label.')
    if not body.id:
        import re
        body.id = re.sub(r'[^a-z0-9]+', '-', body.name.lower()).strip('-')[:50]
        if len(body.id) < 2 or not body.id[0].isalpha():
            body.id = 'type-' + hashlib.sha256(body.name.casefold().encode()).hexdigest()[:24]
    if services.store.get('categories', body.id):
        raise HTTPException(409, 'Category already exists.')
    services.store.set('categories', body.id, body.model_dump())
    return body


@app.get('/api/catalog/labels', response_model=CatalogLabelsResponse)
def catalog_labels(user=Depends(ready_user), services: Services = Depends(get_services)):
    return {
        kind + 's': sorted(services.store.list(collection), key=lambda label: label['name'].casefold())
        for kind, collection in LABEL_COLLECTIONS.items()
    }


@app.post('/api/admin/catalog/labels', status_code=201, response_model=CatalogLabelResponse)
def create_catalog_label(body: CatalogLabelCreate, user=Depends(admin), services: Services = Depends(get_services)):
    # A deterministic ID and transaction reuse the same label under concurrent creation.
    identifier = body.kind + '-' + hashlib.sha256(body.name.casefold().encode()).hexdigest()[:24]
    collection = LABEL_COLLECTIONS[body.kind]

    def create(tx):
        existing = tx.get(collection, identifier)
        if existing:
            return existing
        value = {'id': identifier, 'name': body.name}
        tx.set(collection, identifier, value)
        return value

    return services.store.atomic(create)


def validate_garment_labels(store_id, brand_id, services):
    for kind, identifier in [('store', store_id), ('brand', brand_id)]:
        if identifier and not services.store.get(LABEL_COLLECTIONS[kind], identifier):
            raise HTTPException(400, f'Unknown {kind} label.')


@app.get('/api/garments', response_model=list[GarmentResponse])
def garments(user=Depends(ready_user), services: Services = Depends(get_services)):
    filters = None if user['role'] == 'admin' else {'active': True}
    return [view_garment(g) for g in services.store.list('garments', filters)]


@app.post('/api/garments', status_code=201, response_model=GarmentResponse)
@app.post('/api/admin/garments', status_code=201, response_model=GarmentResponse)
def create_garment(file: UploadFile | None = File(None), files: list[UploadFile] | None = File(None), name: str = Form(..., min_length=1, max_length=120), description: str = Form('', max_length=2000), category_id: str = Form(...), store_id: str | None = Form(None, max_length=80), brand_id: str | None = Form(None, max_length=80), source_url: str = Form('', max_length=2000), license: str = Form('', max_length=200), attribution: str = Form('', max_length=1000), active: bool = Form(True), user=Depends(admin), services: Services = Depends(get_services)):
    if not services.store.get('categories', category_id):
        raise HTTPException(400, 'Unknown category.')
    store_id, brand_id = store_id or None, brand_id or None
    validate_garment_labels(store_id, brand_id, services)
    if source_url:
        from urllib.parse import urlsplit
        parsed = urlsplit(source_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(400, 'Source URL must be an HTTP or HTTPS URL without credentials.')
    photos = ([file] if file else []) + (files or [])
    if not 1 <= len(photos) <= MAX_GARMENT_PHOTOS:
        raise HTTPException(400, f'Provide between 1 and {MAX_GARMENT_PHOTOS} garment photos.')
    # Decode every reference before writing any objects; one bad photo cannot leave a partial garment.
    images, total_bytes = [], 0
    for photo in photos:
        contents = photo.file.read(services.env.max_upload_bytes + 1)
        total_bytes += len(contents)
        if total_bytes > MAX_CATALOG_UPLOAD_BYTES:
            raise HTTPException(413, 'The dress photos exceed the 28 MB combined upload limit.')
        images.append(normalize_image(contents, services.env.max_upload_bytes))
    identifier = uuid.uuid4().hex
    key, thumb = f'garments/{identifier}.jpg', f'thumbnails/{identifier}.jpg'
    keys = [key] + [f'garments/{identifier}/{index}.jpg' for index in range(1, len(images))]
    value = {'id': identifier, 'name': name, 'description': description, 'category_id': category_id, 'store_id': store_id, 'brand_id': brand_id, 'active': active, 'source_url': source_url, 'license': license, 'attribution': attribution, 'image_key': key, 'image_keys': keys, 'thumbnail_key': thumb, 'created_at': now()}
    written = []
    try:
        for photo_key, image in zip(keys, images):
            services.objects.put('catalog', photo_key, image.data)
            written.append(photo_key)
        services.objects.put('catalog', thumb, images[0].thumbnail)
        written.append(thumb)
        services.store.set('garments', identifier, value)
    except Exception:
        for photo_key in written:
            try:
                services.objects.delete('catalog', photo_key)
            except Exception:
                pass
        raise
    return view_garment(value)


@app.patch('/api/garments/{identifier}', response_model=GarmentResponse)
def patch_garment(identifier: str, body: GarmentPatch, user=Depends(admin), services: Services = Depends(get_services)):
    garment = services.store.get('garments', identifier)
    if not garment:
        raise HTTPException(404, 'Garment not found.')
    if body.category_id and not services.store.get('categories', body.category_id):
        raise HTTPException(400, 'Unknown category.')
    validate_garment_labels(body.store_id, body.brand_id, services)
    changes = body.model_dump(exclude_unset=True)
    # Explicit null clears optional labels; keep legacy fields' null behavior unchanged.
    garment.update({k: v for k, v in changes.items() if v is not None or k in {'store_id', 'brand_id'}})
    services.store.set('garments', identifier, garment)
    return view_garment(garment)


@app.delete('/api/garments/{identifier}')
def delete_garment(identifier: str, user=Depends(admin), services: Services = Depends(get_services)):
    garment = services.store.get('garments', identifier)
    if not garment:
        raise HTTPException(404, 'Garment not found.')
    services.store.delete('garments', identifier)
    for key in set((garment.get('image_keys') or [garment['image_key']]) + [garment['image_key'], garment['thumbnail_key']]):
        services.objects.delete('catalog', key)
    return {'success': True}


@app.get('/api/garments/{identifier}/photos/{index}')
def garment_photo(identifier: str, index: int, user=Depends(ready_user), services: Services = Depends(get_services)):
    garment = services.store.get('garments', identifier)
    if not garment or (not garment.get('active') and user['role'] != 'admin'):
        raise HTTPException(404, 'Garment not found.')
    keys = garment.get('image_keys') or [garment['image_key']]
    if index < 0 or index >= len(keys):
        raise HTTPException(404, 'Garment photo not found.')
    return image_response(services.objects.get('catalog', keys[index]))


@app.get('/api/garments/{identifier}/{variant}')
def garment_image(identifier: str, variant: str, user=Depends(ready_user), services: Services = Depends(get_services)):
    garment = services.store.get('garments', identifier)
    if not garment or (not garment.get('active') and user['role'] != 'admin') or variant not in {'image', 'thumbnail'}:
        raise HTTPException(404, 'Garment not found.')
    return image_response(services.objects.get('catalog', garment['image_key' if variant == 'image' else 'thumbnail_key']))


@app.post('/api/uploads', status_code=201, response_model=UploadResponse)
def upload_photo(file: UploadFile = File(...), consent: str = Form(...), purpose: str = Form(...), user=Depends(ready_user), services: Services = Depends(get_services)):
    if consent != 'true' or purpose not in {'person', 'holding', 'share'}:
        raise HTTPException(400, 'Consent and a valid photo purpose are required.')
    original = file.file.read(services.env.max_upload_bytes + 1)
    image = normalize_image(original, services.env.max_upload_bytes)
    import re
    original_filename = re.sub(r'[^A-Za-z0-9._ -]', '_', Path(file.filename or 'photo').name)[:120]
    # Shared transactional upload throttle also limits storage abuse, independently of AI calls.
    def upload_quota(tx):
        value = tx.get('upload_quotas', user['id']) or {}
        day = now().strftime('%Y-%m-%d')
        count = value.get('count', 0) if value.get('day') == day else 0
        if count >= 100:
            raise HTTPException(429, 'Daily upload limit reached.', headers={'Retry-After': '3600'})
        tx.set('upload_quotas', user['id'], {'day': day, 'count': count + 1})
    services.store.atomic(upload_quota)
    identifier = uuid.uuid4().hex
    key = f'uploads/{user["id"]}/{identifier}.jpg'
    services.objects.put('temp', key, image.data)
    value = {'id': identifier, 'key': key, 'user_id': user['id'], 'purpose': purpose, 'consent': True, 'created_at': now(), 'expires_at': now() + timedelta(hours=1), 'width': image.width, 'height': image.height, 'size_bytes': len(image.data), 'deleted': False, 'cleanup_pending': True}
    services.store.set('uploads', identifier, value)
    services.jobs.event(user['id'], 'upload', size_bytes=len(image.data), original_size_bytes=len(original), filename=original_filename, width=image.width, height=image.height, workflow=purpose)
    return {k: value[k] for k in ['id', 'width', 'height', 'size_bytes']} | {'image_url': f'/api/uploads/{identifier}/image'}


@app.get('/api/uploads/{identifier}/image')
def upload_image(identifier: str, user=Depends(ready_user), services: Services = Depends(get_services)):
    upload = owned(services.store, 'uploads', identifier, user['id'])
    if upload.get('deleted') or upload['expires_at'] <= now():
        raise HTTPException(410, 'Photo expired.')
    return image_response(services.objects.get('temp', upload['key']))


@app.post('/api/tryon/estimate', response_model=EstimateResponse)
def estimate_job(body: EstimateRequest, user=Depends(ready_user), services: Services = Depends(get_services)):
    workflow = body.workflow
    reference_count = 0
    if workflow == 'catalog':
        for identifier in body.garment_ids:
            garment = services.store.get('garments', identifier)
            if not garment or not garment.get('active'):
                raise HTTPException(400, 'Choose an available garment.')
            reference_count += len(garment.get('image_keys') or [garment['image_key']])
    calls, cost = estimate(services.jobs.settings(), len(body.garment_ids) or 1, workflow, reference_count=reference_count)
    return {'expected_calls': calls, 'estimated_cost_usd': cost}


@app.post('/api/tryon/catalog', status_code=202, response_model=JobResponse)
def catalog_tryon(body: TryOnRequest, user=Depends(ready_user), services: Services = Depends(get_services)):
    return public_job(services.jobs.submit(user['id'], body, 'catalog'))


@app.post('/api/tryon/holding-garment', status_code=202, response_model=JobResponse)
def holding_tryon(body: TryOnRequest, user=Depends(ready_user), services: Services = Depends(get_services)):
    return public_job(services.jobs.submit(user['id'], body, 'holding'))


@app.get('/api/tryon/jobs/{identifier}', response_model=JobResponse)
def job_status(identifier: str, user=Depends(ready_user), services: Services = Depends(get_services)):
    return public_job(owned(services.store, 'generation_jobs', identifier, user['id']))


@app.get('/api/tryon/results/{identifier}')
def result_image(identifier: str, user=Depends(ready_user), services: Services = Depends(get_services)):
    job = owned(services.store, 'generation_jobs', identifier, user['id'])
    if not job.get('result_key') or job.get('result_deleted') or job['result_expires_at'] <= now():
        raise HTTPException(410, 'Result expired or was deleted. Local gallery results are available on the device that saved them.')
    return image_response(services.objects.get('temp', job['result_key']))


@app.delete('/api/tryon/results/{identifier}')
def delete_result(identifier: str, user=Depends(ready_user), services: Services = Depends(get_services)):
    job = owned(services.store, 'generation_jobs', identifier, user['id'])
    services.jobs._update(identifier, result_deleted=True)
    if job.get('result_key'):
        services.objects.delete('temp', job['result_key'])
    for share in services.store.list('shares', {'result_id': identifier}):
        services.objects.delete('temp', share['key'])
        services.store.delete('shares', share['id'])
    return {'success': True}


@app.post('/api/shares', status_code=201, response_model=ShareResponse)
def share_result(body: ShareRequest, user=Depends(ready_user), services: Services = Depends(get_services)):
    if bool(body.result_id) == bool(body.upload_id):
        raise HTTPException(400, 'Choose one result or local-gallery upload to share.')
    if body.result_id:
        job = owned(services.store, 'generation_jobs', body.result_id, user['id'])
        if not job.get('result_key') or job.get('result_deleted') or job['result_expires_at'] <= now():
            raise HTTPException(410, 'The result expired. Share its locally saved image instead.')
        source_key = job['result_key']
    else:
        upload = owned(services.store, 'uploads', body.upload_id, user['id'])
        if upload['purpose'] != 'share' or upload.get('deleted') or upload['expires_at'] <= now():
            raise HTTPException(400, 'Upload a local result for sharing first.')
        source_key = upload['key']
    identifier, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
    key = f'shares/{user["id"]}/{identifier}.jpg'
    services.objects.put('temp', key, services.objects.get('temp', source_key))
    expiry = now() + timedelta(minutes=15)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    services.store.set('shares', token_hash, {'id': token_hash, 'public_id': identifier, 'user_id': user['id'], 'result_id': body.result_id, 'key': key, 'expires_at': expiry, 'created_at': now(), 'revoked': False})
    if body.upload_id:
        services.objects.delete('temp', source_key)
        services.store.set('uploads', upload['id'], {**upload, 'deleted': True, 'cleanup_pending': False})
    return {'id': token_hash, 'url': f'{services.env.service_url}/share#{token}', 'expires_at': expiry}


@app.post('/api/shares/download')
def download_share(body: ShareDownload, services: Services = Depends(get_services)):
    share = services.store.get('shares', hashlib.sha256(body.token.encode()).hexdigest())
    if not share or share.get('revoked') or share['expires_at'] <= now():
        raise HTTPException(410, 'This shared image expired or was revoked.')
    owner = services.store.get('users', share['user_id'])
    if not owner or not owner.get('active'):
        raise HTTPException(410, 'This shared image is unavailable.')
    return image_response(services.objects.get('temp', share['key']))


@app.delete('/api/shares/{identifier}')
def revoke_share(identifier: str, user=Depends(ready_user), services: Services = Depends(get_services)):
    share = owned(services.store, 'shares', identifier, user['id'])
    services.store.set('shares', identifier, {**share, 'revoked': True})
    services.objects.delete('temp', share['key'])
    return {'success': True}


@app.get('/api/admin/settings', response_model=SettingsResponse)
def admin_settings(user=Depends(admin), services: Services = Depends(get_services)):
    return settings_response(services)


@app.put('/api/admin/settings', response_model=SettingsResponse)
def put_settings(body: Settings, user=Depends(admin), services: Services = Depends(get_services)):
    provider = next(p for p in services.providers.info(body) if p['id'] == body.ai.provider)
    if body.ai.model not in provider['models']:
        raise HTTPException(400, 'The chosen model is not supported by this provider.')
    existing = services.jobs.settings()
    for field in ['pruna_terms_confirmed', 'fashn_credit_usd', 'pruna_unit_usd']:
        if field not in body.model_fields_set:
            setattr(body, field, getattr(existing, field))
    services.store.set('application_settings', 'main', body.model_dump())
    return settings_response(services)


@app.post('/api/admin/providers/{identifier}/test')
def provider_readiness(identifier: str, user=Depends(admin), services: Services = Depends(get_services)):
    info = next((p for p in services.providers.info(services.jobs.settings()) if p['id'] == identifier), None)
    if not info:
        raise HTTPException(404, 'Provider not found.')
    check = {'status': info['status'], 'message': 'Provider unavailable. Configure credentials and applicable privacy terms first.'}
    if info['configured'] and info['status'] != 'terms_unconfirmed':
        try:
            adapter = services.providers.get(identifier)
            check = adapter.readiness(services.jobs.settings()) if hasattr(adapter, 'readiness') else {'status': 'connectivity_unverified', 'message': 'This provider has no verified nonbillable readiness endpoint. A real generation is required.'}
        except Exception:
            check = {'status': 'connectivity_failed', 'message': 'The authenticated provider metadata check failed. Verify credentials, model access and API configuration.'}
    services.store.set('provider_checks', identifier, {'checked_at': now(), **check})
    return {**info, **check, 'inference_verified': False}


@app.put('/api/admin/providers/{identifier}/credential')
def put_credential(identifier: str, body: Credential, user=Depends(admin), services: Services = Depends(get_services)):
    if identifier not in {'fashn', 'pruna'}:
        raise HTTPException(400, 'Google uses service-account credentials.')
    services.secrets.write(f'{identifier}-api-key', body.api_key)
    return {'success': True}


def filtered_events(services, start_date=None, end_date=None, user_id=None, provider=None, model=None, status=None, workflow=None):
    filters = {k: v for k, v in {'user_id': user_id, 'provider': provider, 'model': model, 'status': status, 'workflow': workflow}.items() if v}
    events = services.store.list('usage_events', filters)
    return sorted([e for e in events if (not start_date or e['created_at'].strftime('%Y-%m-%d') >= start_date) and (not end_date or e['created_at'].strftime('%Y-%m-%d') <= end_date)], key=lambda e: (e['created_at'], e['id']), reverse=True)


@app.get('/api/admin/usage')
def usage(start_date: str | None = None, end_date: str | None = None, user_id: str | None = None, provider: str | None = None, model: str | None = None, status: str | None = None, workflow: str | None = None, cursor: str | None = None, limit: int = 50, user=Depends(admin), services: Services = Depends(get_services)):
    events = filtered_events(services, start_date, end_date, user_id, provider, model, status, workflow)
    if cursor:
        position = next((i for i, e in enumerate(events) if e['id'] == cursor), None)
        if position is None:
            raise HTTPException(400, 'Unknown history cursor.')
        events = events[position + 1:]
    limit = max(1, min(100, limit))
    return {'items': events[:limit], 'next_cursor': events[limit - 1]['id'] if len(events) > limit else None}


@app.get('/api/admin/analytics')
def analytics(start_date: str | None = None, end_date: str | None = None, user_id: str | None = None, provider: str | None = None, model: str | None = None, status: str | None = None, workflow: str | None = None, user=Depends(admin), services: Services = Depends(get_services)):
    events = filtered_events(services, start_date, end_date, user_id, provider, model, status, workflow)
    completed = [e for e in events if e['event'] == 'completed']
    uploads = [e for e in events if e['event'] == 'upload']
    calls = [e for e in events if e['event'] == 'provider_call']
    days = {}
    for event in events:
        day = event['created_at'].strftime('%Y-%m-%d')
        value = days.setdefault(day, {'date': day, 'generations': 0, 'cost_usd': 0})
        value['generations'] += int(event['event'] == 'generation')
        value['cost_usd'] += event.get('estimated_cost_usd', 0) if event['event'] == 'completed' else 0
    total = {'users': len(services.store.list('users')), 'uploads': len(uploads), 'generations': sum(e['event'] == 'generation' for e in events), 'succeeded': sum(e.get('status') == 'succeeded' for e in completed), 'failed': sum(e.get('status') in {'failed', 'unknown'} for e in completed), 'upload_bytes': sum(e.get('size_bytes', 0) for e in uploads), 'estimated_cost_usd': sum(e.get('estimated_cost_usd', 0) for e in completed), 'avg_duration_seconds': sum(e.get('duration_seconds', 0) for e in completed) / max(1, len(completed))}
    budget = services.store.get('budget_months', now().strftime('%Y-%m')) or {'reserved': 0, 'spent': 0}
    return {'totals': total, 'daily': sorted(days.values(), key=lambda d: d['date']), 'by_provider': [{'name': k, 'calls': v} for k, v in Counter(e.get('provider', 'unknown') for e in calls).items()], 'by_model': [{'name': k, 'calls': v} for k, v in Counter(e.get('model', 'unknown') for e in calls).items()], 'monthly_budget': budget}


def internal_auth(credentials: HTTPAuthorizationCredentials = Depends(bearer), services: Services = Depends(get_services)):
    if not credentials or not services.env.service_url or not services.env.task_account:
        raise HTTPException(401, 'Task authentication required.')
    try:
        claims = id_token.verify_oauth2_token(credentials.credentials, GoogleRequest(), audience=services.env.service_url)
    except Exception:
        raise HTTPException(401, 'Task token invalid.')
    if claims.get('email') != services.env.task_account or claims.get('email_verified') is not True:
        raise HTTPException(403, 'Task identity rejected.')


@app.post('/internal/tasks', dependencies=[Depends(internal_auth)])
def task(body: TaskBody, services: Services = Depends(get_services)):
    services.jobs.process(body.job_id)
    return {'success': True}


@app.post('/internal/maintenance', dependencies=[Depends(internal_auth)])
def maintenance(services: Services = Depends(get_services)):
    return services.jobs.maintenance()


@app.get('/{path:path}', include_in_schema=False)
def frontend(path: str):
    if path.startswith(('api/', 'internal/')):
        raise HTTPException(404, 'Endpoint not found.')
    root = Path(env.frontend_dir).resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(404, 'Not found.')
    if candidate.is_file():
        return FileResponse(candidate)
    index = root / 'index.html'
    if index.is_file():
        return FileResponse(index)
    return Response('StyleReel frontend is not built yet.', status_code=503)


@app.delete('/api/uploads/{identifier}')
def delete_upload(identifier: str, user=Depends(ready_user), services: Services = Depends(get_services)):
    upload = owned(services.store, 'uploads', identifier, user['id'])
    if upload.get('consumed'):
        raise HTTPException(409, 'This photo belongs to a generation in progress. Delete the result when it finishes.')
    services.store.set('uploads', identifier, {**upload, 'deleted': True})
    services.objects.delete('temp', upload['key'])
    services.store.set('uploads', identifier, {**upload, 'deleted': True, 'cleanup_pending': False})
    return {'success': True}
