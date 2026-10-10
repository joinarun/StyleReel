"""Idempotently seed CC0 catalog assets through the same image normalization as uploads."""
import json
import pathlib
from app.config import Environment
from app.infrastructure import FirestoreStore, ObjectStorage, now
from app.images import normalize_image

root = pathlib.Path(__file__).resolve().parents[1]
env = Environment()
store, objects = FirestoreStore(env), ObjectStorage(env)
for entry in json.loads((root / 'sample_assets/manifest.json').read_text()):
    if store.get('garments', entry['id']):
        print('Existing sample:', entry['name'])
        continue
    image = normalize_image((root / 'sample_assets' / entry['file']).read_bytes())
    key, thumb = 'garments/' + entry['id'] + '.jpg', 'thumbnails/' + entry['id'] + '.jpg'
    objects.put('catalog', key, image.data)
    objects.put('catalog', thumb, image.thumbnail)
    store.set('garments', entry['id'], {**{k: v for k, v in entry.items() if k != 'file'},
                                      'image_key': key, 'thumbnail_key': thumb, 'active': True, 'created_at': now()})
    print('Seeded:', entry['name'])
