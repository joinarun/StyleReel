"""Configure Firebase Auth SDK with Identity Platform; a Firebase web app is optional for Auth."""
import argparse
import json
from cloud_setup import api, gc, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--service-url', default='')
    args = parser.parse_args()
    p, r = 'virtualtryon-511016', 'asia-south1'
    gc('services', 'enable', 'apikeys.googleapis.com', '--project=' + p)
    api('POST', 'https://identitytoolkit.googleapis.com/v2/projects/' + p + '/identityPlatform:initializeAuth', {}, tolerate=(400,409))
    keys = json.loads(gc('services', 'api-keys', 'list', '--project=' + p, '--format=json').stdout)
    key = next((k for k in keys if k.get('displayName') == 'StyleReel Web Authentication'), None)
    if not key:
        gc('services', 'api-keys', 'create', '--display-name=StyleReel Web Authentication', '--project=' + p,
           '--api-target=service=identitytoolkit.googleapis.com', '--api-target=service=securetoken.googleapis.com')
        keys = json.loads(gc('services', 'api-keys', 'list', '--project=' + p, '--format=json').stdout)
        key = next(k for k in keys if k.get('displayName') == 'StyleReel Web Authentication')
    api_key = gc('services', 'api-keys', 'get-key-string', key['name'], '--project=' + p, '--format=value(keyString)').stdout.strip()
    identity_url = 'https://identitytoolkit.googleapis.com/admin/v2/projects/' + p + '/config'
    config = api('GET', identity_url)
    domains = set(config.get('authorizedDomains', [])) | {p + '.firebaseapp.com'}
    if args.service_url:
        from urllib.parse import urlparse
        domains.add(urlparse(args.service_url).hostname)
    api('PATCH', identity_url + '?updateMask=signIn.email,client.permissions,authorizedDomains,recaptchaConfig',
        {'signIn': {'email': {'enabled': True, 'passwordRequired': True}},
         'client': {'permissions': {'disabledUserSignup': True, 'disabledUserDeletion': True}},
         'authorizedDomains': sorted(domains),
         'recaptchaConfig': {'emailPasswordEnforcementState': 'ENFORCE', 'managedRules': [{'endScore': 0.3, 'action': 'BLOCK'}]}})
    rules = {'source': {'files': [{'name': 'firestore.rules', 'content': (ROOT / 'firestore.rules').read_text()}]}}
    ruleset = api('POST', 'https://firebaserules.googleapis.com/v1/projects/' + p + '/rulesets', rules)
    release_url = 'https://firebaserules.googleapis.com/v1/projects/' + p + '/releases/cloud.firestore'
    release = {'name': 'projects/' + p + '/releases/cloud.firestore', 'rulesetName': ruleset['name']}
    if 'error' in api('GET', release_url, tolerate=(404,)):
        api('POST', 'https://firebaserules.googleapis.com/v1/projects/' + p + '/releases', release)
    else:
        api('PATCH', release_url + '?updateMask=rulesetName', {'release': release})
    for name in ['stylereel-fashn-api-key', 'stylereel-pruna-api-key']:
        if gc('secrets', 'describe', name, '--project=' + p, check=False).returncode:
            gc('secrets', 'create', name, '--replication-policy=automatic', '--project=' + p)
        for role in ['roles/secretmanager.secretAccessor', 'roles/secretmanager.secretVersionAdder']:
            gc('secrets', 'add-iam-policy-binding', name, '--project=' + p,
               '--member=serviceAccount:stylereel-runtime@' + p + '.iam.gserviceaccount.com', '--role=' + role)
    dest = ROOT / '.deployment' / 'config.json'
    dest.parent.mkdir(exist_ok=True)
    firebase = {'apiKey': api_key, 'authDomain': p + '.firebaseapp.com', 'projectId': p}
    dest.write_text(json.dumps({'project': p, 'region': r, 'firebase': firebase,
                               'firebase_web_app_registration': 'Identity Platform Auth SDK configuration; no appId required for email/password Auth',
                               'runtime_account': 'stylereel-runtime@' + p + '.iam.gserviceaccount.com',
                               'task_account': 'stylereel-dispatch@' + p + '.iam.gserviceaccount.com',
                               'catalog_bucket': p + '-stylereel-catalog', 'temp_bucket': p + '-stylereel-temp',
                               'service_url': args.service_url}, indent=2))
    print('Identity Platform configured with Firebase Web Authentication SDK and enforced reCAPTCHA. No fabricated Firebase appId.')


if __name__ == '__main__':
    main()
