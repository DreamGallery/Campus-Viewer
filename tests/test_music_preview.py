import unittest
from campus_story_index.music_preview import timed_lyrics


class MusicLyricsTests(unittest.TestCase):
    def test_timeline_offset_speed_and_formatting(self):
        rows = [{'from': 6, 'to': 10, 'text': '<color=#fff>test</color>\nline'},
                {'from': 2, 'to': 4, 'text': 'first'}]
        self.assertEqual(timed_lyrics(rows, start=3, clip_in=2, scale=2), [
            {'start': 3, 'end': 4, 'text': 'first'},
            {'start': 5, 'end': 7, 'text': 'test\nline'}])

    def test_trim_before_audio_and_ignore_empty_or_invalid_lines(self):
        rows = [{'from': -2, 'to': 1, 'text': 'intro'},
                {'from': -3, 'to': -1, 'text': 'before'},
                {'from': 3, 'to': 2, 'text': 'invalid'},
                {'from': 1, 'to': 2, 'text': ' '}]
        self.assertEqual(timed_lyrics(rows), [{'start': 0, 'end': 1, 'text': 'intro'}])
        with self.assertRaises(ValueError):
            timed_lyrics(rows, scale=0)

class MusicSelectionTests(unittest.TestCase):
    def test_vocals_only_and_explicit_selection(self):
        from campus_story_index.music_preview import select_music
        rows = [{'id': 'music-char-hski-001', 'gameVersionAssetId': 'vocal'},
                {'id': 'music-char-hski-001-inst', 'gameVersionAssetId': 'vocal-inst'},
                {'id': 'music-bgm-001', 'gameVersionAssetId': 'bgm'},
                {'id': 'music-char-absent', 'gameVersionAssetId': 'absent'}]
        resources = {n+'.awb': {} for n in ['vocal', 'vocal-inst', 'bgm']}
        self.assertEqual([r['id'] for r in select_music(rows, resources)], ['music-char-hski-001'])
        self.assertEqual(len(select_music(rows, resources, scope='all')), 3)
        with self.assertRaises(ValueError): select_music(rows, resources, ['music-char-absent'])

    def test_publish_file_replaces_damaged_file_without_mutating_hardlink(self):
        import os
        from pathlib import Path
        import tempfile
        from campus_story_index.music_preview import publish_file
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); out=root/'out';out.mkdir()
            source=root/'a.flac';source.write_bytes(b'correct')
            name=publish_file(source,out)
            (out/name).write_bytes(b'damaged')
            os.link(out/name,root/'old-release.flac')
            publish_file(source,out)
            self.assertEqual((out/name).read_bytes(),b'correct')
            self.assertEqual((root/'old-release.flac').read_bytes(),b'damaged')

    def test_decoder_reads_full_awb_and_reuses_verified_output(self):
        import json
        from pathlib import Path
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        import wave
        from campus_story_index.music_preview import decode_song
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);output=root/'out';output.mkdir()
            source=root/'song.awb';source.write_bytes(b'full')
            acb=root/'song.acb';acb.write_bytes(b'prefetch')
            def run(args, **kwargs):
                self.assertEqual(Path(args[-1]),source)
                with wave.open(args[args.index('-o')+1],'wb') as f:
                    f.setparams((2,2,48000,0,'NONE','not compressed'));f.writeframes(b'\0'*4800*4)
                return SimpleNamespace(stdout=json.dumps({'playSamples':4800,'sampleRate':48000,'encoding':'CRI HCA','streamInfo':{'total':1}}))
            def encode(wav):
                target=wav.with_suffix('.flac');target.write_bytes(b'fLaC');return target
            with patch('campus_story_index.music_preview.subprocess.run',side_effect=run) as decoder, patch('campus_story_index.music_preview.encode_flac',side_effect=encode):
                first=decode_song(source,acb,output,root,Path('/decoder'),'hash')
                second=decode_song(source,acb,output,root,Path('/decoder'),'hash')
                self.assertEqual(first,second);self.assertEqual(decoder.call_count,1)
                (output/first['file']).write_bytes(b'broken')
                repaired=decode_song(source,acb,output,root,Path('/decoder'),'hash')
                self.assertEqual((output/repaired['file']).read_bytes(),b'fLaC')
                self.assertEqual(decoder.call_count,2)
