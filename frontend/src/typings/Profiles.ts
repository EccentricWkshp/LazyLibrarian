export type ProfileMediaType = 'ebook' | 'audiobook' | 'magazine' | 'comic';

export interface ProfileItem {
  quality: string;
  name: string;
  allowed: boolean;
  // whether its files are imported, by the types settings
  imported: boolean;
}

export interface QualityProfile {
  id: number;
  name: string;
  mediaType: ProfileMediaType;
  // best first
  items: ProfileItem[];
  cutoff: string;
  upgradeAllowed: boolean;
  isDefault: boolean;
}
