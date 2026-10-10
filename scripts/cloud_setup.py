"""Create only the POC's low-cost managed resources; never print credentials."""
import argparse
import json
import pathlib
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def gc(*args, check=True, stdin=None):
    command = ['gcloud', '--quiet', *args]
    result = subprocess.run(command, input=stdin, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result


def api(method, url, body=None, tolerate=()):
    token = gc('auth', 'print-access-token').stdout.strip()
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={'Authorization': 'Bearer ' + token,
                                                        'X-Goog-User-Project': 'virtualtryon-511016',
                                                        'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        value = json.loads(exc.read())
        if exc.code in tolerate:
            return value
        raise RuntimeError(f'{method} {url.split("?")[0]}: {exc.code}: {value.get("error", {}).get("message", "failed")}') from None


def wait_operation(host, operation):
    name = operation.get('name')
    if not name:
        return operation
    for _ in range(90):
        state = api('GET', host + '/' + name)
        if state.get('done'):
            if state.get('error'):
                raise RuntimeError(str(state['error']))
            return state.get('response', state)
        time.sleep(2)
    raise RuntimeError('Cloud operation did not complete within three minutes')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default='virtualtryon-511016')
    parser.add_argument('--region', default='asia-south1')
    parser.add_argument('--service-url', default='')
    args = parser.parse_args()
    p, r = args.project, args.region
    number = gc('projects', 'describe', p, '--format=value(projectNumber)').stdout.strip()
    print('Enabling required APIs in', p, flush=True)
    apis = ['run', 'firestore', 'storage', 'aiplatform', 'identitytoolkit', 'firebase', 'recaptchaenterprise',
            'secretmanager', 'cloudtasks', 'cloudscheduler', 'cloudbuild', 'artifactregistry', 'iam', 'iamcredentials', 'firebaserules']
    gc('services', 'enable', *[s + '.googleapis.com' for s in apis], '--project=' + p)
    gc('beta', 'services', 'identity', 'create', '--service=identitytoolkit.googleapis.com', '--project=' + p)
    gc('projects', 'add-iam-policy-binding', p,
       '--member=serviceAccount:service-' + number + '@gcp-sa-identitytoolkit.iam.gserviceaccount.com',
       '--role=roles/identitytoolkit.serviceAgent', '--condition=None')
    for short in ['stylereel-runtime', 'stylereel-dispatch']:
        email = short + '@' + p + '.iam.gserviceaccount.com'
        if gc('iam', 'service-accounts', 'describe', email, '--project=' + p, check=False).returncode:
            gc('iam', 'service-accounts', 'create', short, '--project=' + p, '--display-name=StyleReel ' + short)
    runtime = 'stylereel-runtime@' + p + '.iam.gserviceaccount.com'
    dispatcher = 'stylereel-dispatch@' + p + '.iam.gserviceaccount.com'
    for role in ['roles/datastore.user', 'roles/aiplatform.user', 'roles/cloudtasks.enqueuer', 'roles/firebaseauth.admin']:
        gc('projects', 'add-iam-policy-binding', p, '--member=serviceAccount:' + runtime, '--role=' + role, '--condition=None')
    gc('iam', 'service-accounts', 'add-iam-policy-binding', dispatcher, '--project=' + p,
       '--member=serviceAccount:' + runtime, '--role=roles/iam.serviceAccountUser')
    databases = json.loads(gc('firestore', 'databases', 'list', '--project=' + p, '--format=json').stdout)
    if not any(d['name'].endswith('/(default)') for d in databases):
        gc('firestore', 'databases', 'create', '--database=(default)', '--location=' + r, '--type=firestore-native', '--project=' + p)
    for kind in ['catalog', 'temp']:
        bucket = 'gs://' + p + '-stylereel-' + kind
        if gc('storage', 'buckets', 'describe', bucket, '--project=' + p, check=False).returncode:
            gc('storage', 'buckets', 'create', bucket, '--location=' + r, '--uniform-bucket-level-access', '--public-access-prevention', '--project=' + p)
        gc('storage', 'buckets', 'add-iam-policy-binding', bucket,
           '--member=serviceAccount:' + runtime, '--role=roles/storage.objectAdmin', '--project=' + p)
        if kind == 'temp':
            gc('storage', 'buckets', 'update', bucket, '--clear-soft-delete', '--no-versioning', '--project=' + p)
            rule = {'rule': [{'action': {'type': 'Delete'}, 'condition': {'age': 2}}]}
            rulepath = ROOT / '.deployment' / 'temp-lifecycle.json'
            rulepath.parent.mkdir(exist_ok=True)
            rulepath.write_text(json.dumps(rule))
            gc('storage', 'buckets', 'update', bucket, '--lifecycle-file=' + str(rulepath), '--project=' + p)
    for name in ['stylereel-fashn-api-key', 'stylereel-pruna-api-key', 'stylereel-bootstrap-password']:
        created = gc('secrets', 'describe', name, '--project=' + p, check=False).returncode != 0
        if created:
            gc('secrets', 'create', name, '--replication-policy=automatic', '--project=' + p)
        if name != 'stylereel-bootstrap-password':
            for role in ['roles/secretmanager.secretAccessor', 'roles/secretmanager.secretVersionAdder']:
                gc('secrets', 'add-iam-policy-binding', name, '--project=' + p,
                   '--member=serviceAccount:' + runtime, '--role=' + role)
        elif created:
            gc('secrets', 'versions', 'add', name, '--data-file=-', '--project=' + p, stdin=secrets.token_urlsafe(32))
    q = 'stylereel-generations'
    if gc('tasks', 'queues', 'describe', q, '--location=' + r, '--project=' + p, check=False).returncode:
        gc('tasks', 'queues', 'create', q, '--location=' + r, '--project=' + p)
    gc('tasks', 'queues', 'update', q, '--location=' + r, '--project=' + p, '--max-concurrent-dispatches=2',
       '--max-dispatches-per-second=5', '--max-attempts=5', '--min-backoff=10s', '--max-backoff=120s')
    if gc('artifacts', 'repositories', 'describe', 'stylereel', '--location=' + r, '--project=' + p, check=False).returncode:
        gc('artifacts', 'repositories', 'create', 'stylereel', '--repository-format=docker', '--location=' + r, '--project=' + p)
    print('Configuring Firebase and enforced authentication protection', flush=True)
    firebase = 'https://firebase.googleapis.com/v1beta1'
    existing = api('GET', firebase + '/projects/' + p, tolerate=(404,))
    if 'error' in existing:
        try:
            wait_operation(firebase, api('POST', firebase + '/projects/' + p + ':addFirebase', {}))
        except RuntimeError as exc:
            if '403' not in str(exc) or p != 'virtualtryon-511016':
                raise
            print('Firebase project registration unavailable; configuring supported Identity Platform Auth SDK directly.', flush=True)
            subprocess.run(['python3', str(ROOT / 'scripts/auth_setup.py'), '--service-url', args.service_url], check=True)
            return
    apps = api('GET', firebase + '/projects/' + p + '/webApps').get('apps', [])
    app = next((a for a in apps if a.get('displayName') == 'StyleReel'), None)
    if not app:
        app = wait_operation(firebase, api('POST', firebase + '/projects/' + p + '/webApps', {'displayName': 'StyleReel'}))
    app_id = app['appId']
    config = api('GET', firebase + '/projects/' + p + '/webApps/' + urllib.parse.quote(app_id, safe='') + '/config')
    api('POST', 'https://identitytoolkit.googleapis.com/v2/projects/' + p + '/identityPlatform:initializeAuth', {}, tolerate=(400,409))
    identity_url = 'https://identitytoolkit.googleapis.com/admin/v2/projects/' + p + '/config'
    old = api('GET', identity_url)
    domains = set(old.get('authorizedDomains', [])) | {p + '.firebaseapp.com'}
    if args.service_url:
        domains.add(urllib.parse.urlparse(args.service_url).hostname)
    auth_body = {'signIn': {'email': {'enabled': True, 'passwordRequired': True}},
                 'client': {'permissions': {'disabledUserSignup': True, 'disabledUserDeletion': True}},
                 'authorizedDomains': sorted(domains),
                 'recaptchaConfig': {'emailPasswordEnforcementState': 'ENFORCE',
                                     'managedRules': [{'endScore': 0.3, 'action': 'BLOCK'}]}}
    api('PATCH', identity_url + '?updateMask=signIn.email,client.permissions,authorizedDomains,recaptchaConfig', auth_body)
    # Clients never receive direct Firestore access. Publish deny-all rules.
    rules = {'source': {'files': [{'name': 'firestore.rules', 'content': (ROOT / 'firestore.rules').read_text()}]}}
    ruleset = api('POST', 'https://firebaserules.googleapis.com/v1/projects/' + p + '/rulesets', rules)
    release_url = 'https://firebaserules.googleapis.com/v1/projects/' + p + '/releases/cloud.firestore'
    release = {'name': 'projects/' + p + '/releases/cloud.firestore', 'rulesetName': ruleset['name']}
    if 'error' in api('GET', release_url, tolerate=(404,)):
        api('POST', 'https://firebaserules.googleapis.com/v1/projects/' + p + '/releases', release)
    else:
        api('PATCH', release_url + '?updateMask=rulesetName', {'release': release})
    deployment = {'project': p, 'region': r, 'firebase': config, 'runtime_account': runtime,
                  'task_account': dispatcher, 'service_url': args.service_url,
                  'catalog_bucket': p + '-stylereel-catalog', 'temp_bucket': p + '-stylereel-temp'}
    dest = ROOT / '.deployment' / 'config.json'
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(deployment, indent=2))
    print('Resource setup complete; public Firebase configuration saved in .deployment/config.json')
    print('Bootstrap password stays in Secret Manager: stylereel-bootstrap-password')


if __name__ == '__main__':
    main()
