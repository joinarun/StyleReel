"""Anonymous HTTPS/security/OpenAPI smoke checks for the latest deployed revision."""
import datetime as dt
import json
import httpx
from e2e_live import ROOT

config = json.loads((ROOT / '.deployment/config.json').read_text())
inventory = json.loads((ROOT / 'verification/infrastructure.json').read_text())
report = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'service_url': config['service_url'], 'revision': inventory['service']['status']['latestReadyRevisionName'], 'image': config['image'], 'checks': []}


def check(name, value):
    report['checks'].append({'name': name, 'passed': bool(value)})
    if not value:
        raise AssertionError(name)


with httpx.Client(base_url=config['service_url'], follow_redirects=True, timeout=60) as client:
    for path in ['/', '/api/health', '/api/config']:
        response = client.get(path)
        check(path + ' serves HTTPS successfully', response.status_code == 200 and response.url.scheme == 'https')
        check(path + ' serves security headers', response.headers.get('x-content-type-options') == 'nosniff' and "frame-ancestors 'none'" in response.headers.get('content-security-policy', ''))
    check('Same-origin camera permission is allowed; microphone remains disabled', 'camera=(self)' in response.headers.get('permissions-policy', '') and 'microphone=()' in response.headers.get('permissions-policy', ''))
    for path in ['/api/settings', '/api/users', '/api/tryon/jobs/no-such-job', '/internal/maintenance']:
        response = client.post(path, json={}) if path.startswith('/internal') else client.get(path)
        check(path + ' denies anonymous access', response.status_code in [401, 403])
    contract = client.get('/api/docs')
    check('OpenAPI contract exposes authoritative job metadata', contract.status_code == 200 and {'provider', 'provider_label', 'model', 'experimental'} <= set(contract.json()['components']['schemas']['JobResponse']['properties']))
identity = inventory['identity']
check('Email/password Enterprise CAPTCHA remains enforced', identity['recaptcha'].get('emailPasswordEnforcementState') == 'ENFORCE')
check('Public signup remains disabled', identity['public_user_permissions'].get('disabledUserSignup') is True)
check('Runtime has no operator token-signing IAM binding', not inventory['runtime_account_iam'].get('bindings'))
check('Cloud Run serves the final ready revision', inventory['service']['status']['latestCreatedRevisionName'] == report['revision'])
(ROOT / 'verification/revision-smoke-evidence.json').write_text(json.dumps(report, indent=2))
print('PASS:', len(report['checks']), 'final deployed smoke/security checks.')
