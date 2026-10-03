"""Persistent first-run dialogue encoding settings (independent of music)."""
import json
import os
from pathlib import Path
from .io import atomic_write

MP3_BITRATES = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)


def encoding_settings(format='flac', bitrate=None):
    format = format.strip().lower()
    if format not in ('flac', 'mp3', 'aac'):
        raise ValueError('CAMPUS_VOICE_FORMAT 必须为 flac、mp3 或 aac')
    if format == 'flac':
        if bitrate is not None and str(bitrate).strip():
            raise ValueError('FLAC 不使用码率配置，请留空 CAMPUS_VOICE_BITRATE')
        return {'format': 'flac', 'compression_level': 8}
    try:
        kbps = int(str(bitrate).strip().lower().removesuffix('k')) if bitrate is not None and str(bitrate).strip() else 128
    except ValueError:
        raise ValueError('CAMPUS_VOICE_BITRATE 应为 kbps 整数，例如 128 或 128k') from None
    if format == 'mp3' and kbps not in MP3_BITRATES:
        raise ValueError('MP3 码率必须为 ' + '/'.join(map(str, MP3_BITRATES)) + ' kbps')
    if format == 'aac' and not 32 <= kbps <= 320:
        raise ValueError('AAC 码率必须在 32–320 kbps 之间')
    return {'format': format, 'bitrate_kbps': kbps}


def audio_suffix(settings):
    return '.m4a' if settings['format'] == 'aac' else '.' + settings['format']


def initialize_voice_encoding(root):
    """Called under the updater lock; never implicitly transcode an existing volume."""
    root = Path(root)
    path = root / 'voice-encoding.json'
    saved = json.loads(path.read_text()) if path.exists() else None
    if saved is None and ((root / 'current').exists() or
            any((root / 'cache/audio/bank-manifests').glob('*.json')) or
            any((root / 'cache/audio/clips').glob('*/*'))):
        saved = encoding_settings()  # Existing deployments use verified FLAC.
    format = os.getenv('CAMPUS_VOICE_FORMAT', '').strip() or (saved or {}).get('format', 'flac')
    bitrate = os.getenv('CAMPUS_VOICE_BITRATE', '').strip() or (saved or {}).get('bitrate_kbps')
    selected = encoding_settings(format, bitrate)
    if saved is not None and selected != saved:
        raise ValueError('语音编码已在此挂载目录初始化，请沿用原配置；新格式或码率需要使用新的独立 runtime 挂载目录')
    if not path.exists():
        atomic_write(path, selected)
    return selected
