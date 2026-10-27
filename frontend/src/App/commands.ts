// Sonarr's commands: start one, show how it's going in the sidebar, and say how it ended. The page
// that started it can close meanwhile, so this isn't tied to it
import { Command } from 'typings/InteractiveImport';
import { api } from 'Utilities/api';
import { showMessage } from './messagesStore';
import queryClient from './queryClient';
import { onCommand } from './serverEvents';

// the live updates say how a command goes, this asks too in case they can't get through
const POLL = 5000;

// what to ask for again when a command is done, as it changes them
const CHANGES: Record<string, string[][]> = {
  ManualImport: [['queue'], ['manualimport'], ['wanted']],
  BookSearch: [['queue'], ['wanted'], ['author'], ['library']],
  MissingBookSearch: [['queue'], ['wanted']],
  ClearBlocklist: [['blocklist']],
  RunTask: [['tasks'], ['commands'], ['queue'], ['wanted'], ['history'], ['backups'], ['update'], ['library'], ['author']],
  Backup: [['backups']],
  CutoffUnmetSearch: [['queue'], ['wanted']],
  AddAuthor: [['lookup'], ['wanted'], ['author']],
  AddBook: [['lookup'], ['wanted'], ['author'], ['library']],
  RefreshAuthor: [['lookup'], ['wanted'], ['author']],
  AuthorSearch: [['queue'], ['wanted'], ['author']],
  RefreshBook: [['lookup'], ['wanted'], ['author'], ['library']],
  LibraryScan: [['library'], ['author'], ['wanted']],
};

function isDone(command: Command) {
  return command.status === 'completed' || command.status === 'failed';
}

export async function runCommand(name: string, body: Record<string, unknown>, label: string) {
  const id = `command-${name}-${Date.now()}`;
  // listening before it starts, a command that ends at once isn't missed
  const seen = new Map<number, Command>();
  let follow: ((command: Command) => void) | null = null;
  const stopListening = onCommand((command) => {
    seen.set(command.id, command);
    follow?.(command);
  });
  let timer = 0;

  showMessage({ id, text: label, kind: 'info', isWorking: true });

  try {
    const started = await api<Command>('/command', { method: 'POST', body: { name, ...body } });
    const command = await new Promise<Command>((resolve) => {
      let latest = started;

      follow = (update: Command) => {
        if (update.id !== started.id) {
          return;
        }

        latest = update;

        if (isDone(update)) {
          resolve(update);
        } else if (update.message && update.status === 'started') {
          showMessage({ id, text: update.message, kind: 'info', isWorking: true });
        }
      };

      follow(seen.get(started.id) ?? latest);
      timer = window.setInterval(() => {
        api<Command>(`/command/${started.id}`)
          .then((update) => follow?.(update))
          .catch(() => undefined);
      }, POLL);
    });

    // an import that left some out, or a search that found nothing, is worth a second look
    const result = command.result;
    const someFailed = Array.isArray(result) ? result.some((item) => !item.imported) : result?.found === 0;
    showMessage({
      id,
      text: command.message || `${label} ${command.status}`,
      kind: command.status === 'failed' ? 'danger' : someFailed ? 'warning' : 'success',
      isWorking: false,
    });

    return command;
  } catch (error) {
    showMessage({ id, text: `${label} failed: ${(error as Error).message}`, kind: 'danger', isWorking: false });

    return null;
  } finally {
    stopListening();
    window.clearInterval(timer);
    (CHANGES[name] ?? []).forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
  }
}
