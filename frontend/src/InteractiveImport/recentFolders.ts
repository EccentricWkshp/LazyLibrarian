// The folders imported from lately, like Sonarr's recent folders, kept in this browser
const KEY = 'lazylibrarian.manualImport.recentFolders';
const KEEP = 5;

export function recentFolders(): string[] {
  try {
    const folders = JSON.parse(window.localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(folders) ? folders.filter((folder) => typeof folder === 'string') : [];
  } catch {
    return [];
  }
}

export function addRecentFolder(folder: string) {
  try {
    const folders = [folder, ...recentFolders().filter((recent) => recent !== folder)].slice(0, KEEP);
    window.localStorage.setItem(KEY, JSON.stringify(folders));
  } catch {
    // private windows and blocked storage just don't remember
  }
}
