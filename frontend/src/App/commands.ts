// Sonarr's commands: start one, show how it's going in the sidebar, and say how it ended. The page
// that started it can close meanwhile, so this isn't tied to it
import { Command } from 'typings/InteractiveImport';
import { api } from 'Utilities/api';
import { showMessage } from './messagesStore';
import queryClient from './queryClient';

const POLL = 1000;

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

// what to ask for again when a command is done, as it changes them
const CHANGES: Record<string, string[][]> = {
  ManualImport: [['queue'], ['manualimport'], ['wanted']],
  BookSearch: [['queue'], ['wanted']],
  MissingBookSearch: [['queue'], ['wanted']],
  ClearBlocklist: [['blocklist']],
  RunTask: [['tasks'], ['commands'], ['queue'], ['wanted'], ['history']],
};

export async function runCommand(name: string, body: Record<string, unknown>, label: string) {
  const id = `command-${name}-${Date.now()}`;

  showMessage({ id, text: label, kind: 'info', isWorking: true });

  try {
    let command = await api<Command>('/command', { method: 'POST', body: { name, ...body } });

    while (command.status === 'queued' || command.status === 'started') {
      await wait(POLL);
      command = await api<Command>(`/command/${command.id}`);

      if (command.message && command.status === 'started') {
        showMessage({ id, text: command.message, kind: 'info', isWorking: true });
      }
    }

    // an import that left some out, or a search that found nothing, is worth a second look
    const result = command.result;
    const someFailed = Array.isArray(result)
      ? result.some((item) => !item.imported)
      : result?.found === 0;
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
    (CHANGES[name] ?? []).forEach((queryKey) => queryClient.invalidateQueries({ queryKey }));
  }
}
