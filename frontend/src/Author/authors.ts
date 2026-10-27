// What the author pages share: how a status shows, and changing or deleting authors
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import { api } from 'Utilities/api';

export const AUTHOR_STATUSES = [
  { key: 'Active', value: 'Active', hint: 'Their new books are wanted as Settings says' },
  { key: 'Wanted', value: 'Wanted', hint: 'Their new books are wanted' },
  { key: 'Paused', value: 'Paused', hint: "Their books aren't looked for" },
  { key: 'Ignored', value: 'Ignored', hint: 'Hidden, and their books are left alone' },
];

export function statusKind(status: string) {
  switch (status) {
    case 'Active':
    case 'Wanted':
      return 'success';
    case 'Paused':
      return 'warning';
    case 'Loading':
      return 'info';
    default:
      return 'default';
  }
}

function changed() {
  queryClient.invalidateQueries({ queryKey: ['author'] });
  queryClient.invalidateQueries({ queryKey: ['wanted'] });
}

async function tell<T>(id: string, work: () => Promise<T>, done: (result: T) => string, failed: string) {
  try {
    const result = await work();
    showMessage({ id, text: done(result), kind: 'success', isWorking: false });
    return result;
  } catch (error) {
    showMessage({ id, text: `${failed}: ${(error as Error).message}`, kind: 'danger', isWorking: false });
    return null;
  } finally {
    changed();
  }
}

export function setAuthorStatus(authorIds: string[], status: string) {
  return tell(
    `author-status-${Date.now()}`,
    () => api<{ changed: number }>('/author/editor', { method: 'PUT', body: { authorIds, status } }),
    (result) => `${result.changed} ${result.changed === 1 ? 'author' : 'authors'} set ${status}`,
    'Setting the status failed'
  );
}

export function deleteAuthors(authorIds: string[], deleteFiles: boolean) {
  return tell(
    `author-delete-${Date.now()}`,
    () => api<{ changed: number }>('/author/editor', { method: 'DELETE', body: { authorIds, deleteFiles } }),
    (result) => `${result.changed} ${result.changed === 1 ? 'author' : 'authors'} deleted`,
    'Deleting failed'
  );
}

export function removeContributorAuthors() {
  return tell(
    `author-contributors-${Date.now()}`,
    () => api<{ merged: number; removed: number }>('/author/contributors', { method: 'DELETE' }),
    (result) => `${result.removed} contributor ${result.removed === 1 ? 'author' : 'authors'} removed, ${result.merged} merged`,
    'Removing the contributor authors failed'
  );
}

export function setBookStatus(bookIds: string[], mediaTypes: string[], status: string) {
  return tell(
    `book-status-${Date.now()}`,
    () =>
      api<{ changed: number; failed: number }>('/book/status', { method: 'PUT', body: { bookIds, mediaTypes, status } }),
    (result) => `${result.changed} set ${status}${result.failed ? `, ${result.failed} not (in the library already)` : ''}`,
    'Setting the status failed'
  );
}
