import profiles from '../campus_story_index/official_profiles.json';
export interface OfficialProfile { source_url: string; quote: string[]; photo: string; voices: string[]; introduction?: string; }
export const officialProfiles: Record<string, OfficialProfile> = profiles;
