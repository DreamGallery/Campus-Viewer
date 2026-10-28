import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from campus_story_index.web_assets import extract_one


class WebAssetTests(unittest.TestCase):
    def test_native_textures_preserve_dimensions_and_legacy_files(self):
        cases = [
            ('img_general_cidol-test_0-full', (1024, 2048), 'stretch-v2'),
            ('img_general_csprt-test_full', (2048, 1024), 'stretch-v2'),
            ('img_general_event_test-banner', (1024, 256), 'banner-3to1-v1'),
        ]
        for name, size, old_recipe in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                cache, output = root / 'bundles', root / 'images'
                cache.mkdir(); output.mkdir()
                (cache / name).write_bytes(b'fixture bundle')
                item = {'name': name, 'md5': '0' * 32}
                old = output / f"{name}.{item['md5']}.{old_recipe}.webp"
                old.write_bytes(b'legacy resource referenced by an existing release')
                # Transparent borders must be retained alongside the native size.
                picture = Image.new('RGBA', size)
                picture.paste((90, 120, 150, 255), (20, 20, size[0] - 20, size[1] - 20))
                data = SimpleNamespace(m_Name=name, image=picture)
                obj = SimpleNamespace(type=SimpleNamespace(name='Texture2D'), read=lambda: data)
                unity = SimpleNamespace(load=lambda _: SimpleNamespace(objects=[obj]))
                with patch.dict('sys.modules', {'UnityPy': unity}), \
                        patch('campus_story_index.web_assets.download_one', return_value={'status': 'cached'}), \
                        patch('campus_story_index.web_assets.decode_header', side_effect=lambda payload, _: payload):
                    result = extract_one(item, '', cache, output)
                    path = root / result['path']
                    self.assertTrue(path.name.endswith('.native-v1.webp'))
                    self.assertEqual((result['width'], result['height']), size)
                    with Image.open(path) as stored:
                        self.assertEqual(stored.size, size)
                        self.assertEqual(stored.getpixel((0, 0))[3], 0)
                    self.assertEqual(old.read_bytes(), b'legacy resource referenced by an existing release')
                    with patch.object(unity, 'load', side_effect=AssertionError('cache should avoid decoding')):
                        cached = extract_one(item, '', cache, output)
                    self.assertEqual(cached['status'], 'cached')
                    self.assertEqual(cached['sha256'], result['sha256'])
                    self.assertEqual((cached['width'], cached['height']), size)


if __name__ == '__main__':
    unittest.main()
