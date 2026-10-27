export interface HealthCheck {
  source: string;
  type: 'error' | 'warning' | 'notice';
  message: string;
  // where to put it right, '' when there's nowhere
  link: string;
}

export interface DiskSpace {
  path: string;
  label: string;
  freeSpace: number;
  totalSpace: number;
}

export interface SystemStatus {
  appName: string;
  version: string;
  branch: string;
  installType: string;
  latestVersion: string;
  commitsBehind: number;
  databaseVersion: number;
  urlBase: string;
  authentication: string;
  isDocker: boolean;
  osName: string;
  osVersion: string;
  pythonVersion: string;
  appData: string;
  startupPath: string;
  databasePath: string;
  startTime: string;
}

export interface Backup {
  // its type and file name
  id: string;
  name: string;
  type: 'scheduled' | 'manual' | 'update' | 'restore';
  size: number;
  time: string;
}

export interface UpdateInfo {
  version: string;
  latestVersion: string;
  branch: string;
  installType: string;
  behind: number;
  // the changes since, newest first
  changes: string[];
  message: string;
  canInstall: boolean;
  whyNot: string;
  lastChecked: string | null;
  repo: string;
}

export interface LogEvent {
  time: string;
  level: string;
  thread: string;
  file: string;
  method: string;
  line: number;
  message: string;
}

export interface LogFile {
  filename: string;
  size: number;
  lastWriteTime: string;
}

export interface Task {
  name: string;
  taskName: string;
  // minutes
  interval: number;
  lastStartTime: string | null;
  lastExecution: string | null;
  // seconds
  lastDuration: number | null;
  nextExecution: string | null;
  isRunning: boolean;
  // why it doesn't run, '' when it does
  disabledReason: string;
}
