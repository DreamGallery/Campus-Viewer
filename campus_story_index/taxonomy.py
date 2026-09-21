"""Stable machine IDs, editable display labels. Source enums stay in provenance."""
ROOTS = {'main': '主线剧情', 'character': '角色剧情', 'support_card': '辅助卡剧情', 'event': '活动剧情', 'other': '其他剧情'}
LEAVES = {
    'character.dearness': '亲密度剧情',
    'character.idol_card': '角色卡剧情',
    'character.training_story': '培养主剧情',
    'character.training_growth': '培养成长剧情',
    'character.training_activity': '培养外出剧情',
    'character.training_school': '培养校园剧情',
    'character.training_business': '培养营业剧情',
    'character.training_stage': '培养阶段剧情',
    'character.training_transition': '培养行动过场',
    'character.training_lesson': '培养公开课程',
    'character.training_week': '培养周次过场',
    'character.birthday': '生日剧情',
    'character.live': 'Live 前后剧情',
    'character.extra': '角色其他剧情',
    'support_card.story': '辅助卡剧情',
    'event.story': '剧情活动',
    'event.tour': '巡演活动',
    'event.raid': '公会战活动',
    'event.april_fool': '愚人节活动',
    'event.high_score': '高分活动',
    'event.campaign': '限时企划剧情',
    'main.story': '主线剧情',
    'other.tutorial': '教程剧情',
    'other.training_shared': '培养共通剧情',
    'other.tower': '高塔剧情',
    'other.gacha': '招募演出',
    'other.unclassified': '待分类',
}
STORY_TYPES = {
    'Main': 'main.story', 'Birthday': 'character.birthday',
    'DearnessStory': 'character.dearness', 'ExtraDearnessStory': 'character.dearness',
    'CampaignDearnessStory': 'character.dearness', 'StoryEvent': 'event.story',
    'Tour': 'event.tour', 'GvgRaid': 'event.raid', 'AprilFool': 'event.april_fool',
}
PRODUCE_TYPES = {
    'Character': 'character.training_story', 'CharacterGrowth': 'character.training_growth',
    'IdolCard': 'character.idol_card', 'SupportCard': 'support_card.story',
    'StepActivityEvent': 'character.training_activity',
    'StepSchoolEvent': 'character.training_school',
    'StepBusinessEvent': 'character.training_business',
}
RELATION_CATEGORIES = {
    'eventCharacterProduceStoryIds': 'character.training_story',
    'eventCharacterGrowthProduceStoryIds': 'character.training_growth',
    'eventActivityProduceStoryIds': 'character.training_activity',
    'eventSchoolProduceStoryIds': 'character.training_school',
    'eventBusinessProduceStoryIds': 'character.training_business',
    'eventCampaignProduceStoryIds': 'event.campaign',
}
