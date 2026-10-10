"""Explicitly remove only StyleReel resources, keeping the existing GCP project and billing intact."""
import argparse
import json
import pathlib
from cloud_setup import gc

parser = argparse.ArgumentParser()
parser.add_argument('--confirm-delete-stylereel', action='store_true', required=True)
args = parser.parse_args()
config = json.loads((pathlib.Path(__file__).resolve().parents[1] / '.deployment/config.json').read_text())
p, r = config['project'], config['region']
gc('scheduler', 'jobs', 'delete', 'stylereel-maintenance', '--project=' + p, '--location=' + r, check=False)
gc('tasks', 'queues', 'delete', 'stylereel-generations', '--project=' + p, '--location=' + r, check=False)
gc('run', 'services', 'delete', 'stylereel', '--project=' + p, '--region=' + r, check=False)
for name in ['catalog', 'temp', 'build-source']:
    gc('storage', 'rm', '--recursive', 'gs://' + p + '-stylereel-' + name, '--project=' + p, check=False)
gc('artifacts', 'repositories', 'delete', 'stylereel', '--project=' + p, '--location=' + r, check=False)
for name in ['stylereel-fashn-api-key', 'stylereel-pruna-api-key', 'stylereel-bootstrap-password']:
    gc('secrets', 'delete', name, '--project=' + p, check=False)
for account in ['stylereel-runtime', 'stylereel-dispatch', 'stylereel-build']:
    gc('iam', 'service-accounts', 'delete', account + '@' + p + '.iam.gserviceaccount.com', '--project=' + p, check=False)
print('Compute/storage/secrets removed. Review Firestore records and Firebase accounts manually; shared project data was preserved.')
