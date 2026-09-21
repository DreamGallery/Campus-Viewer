import unittest
from campus_story_index.pending_text import filename_hints
from campus_story_index.web_assets import image_requests


class PendingTextTests(unittest.TestCase):
    def test_exact_card_resource_hints_without_masterdata(self):
        card = filename_hints('adv_cidol-hski-3-999_01', ['hski', 'ttmr'])
        self.assertEqual(card['category_id'], 'character.idol_card')
        self.assertEqual(card['character_ids'], ['hski'])
        self.assertEqual(card['images'][0][0], 'img_general_cidol-hski-3-999_0-full')
        support = filename_hints('adv_csprt-3-9999_03', ['hski'])
        self.assertEqual(support['category_id'], 'support_card.story')
        self.assertEqual(support['character_ids'], [])
        self.assertEqual(support['images'][0][0], 'img_general_csprt-3-9999_full')
        planned = image_requests({'characters': [], 'groups': [], 'scripts': [{'id': 'adv_csprt-3-9999_03'}]})
        self.assertIn('img_general_csprt-3-9999_full', planned)

    def test_unknown_names_do_not_guess_cards(self):
        hints = filename_hints('adv_something_hskiish', ['hski'])
        self.assertIsNone(hints['category_id'])
        self.assertEqual(hints['character_ids'], [])
        self.assertEqual(hints['images'], [])
