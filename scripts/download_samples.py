"""Download a small CC0 demo catalog with license evidence; never scrape retail stores."""
import hashlib
import html
import json
import pathlib
import re
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAMPLES = [
    ('sports-tshirt', 'Sports T-shirt', 'tshirts', 'File:Sports T-Shirt.png'),
    ('cream-dress', 'Poiret cream dress · museum sample', 'dresses', 'File:Dress MET DP143261.jpg'),
    ('cotton-skirt', 'Cotton skirt · museum sample', 'skirts', 'File:Skirt MET 55.26.87 CP1.jpg'),
    ('saree', 'Saree · experimental sample', 'sarees', 'File:Saree image.jpg'),
]


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'StyleReel-POC/1.0 (licensed catalog; joinarun@gmail.com)'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def main():
    folder = ROOT / 'sample_assets'
    folder.mkdir(exist_ok=True)
    manifest = []
    for ident, name, category, title in SAMPLES:
        params = {'action': 'query', 'format': 'json', 'prop': 'imageinfo', 'iiprop': 'url|extmetadata', 'titles': title}
        info = json.loads(get('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(params)))
        page = next(iter(info['query']['pages'].values()))
        image = page['imageinfo'][0]
        meta = image['extmetadata']
        license_name = meta.get('LicenseShortName', {}).get('value', '')
        if license_name != 'CC0':
            raise RuntimeError(title + ' is not verified CC0: ' + license_name)
        author = html.unescape(re.sub('<[^>]+>', '', meta.get('Artist', {}).get('value', '')))
        ext = pathlib.Path(urllib.parse.urlparse(image['url']).path).suffix
        filename = ident + ext
        content = get(image['url'])
        (folder / filename).write_bytes(content)
        entry = {'id': 'sample-' + ident, 'name': name, 'category_id': category,
                 'description': 'Licensed demo asset; replace with your store product photos for retail evaluation.',
                 'file': filename, 'license': 'CC0 1.0', 'license_url': meta['LicenseUrl']['value'],
                 'source_url': image['descriptionurl'], 'attribution': author,
                 'sha256': hashlib.sha256(content).hexdigest()}
        manifest.append(entry)
        print('Verified and downloaded:', title, license_name, flush=True)
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    (folder / 'LICENSES.md').write_text('# Demo catalog licenses\n\n' + '\n\n'.join(
        f"- **{x['name']}** — {x['attribution']}; [{x['license']}]({x['license_url']}); [source]({x['source_url']}). Original files unchanged; application previews are resized. SHA-256: `{x['sha256']}`."
        for x in manifest))


if __name__ == '__main__':
    main()
