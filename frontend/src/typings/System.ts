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
