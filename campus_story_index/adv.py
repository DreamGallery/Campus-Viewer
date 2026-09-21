"""Parse Gakumas ADV commands without executing them, including nested branch scopes."""
from collections import Counter
import json
import re

from .io import canonical, digest

IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
FIELD_START = re.compile(r' +[A-Za-z_][A-Za-z_0-9]*=')
RELEVANT = {'message', 'narration', 'choicegroup', 'voice', 'branch', 'branchgroup',
            'timeline', 'unitytimelinestart', 'unitytimelineplay', 'unitytimelineend'}


def parse_command(text):
    def object_at(pos):
        if pos >= len(text) or text[pos] != '[':
            raise ValueError('Expected ADV object')
        match = IDENTIFIER.match(text, pos + 1)
        if not match:
            raise ValueError('Invalid ADV command name')
        result = {'tag': match[0]}
        pos = match.end()
        while pos < len(text) and text[pos] != ']':
            if text[pos] != ' ':
                raise ValueError('Expected ADV attribute separator')
            pos += 1
            match = IDENTIFIER.match(text, pos)
            if not match or match.end() >= len(text) or text[match.end()] != '=':
                raise ValueError('Invalid ADV attribute')
            key = match[0]
            pos = match.end() + 1
            if pos < len(text) and text[pos] == '[':
                value, pos = object_at(pos)
            else:
                start, depth = pos, 0
                while pos < len(text):
                    char = text[pos]
                    if char == '\\' and pos + 1 < len(text):
                        if text[pos + 1] == '{':
                            depth += 1
                        elif text[pos + 1] == '}':
                            depth -= 1
                            if depth < 0:
                                raise ValueError('Unbalanced ADV escaped object')
                        pos += 2
                        continue
                    if depth == 0 and (char == ']' or (char == ' ' and FIELD_START.match(text, pos))):
                        break
                    pos += 1
                if depth:
                    raise ValueError('Unclosed ADV escaped object')
                value = text[start:pos]
            if key not in result:
                result[key] = value
            elif isinstance(result[key], list):
                result[key].append(value)
            else:
                result[key] = [result[key], value]
        if pos >= len(text):
            raise ValueError('Unclosed ADV command')
        return result, pos + 1
    result, end = object_at(0)
    if end != len(text):
        raise ValueError('Trailing ADV input')
    return result


def clip_timing(command):
    if not command.get('clip'):
        return None
    text = command['clip'].replace(r'\{', '{').replace(r'\}', '}')
    value = json.loads(text)
    if '_startTime' not in value or '_duration' not in value:
        return None
    return {'start_ms': round(float(value['_startTime']) * 1000, 6),
            'duration_ms': round(float(value['_duration']) * 1000, 6),
            'clip_in_ms': round(float(value.get('_clipIn', 0)) * 1000, 6),
            'time_scale': float(value.get('_timeScale', 1))}


def parse_script(text, script_id):
    commands = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = re.match(r'\[(\w+)', line)
        if not match:
            raise ValueError(f'{script_id}:{line_number}: invalid ADV line')
        tag = match[1]
        try:
            command = parse_command(line) if tag in RELEVANT else {'tag': tag}
        except ValueError as exc:
            raise ValueError(f'{script_id}:{line_number}: {exc}') from exc
        command['source_line'] = line_number
        commands.append(command)
    scoped = []

    def consume(pos, count, scope):
        processed, branch_group, timeline = 0, 0, 0
        while pos < len(commands) and (count is None or processed < count):
            command = commands[pos]
            pos += 1
            processed += 1
            tag = command['tag']
            command['scope'] = '/'.join([*scope, f'timeline:{timeline}'])
            scoped.append(command)
            if tag == 'branchgroup':
                branch_group += 1
                children = int(command.get('groupLength', 0))
                for index in range(children):
                    # Some legacy groups count an inline choicegroup as a child.
                    if pos < len(commands) and commands[pos]['tag'] == 'choicegroup':
                        pos = consume(pos, 1, scope)
                        continue
                    if pos >= len(commands) or commands[pos]['tag'] != 'branch':
                        raise ValueError(f'{script_id}: malformed branch group')
                    branch = commands[pos]
                    pos += 1
                    scoped.append({**branch, 'scope': command['scope']})
                    pos = consume(pos, int(branch.get('groupLength', 0)),
                                  (*scope, f'group:{branch_group}', f'branch:{index}'))
            elif tag == 'branch':
                raise ValueError(f'{script_id}: branch outside branchgroup')
            elif tag == 'timeline':
                timeline += 1
        if count is not None and processed != count:
            raise ValueError(f'{script_id}: truncated branch body')
        return pos

    consume(0, None, ())
    texts, voices, embedded = [], [], []
    occurrences = Counter()
    for command in scoped:
        tag = command['tag']
        if tag == 'unitytimelinestart':
            embedded.append({'timeline_asset_id': command.get('timeline'),
                             'source_line': command['source_line'], 'scope': command['scope']})
        if tag not in ('message', 'narration', 'choicegroup', 'voice'):
            continue
        timing = clip_timing(command)
        common = {'source_line': command['source_line'], 'scope': command['scope'], 'timing': timing}
        if tag == 'voice':
            voices.append({**common, 'voice_ref': command.get('voice'),
                           'actor_id': command.get('actorId'), 'channel': command.get('channel'),
                           'volume': command.get('volume'), 'attributes': {k: v for k, v in command.items()
                               if k not in ('clip', 'source_line', 'scope', 'tag')}})
        else:
            if tag == 'choicegroup':
                choices = command.get('choices', [])
                choices = choices if isinstance(choices, list) else [choices]
                candidates = [('choice', '', c.get('text', ''), n) for n, c in enumerate(choices)]
            else:
                candidates = [(tag, command.get('name', '__narration__'), command.get('text', ''), None)]
            for kind, speaker, text_value, choice_index in candidates:
                if not text_value:
                    continue
                fingerprint = digest(canonical([kind, speaker, text_value]).encode())[:24]
                occurrences[fingerprint] += 1
                texts.append({**common, 'id': f'{script_id}/text/{fingerprint}/{occurrences[fingerprint]}',
                              'kind': kind, 'speaker': speaker, 'text': text_value,
                              'choice_index': choice_index, 'hide': command.get('hide'),
                              'is_inner': command.get('isInner')})
    for index, voice in enumerate(voices):
        voice['id'] = f'{script_id}/voice/{index + 1}'
    return {'texts': texts, 'voices': voices, 'embedded_timelines': embedded}
