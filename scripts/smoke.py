import json
import pathlib
import urllib.error
import urllib.request
root = pathlib.Path(__file__).resolve().parents[1]
config = json.loads((root / '.deployment/config.json').read_text())
url = config['service_url']
for path in ['/', '/api/health', '/api/config']:
    with urllib.request.urlopen(url + path, timeout=60) as response:
        print(path, response.status, response.headers.get('Content-Type'))
for path in ['/api/settings', '/api/users', '/internal/maintenance']:
    try:
        request = urllib.request.Request(url + path, method='POST' if path.startswith('/internal') else 'GET', data=b'{}' if path.startswith('/internal') else None)
        urllib.request.urlopen(request, timeout=60)
        raise AssertionError('Protected route unexpectedly accepted anonymous request: ' + path)
    except urllib.error.HTTPError as exc:
        assert exc.code in (401, 403), (path, exc.code)
        print(path, exc.code, 'anonymous access denied')
