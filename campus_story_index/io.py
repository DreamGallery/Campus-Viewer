"""Snapshot reads and atomic single-file publication."""
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value).hexdigest()


def git_revision(path):
    result = subprocess.run(['git', '-C', str(path), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


class Snapshot:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f'Input directory does not exist: {root}')
        self.files = {}
        self.revision = git_revision(self.root)

    def read(self, relative):
        path = self.root / relative
        content = path.read_bytes()
        checksum = digest(content)
        key = str(relative)
        if key in self.files and self.files[key] != checksum:
            raise ValueError(f'Input changed during build: {path}')
        self.files[key] = checksum
        return content

    def verify(self):
        if self.revision != git_revision(self.root):
            raise ValueError(f'Git revision changed during build: {self.root}')
        for relative, checksum in self.files.items():
            if digest((self.root / relative).read_bytes()) != checksum:
                raise ValueError(f'Input changed during build: {relative}')

    def manifest(self):
        return {'git_commit': self.revision,
                'content_sha256': digest(canonical(self.files).encode()),
                'files': dict(sorted(self.files.items()))}


class MasterData(Snapshot):
    def __init__(self, root):
        super().__init__(root)
        self.tables = {}
        self.paths = sorted(self.root.glob('*.yaml'))
        if not self.paths:
            raise ValueError('No YAML masterdata tables found')

    def table(self, name):
        if name not in self.tables:
            value = yaml.load(self.read(name + '.yaml'), Loader=yaml.CSafeLoader) or []
            if not isinstance(value, list) or any(not isinstance(r, dict) for r in value):
                raise ValueError(f'{name}: expected an array of records')
            self.tables[name] = value
        return self.tables[name]

    def adv_tables(self):
        # Read all table bytes once into the snapshot, parse only tables with script literals.
        for path in self.paths:
            if b'adv_' in self.read(path.name):
                yield path.stem, self.table(path.stem)

    def verify(self):
        if self.paths != sorted(self.root.glob('*.yaml')):
            raise ValueError('Masterdata table list changed during build')
        super().verify()


def read_csvs(snapshot):
    paths = sorted((snapshot.root / 'CSV').rglob('*.csv'))
    if not paths:
        raise ValueError('No CSV files found under stories/CSV')
    result = {}
    for path in paths:
        asset = path.stem
        if asset in result:
            raise ValueError(f'Duplicate CSV basename: {asset}')
        relative = str(path.relative_to(snapshot.root))
        content = snapshot.read(relative)
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))
        if not reader.fieldnames or not {'id', 'name', 'text', 'trans'}.issubset(reader.fieldnames):
            raise ValueError(f'Invalid CSV header: {relative}')
        rows = list(reader)
        if any(None in r or any(r.get(k) is None for k in reader.fieldnames) for r in rows):
            raise ValueError(f'Malformed CSV row: {relative}')
        texts = [r for r in rows if r['text'].strip()]
        original = [[r['id'], r['name'], r['text']] for r in texts]
        result[asset] = {
            'csv_path': relative, 'file_sha256': digest(content),
            'source_text_sha256': digest(canonical(original).encode()),
            'text_row_count': len(texts),
            'translated_row_count': sum(bool(r['trans'].strip()) for r in texts),
            'text_status': 'present' if texts else 'empty',
        }
    return result, paths


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as f:
            temporary = f.name
            json.dump(value, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
