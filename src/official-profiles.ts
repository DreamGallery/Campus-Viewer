import profiles from '../campus_story_index/official_profiles.json';
import type { Character } from './catalog';

const initialProfiles: Record<string, NonNullable<Character['official_profile']>> = profiles;

export function officialProfile(character: Pick<Character, 'id' | 'official_profile'>) {
  // Keep existing media available until an independently deployed updater publishes the field.
  return character.official_profile === undefined
    ? initialProfiles[character.id] ?? null
    : character.official_profile;
}
