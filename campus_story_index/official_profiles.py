"""Sync official character profiles into a persistent, last-known-good cache."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urljoin, urlsplit

import requests
import yaml

from .io import atomic_write

ORIGIN = 'https://gakuen.idolmaster-official.jp'
INDEX_URL = ORIGIN + '/idol/'
SEED_PATH = Path(__file__).with_suffix('.json')


def normalize_name(value):
    return ''.join(unicodedata.normalize('NFKC', value).split())


def official_url(value, base=INDEX_URL, prefix='/assets/'):
    if not value:
        return None
    url = urljoin(base, value)
    parts = urlsplit(url)
    if (parts.scheme, parts.netloc) != ('https', urlsplit(ORIGIN).netloc) or not parts.path.startswith(prefix):
        return None
    return url


class ProfilePage(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.slug = None
        self.roster = {}
        self.quotes = []
        self.introductions = []
        self.voice_ids = []
        self._entry = None
        self._field = None
        self._text = []
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = set((attrs.get('class') or '').split())
        if attrs.get('id') == 'current_idol':
            self.slug = attrs.get('data-current')
        if tag == 'a' and 'idol-nav__link' in classes:
            self._entry = {'url': attrs.get('href'), 'photo': None, 'name': ''}
        if tag == 'img' and self._entry is not None:
            self._entry['photo'] = attrs.get('src')
        if 'idol-info__voice-btn' in classes and re.fullmatch(r'[1-9][0-9]*', attrs.get('data-voice') or ''):
            voice = attrs['data-voice']
            if voice not in self.voice_ids:
                self.voice_ids.append(voice)
        if tag == 'p':
            self._field = next((field for cls, field in (
                ('idol-nav__name', 'name'), ('idol__serif-text', 'quote'),
                ('idol-info__text', 'introduction')) if cls in classes), None)
            self._text = []
        elif tag == 'br' and self._field:
            self._text.append(' ')

    def handle_data(self, data):
        if self._field:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == 'p' and self._field:
            text = ' '.join(''.join(self._text).split())
            if self._field == 'name' and self._entry is not None:
                self._entry['name'] = text
            elif self._field == 'quote' and text:
                self.quotes.append(text)
            elif self._field == 'introduction' and text:
                self.introductions.append(text)
            self._field = None
        if tag == 'a' and self._entry is not None:
            if self._entry['name']:
                self.roster[normalize_name(self._entry['name'])] = self._entry
            self._entry = None


def fetch_page(session, url):
    # The official CDN may retain the old roster when new characters are released.
    with session.get(url, params={'profile_refresh': int(time.time())},
                     timeout=(5, 15), allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected profile response')
        return ProfilePage(response.content.decode('utf-8'))


def media_available(session, url, kind):
    try:
        with session.head(url, timeout=(5, 10), allow_redirects=False) as response:
            if response.status_code != 405:
                return response.status_code == 200 and response.headers.get('Content-Type', '').lower().startswith(kind + '/')
        with session.get(url, headers={'Range': 'bytes=0-0'}, stream=True,
                         timeout=(5, 10), allow_redirects=False) as response:
            return response.status_code in (200, 206) and response.headers.get('Content-Type', '').lower().startswith(kind + '/')
    except requests.RequestException:
        return False


def fetch_profile(entry, previous, index):
    url = official_url(entry['url'], prefix='/idol/')
    if not url:
        raise ValueError('Invalid official profile URL')
    with requests.Session() as session:
        page = index if url == INDEX_URL else fetch_page(session, url)
        slug = page.slug or ''
        expected = urlsplit(url).path.removeprefix('/idol/').strip('/') or index.slug
        if not re.fullmatch(r'[a-z0-9_-]+', slug) or slug != expected or len(page.introductions) != 1:
            raise ValueError('Official profile markup changed')
        photo = official_url(entry['photo'])
        if not photo or not media_available(session, photo, 'image'):
            photo = previous.get('photo')
        voices = []
        for voice_id in page.voice_ids:
            candidates = [ORIGIN + f'/assets/{folder}/voice_{voice_id}.mp3'
                          for folder in (f'data/voice/{slug}', f'{slug}/voice')]
            previous_voice = next((voice for voice in previous.get('voices', []) if voice in candidates), None)
            if previous_voice:
                candidates.remove(previous_voice)
                candidates.insert(0, previous_voice)
            voice = next((candidate for candidate in candidates if media_available(session, candidate, 'audio')), previous_voice)
            if voice:
                voices.append(voice)
        return {'source_url': url, 'quote': page.quotes or previous.get('quote', []),
                'introduction': page.introductions[0], 'photo': photo,
                'voices': voices if page.voice_ids else previous.get('voices', [])}


def sync_profiles(masterdata, output):
    output = Path(output)
    profiles = json.loads(SEED_PATH.read_text())
    if output.exists():
        profiles.update(json.loads(output.read_text()))
    characters = yaml.load((Path(masterdata) / 'Character.yaml').read_text(), Loader=yaml.CSafeLoader)
    playable = {row['id']: normalize_name(''.join((row.get('lastName') or '', row.get('firstName') or '')))
                for row in characters if row.get('isPlayable')}
    previous = dict(profiles)
    try:
        with requests.Session() as session:
            index = fetch_page(session, INDEX_URL)
        if not index.roster:
            raise ValueError('Official roster markup changed')
    except (requests.RequestException, ValueError) as exc:
        print(f'官网资料: 抓取失败（{type(exc).__name__}），保留已有 {len(profiles)} 位资料', flush=True)
    else:
        matched = [(ident, index.roster[name]) for ident, name in playable.items() if name in index.roster]

        def refresh(item):
            ident, entry = item
            try:
                return ident, fetch_profile(entry, previous.get(ident, {}), index)
            except (requests.RequestException, ValueError):
                return ident, None

        failed = 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            for ident, profile in pool.map(refresh, matched):
                if profile is None:
                    failed += 1
                else:
                    profiles[ident] = profile
        changed = sum(profile != previous.get(ident) for ident, profile in profiles.items())
        missing = len(playable) - len(matched)
        print(f'官网资料: 更新 {changed} 位，抓取失败 {failed} 位，尚未公开 {missing} 位', flush=True)
    if not output.exists() or json.loads(output.read_text()) != profiles:
        atomic_write(output, profiles)
    return profiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--masterdata', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=SEED_PATH)
    args = parser.parse_args()
    sync_profiles(args.masterdata, args.output)


if __name__ == '__main__':
    main()
