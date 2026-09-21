"""Full-data reachability and local image verification for the web export."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--catalog',type=Path,default=Path('generated/story-index.json'))
p.add_argument('--web',type=Path,default=Path('data/web'))
a=p.parse_args(); source=json.loads(a.catalog.read_text()); manifest=json.loads((a.web/'catalog/manifest.json').read_text())
root=a.web/'catalog/builds'/manifest['build_id']; entries=set(); scripts=set()
for category in [c for c in source['categories'] if c['parent_id'] is None]:
 rows=json.loads((root/manifest['lists'][category['id']]).read_text())
 for row in rows:
  entries.update(row.get('source_entry_ids', [row['id']])); scripts.add(row['script_id'])
  for image in row.get('group_images', []):
   assert (a.web/image['url'].lstrip('/')).is_file(), image['url']
  chapter=json.loads((root/'chapters'/(row['script_id']+'.json')).read_text())
  assert row['id'] in {e['id'] for e in chapter['entries']}, row['id']
assert entries=={e['id'] for e in source['entries']}
assert scripts=={s['id'] for s in source['scripts']}
images=json.loads((a.web/'assets/manifest.json').read_text())['images']
for image in images:
 if image.get('path'):
  path=a.web/'assets'/image['path']
  assert hashlib.sha256(path.read_bytes()).hexdigest()==image['sha256'], path
for character in manifest['characters']:
 for field in ['portrait','avatar','signature']:
  assert character[field], (character['id'],field)
  assert (a.web/character[field].lstrip('/')).is_file(), character[field]
print(json.dumps({'reachable_entries':len(entries),'reachable_scripts':len(scripts),'characters':len(manifest['characters']),
 'verified_images':sum(bool(i.get('path')) for i in images)},ensure_ascii=False))
