// Live updates, like Sonarr's SignalR: one stream from the server says when a command changes and
// which of the pages' data changed, so they're asked for again then rather than every few seconds
import { useEffect } from 'react';
import { Command } from 'typings/InteractiveImport';
import { urlBase } from 'Utilities/api';
import queryClient from './queryClient';

type CommandListener = (command: Command) => void;

const commandListeners = new Set<CommandListener>();

// told of every command as it changes, until the function it returns is called
export function onCommand(listener: CommandListener) {
  commandListeners.add(listener);

  return () => {
    commandListeners.delete(listener);
  };
}

export function useServerEvents() {
  useEffect(() => {
    // the browser opens it again by itself when it drops
    const source = new EventSource(`${urlBase()}/api/v1/events`);

    source.addEventListener('changed', (event) => {
      const { keys } = JSON.parse((event as MessageEvent).data) as { keys: string[] };

      keys.forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));

      if (keys.includes('queue')) {
        // health counts the downloads that can't be imported
        queryClient.invalidateQueries({ queryKey: ['health'] });
      }
    });

    source.addEventListener('command', (event) => {
      const command = JSON.parse((event as MessageEvent).data) as Command;

      commandListeners.forEach((listener) => listener(command));
      queryClient.invalidateQueries({ queryKey: ['commands'] });
    });

    return () => source.close();
  }, []);
}
