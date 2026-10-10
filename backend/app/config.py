from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class Environment:
    project: str = field(default_factory=lambda: os.getenv('GOOGLE_CLOUD_PROJECT', 'virtualtryon-511016'))
    catalog_bucket: str = field(default_factory=lambda: os.getenv('STORAGE_CATALOG_BUCKET', ''))
    temp_bucket: str = field(default_factory=lambda: os.getenv('STORAGE_TEMP_BUCKET', ''))
    queue: str = field(default_factory=lambda: os.getenv('TASKS_QUEUE', 'stylereel-generations'))
    location: str = field(default_factory=lambda: os.getenv('TASKS_LOCATION', 'asia-south1'))
    vertex_location: str = field(default_factory=lambda: os.getenv('VERTEX_LOCATION', 'global'))
    service_url: str = field(default_factory=lambda: os.getenv('SERVICE_URL', '').rstrip('/'))
    task_account: str = field(default_factory=lambda: os.getenv('TASKS_SERVICE_ACCOUNT', ''))
    secret_prefix: str = field(default_factory=lambda: os.getenv('SECRET_PREFIX', 'stylereel'))
    firebase_api_key: str = field(default_factory=lambda: os.getenv('FIREBASE_API_KEY', ''))
    firebase_auth_domain: str = field(default_factory=lambda: os.getenv('FIREBASE_AUTH_DOMAIN', 'virtualtryon-511016.firebaseapp.com'))
    firebase_app_id: str = field(default_factory=lambda: os.getenv('FIREBASE_APP_ID', ''))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv('MAX_UPLOAD_BYTES', str(12 * 1024 * 1024))))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip() for x in os.getenv('CORS_ORIGINS', '').split(',') if x.strip()))
    frontend_dir: str = field(default_factory=lambda: os.getenv('FRONTEND_DIST', '../frontend/dist'))
    emulator: bool = field(default_factory=lambda: bool(os.getenv('FIREBASE_AUTH_EMULATOR_HOST')))


CATEGORIES = [
    {'id': key, 'name': name, 'slot': slot, 'experimental': experimental}
    for key, name, slot, experimental in [
        ('shirts', 'Shirts', 'upper', False), ('tshirts', 'T-shirts', 'upper', False),
        ('pants', 'Pants', 'lower', False), ('trousers', 'Trousers', 'lower', False),
        ('tops', 'Tops', 'upper', False), ('skirts', 'Skirts', 'lower', False),
        ('sarees', 'Sarees', 'full', True), ('salwar', 'Chudidhars / Salwar suits', 'full', True),
        ('dresses', 'Dresses', 'full', False),
    ]
]
