import json
from pathlib import Path

root = Path(__file__).parent
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
assert manifest['manifest_version'] == 3
for name in ['popup.html', 'popup.css', 'popup.js', 'content.js', 'content.css']:
    assert (root / name).is_file(), name
assert 'tabs' not in manifest.get('permissions', [])
assert 'webRequest' not in manifest.get('permissions', [])
print('extension validation passed')
