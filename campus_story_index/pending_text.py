"""Conservative hints for scripts arriving before story/card masterdata."""
import re


def filename_hints(script_id, character_ids):
    tokens = set(re.split(r'[_-]', script_id))
    characters = sorted(tokens & set(character_ids))
    category = None
    images = []
    card = re.fullmatch(r'adv_(cidol-[a-z0-9]+-\d+-\d+)_\d+', script_id)
    support = re.fullmatch(r'adv_(csprt-\d+-\d+)_\d+', script_id)
    if card:
        category = 'character.idol_card'
        images = [(f'img_general_{card[1]}_{stage}-full', 9 / 16) for stage in (0, 1)]
    elif support:
        category = 'support_card.story'
        images = [(f'img_general_{support[1]}_full', 16 / 9)]
    else:
        prefixes = [('adv_dear_', 'character.dearness'), ('adv_birthday_', 'character.birthday'),
                    ('adv_pstory_', 'character.training_story'), ('adv_pgrowth_', 'character.training_growth'),
                    ('adv_event_highscore_', 'event.high_score'), ('adv_event_', 'event.story'),
                    ('adv_tutorial_', 'other.tutorial'), ('adv_tower-', 'other.tower'),
                    ('adv_gasha_', 'other.gacha'), ('adv_unit_', 'main.story')]
        category = next((value for prefix, value in prefixes if script_id.startswith(prefix)), None)
        if script_id.startswith('adv_pevent_') and '_sales_' in script_id:
            category = 'character.training_business'
    return {'category_id': category, 'character_ids': characters, 'images': images}
