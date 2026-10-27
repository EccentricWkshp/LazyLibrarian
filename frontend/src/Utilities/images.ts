import { urlBase } from './api';

// an image the database has: a web address, or a file the old pages serve, like cache/author/x.jpg
export function imageUrl(path: string) {
  if (!path) {
    return '';
  }

  if (/^https?:\/\//.test(path)) {
    return path;
  }

  return `${urlBase()}/${path.replace(/^\/+/, '')}`;
}
