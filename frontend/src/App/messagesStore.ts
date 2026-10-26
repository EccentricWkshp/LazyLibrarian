// What's happening with commands, shown at the foot of the sidebar like Sonarr's messages
import { create } from 'zustand';

export type MessageKind = 'info' | 'success' | 'warning' | 'danger';

export interface Message {
  id: string;
  text: string;
  kind: MessageKind;
  isWorking: boolean;
}

const messagesStore = create<{ messages: Message[] }>(() => ({ messages: [] }));

// a finished message stays this long
const HIDE_AFTER = 10000;

export function useMessages() {
  return messagesStore((state) => state.messages);
}

export function showMessage(message: Message) {
  messagesStore.setState((state) => ({
    messages: [...state.messages.filter((m) => m.id !== message.id), message],
  }));

  if (!message.isWorking) {
    window.setTimeout(() => hideMessage(message.id), HIDE_AFTER);
  }
}

export function hideMessage(id: string) {
  messagesStore.setState((state) => ({ messages: state.messages.filter((m) => m.id !== id) }));
}
