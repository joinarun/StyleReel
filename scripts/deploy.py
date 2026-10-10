"""Build and deploy the exact working source; configuration contains no privileged secrets."""
import datetime
import json
import pathlib
import subprocess
import urllib.parse
from cloud_setup import api, gc

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    path = ROOT / '.deployment/config.json'
    config = json.loads(path.read_text())
    p, r = config['project'], config['region']
    build_account = 'stylereel-build@' + p + '.iam.gserviceaccount.com'
    if gc('iam', 'service-accounts', 'describe', build_account, '--project=' + p, check=False).returncode:
        gc('iam', 'service-accounts', 'create', 'stylereel-build', '--project=' + p)
    gc('projects', 'add-iam-policy-binding', p, '--member=serviceAccount:' + build_account,
       '--role=roles/logging.logWriter', '--condition=None')
    gc('artifacts', 'repositories', 'add-iam-policy-binding', 'stylereel', '--location=' + r,
       '--project=' + p, '--member=serviceAccount:' + build_account, '--role=roles/artifactregistry.writer')
    source_bucket = 'gs://' + p + '-stylereel-build-source'
    if gc('storage', 'buckets', 'describe', source_bucket, '--project=' + p, check=False).returncode:
        gc('storage', 'buckets', 'create', source_bucket, '--project=' + p, '--location=' + r,
           '--uniform-bucket-level-access', '--public-access-prevention')
    gc('storage', 'buckets', 'add-iam-policy-binding', source_bucket, '--project=' + p,
       '--member=serviceAccount:' + build_account, '--role=roles/storage.objectViewer')
    version = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
    image = r + '-docker.pkg.dev/' + p + '/stylereel/app:' + version
    print('Building version', version, 'in Cloud Build', flush=True)
    result = subprocess.run(['gcloud', '--quiet', 'builds', 'submit', str(ROOT), '--project=' + p,
                             '--region=' + r, '--config=' + str(ROOT / 'cloudbuild.yaml'),
                             '--service-account=projects/' + p + '/serviceAccounts/' + build_account,
                             '--gcs-source-staging-dir=' + source_bucket + '/source',
                             '--substitutions=_REGION=' + r + ',_VERSION=' + version,
                             '--format=value(id)'], check=True, text=True)
    service = gc('run', 'services', 'describe', 'stylereel', '--region=' + r, '--project=' + p,
                 '--format=value(status.url)', check=False)
    number = gc('projects', 'describe', p, '--format=value(projectNumber)').stdout.strip()
    url = service.stdout.strip() if service.returncode == 0 else 'https://stylereel-' + number + '.' + r + '.run.app'
    firebase = config['firebase']
    env = {
        'GOOGLE_CLOUD_PROJECT': p, 'STORAGE_CATALOG_BUCKET': config['catalog_bucket'],
        'STORAGE_TEMP_BUCKET': config['temp_bucket'], 'TASKS_QUEUE': 'stylereel-generations',
        'TASKS_LOCATION': r, 'TASKS_SERVICE_ACCOUNT': config['task_account'],
        'SERVICE_URL': url, 'VERTEX_LOCATION': 'global', 'SECRET_PREFIX': 'stylereel',
        'FIREBASE_API_KEY': firebase['apiKey'], 'FIREBASE_AUTH_DOMAIN': firebase['authDomain'],
        'FIREBASE_APP_ID': firebase.get('appId', ''), 'CORS_ORIGINS': url,
    }
    envpath = ROOT / '.deployment/runtime-env.yaml'
    envpath.write_text('\n'.join(k + ': ' + json.dumps(v) for k, v in env.items()) + '\n')
    print('Deploying scale-to-zero service', flush=True)
    gc('run', 'deploy', 'stylereel', '--project=' + p, '--region=' + r, '--image=' + image,
       '--service-account=' + config['runtime_account'], '--allow-unauthenticated',
       '--min=0', '--max=3', '--cpu=1', '--memory=1Gi', '--concurrency=4', '--timeout=600',
       '--env-vars-file=' + str(envpath), '--no-cpu-boost')
    actual_url = gc('run', 'services', 'describe', 'stylereel', '--region=' + r, '--project=' + p,
                    '--format=value(status.url)').stdout.strip()
    if actual_url != url:
        url = actual_url
        gc('run', 'services', 'update', 'stylereel', '--project=' + p, '--region=' + r,
           '--update-env-vars=SERVICE_URL=' + url + ',CORS_ORIGINS=' + url)
    identity_url = 'https://identitytoolkit.googleapis.com/admin/v2/projects/' + p + '/config'
    domains = set(api('GET', identity_url).get('authorizedDomains', []))
    domains.add(urllib.parse.urlparse(url).hostname)
    api('PATCH', identity_url + '?updateMask=authorizedDomains', {'authorizedDomains': sorted(domains)})
    jobargs = ['--location=' + r, '--project=' + p, '--schedule=*/5 * * * *', '--time-zone=UTC',
               '--uri=' + url + '/internal/maintenance', '--http-method=POST', '--message-body={}',
               '--oidc-service-account-email=' + config['task_account'], '--oidc-token-audience=' + url,
               '--attempt-deadline=180s']
    exists = gc('scheduler', 'jobs', 'describe', 'stylereel-maintenance', '--location=' + r, '--project=' + p, check=False)
    gc('scheduler', 'jobs', 'update' if exists.returncode == 0 else 'create', 'http', 'stylereel-maintenance', *jobargs)
    config.update(service_url=url, image=image, deployed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    path.write_text(json.dumps(config, indent=2))
    print('Deployed:', url)


if __name__ == '__main__':
    main()
