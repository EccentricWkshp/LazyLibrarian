import { create } from 'zustand';

interface AppState {
  // the sidebar on a small screen, where it slides over the page
  isSidebarVisible: boolean;
}

const appStore = create<AppState>(() => ({
  isSidebarVisible: false,
}));

export function useAppValue<K extends keyof AppState>(key: K) {
  return appStore((state) => state[key]);
}

export function setIsSidebarVisible(isSidebarVisible: boolean) {
  appStore.setState({ isSidebarVisible });
}

export function toggleIsSidebarVisible() {
  appStore.setState((state) => ({ isSidebarVisible: !state.isSidebarVisible }));
}
