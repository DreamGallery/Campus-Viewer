"""Publish only explicitly linked and verified voice clips for the chapter reader."""
import json
from pathlib import PurePosixPath


def chapter_voices(root, summary):
    if not summary or not summary.get('path'):
        return {'source_sha256': None, 'lines': []}
    path = (root / summary['path']).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Voice index outside root')
    data = json.loads(path.read_text())
    events = {event['id']: event for event in data.get('voice_events', [])}
    lines = []
    for line in data.get('lines', []):
        if line.get('csv_match_status') != 'matched' or line.get('audio_status') != 'linked':
            continue
        clips = []
        for event_id in line.get('voice_event_ids', []):
            event = events.get(event_id, {})
            for variant in event.get('audio_variants', []):
                audio = variant.get('audio_path', '')
                parsed = PurePosixPath(audio)
                if variant.get('status') != 'verified' or not audio.startswith('clips/') or '..' in parsed.parts or parsed.suffix != '.wav':
                    continue
                clip = {'url': '/audio/' + audio.removeprefix('clips/'), 'label': variant.get('voice_ref', '')}
                if clip not in clips:
                    clips.append(clip)
        if clips:
            lines.append({'record_index': line['csv_record_index'], 'text': line['text'], 'speaker': line['speaker'], 'clips': clips})
    return {'source_sha256': data.get('sources', {}).get('csv_sha256'), 'lines': lines}
