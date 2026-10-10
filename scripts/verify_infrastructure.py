"""Save non-secret resource configuration and production security evidence."""
import concurrent.futures
import json
import pathlib
import subprocess
from cloud_setup import api

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / '.deployment/config.json').read_text())
P, R = CONFIG['project'], CONFIG['region']
COMMANDS = {
    'service': ['run', 'services', 'describe', 'stylereel', '--region=' + R],
    'service_iam': ['run', 'services', 'get-iam-policy', 'stylereel', '--region=' + R],
    'runtime_account_iam': ['iam', 'service-accounts', 'get-iam-policy', CONFIG['runtime_account']],
    'secret_containers': ['secrets', 'list', '--filter=name:stylereel-'],
    'database': ['firestore', 'databases', 'describe', '--database=(default)'],
    'catalog_bucket': ['storage', 'buckets', 'describe', 'gs://' + CONFIG['catalog_bucket']],
    'temporary_bucket': ['storage', 'buckets', 'describe', 'gs://' + CONFIG['temp_bucket']],
    'queue': ['tasks', 'queues', 'describe', 'stylereel-generations', '--location=' + R],
    'scheduler': ['scheduler', 'jobs', 'describe', 'stylereel-maintenance', '--location=' + R],
    'repository': ['artifacts', 'repositories', 'describe', 'stylereel', '--location=' + R],
    'maintenance_requests': ['logging', 'read', 'resource.type="cloud_run_revision" AND httpRequest.requestUrl:"/internal/maintenance"', '--limit=5'],
}


def read(item):
    name, args = item
    value = subprocess.run(['gcloud', *args, '--project=' + P, '--format=json'], check=True, capture_output=True, text=True)
    return name, json.loads(value.stdout)


def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        inventory = dict(pool.map(read, COMMANDS.items()))
    # Keep only explicit authentication fields: the admin config also includes private password hash parameters.
    identity = api('GET', 'https://identitytoolkit.googleapis.com/admin/v2/projects/' + P + '/config')
    inventory['identity'] = {'email_password': identity.get('signIn', {}).get('email'), 'public_user_permissions': identity.get('client', {}).get('permissions'), 'authorized_domains': identity.get('authorizedDomains'), 'recaptcha': identity.get('recaptchaConfig')}
    inventory['project'], inventory['service_url'] = P, CONFIG['service_url']
    (ROOT / 'verification/infrastructure.json').write_text(json.dumps(inventory, indent=2))
    print('Saved non-secret resource inventory and authenticated scheduler evidence.')


if __name__ == '__main__':
    main()
