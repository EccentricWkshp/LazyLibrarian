// Sonarr's System, Tasks: the scheduled tasks, how often each runs and when it last and next
// does, to run one now, the tasks that only run when asked, and the queue of commands with how each ended
import { useQuery } from '@tanstack/react-query';
import { Check, Clock, LoaderCircle, RefreshCw, X } from 'lucide-react';
import { useState } from 'react';
import { runCommand } from 'App/commands';
import Icon from 'Components/Icon';
import IconButton from 'Components/Link/IconButton';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { Column, Table, TableRow, TableRowCell } from 'Components/Table/Table';
import { Command } from 'typings/InteractiveImport';
import { ManualTask, Task } from 'typings/System';
import { api } from 'Utilities/api';
import { formatDateTime, formatDuration, formatInterval, parseDate, relativeDate } from 'Utilities/format';
import styles from './Tasks.module.css';

// the live updates say when they change, this keeps the times in step
const REFRESH = 30000;

const TASK_COLUMNS: Column[] = [
  { name: 'name', label: 'Name' },
  { name: 'interval', label: 'Interval' },
  { name: 'lastExecution', label: 'Last Execution' },
  { name: 'lastDuration', label: 'Last Duration' },
  { name: 'nextExecution', label: 'Next Execution' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

const MANUAL_COLUMNS: Column[] = [
  { name: 'name', label: 'Name' },
  { name: 'lastExecution', label: 'Last Execution' },
  { name: 'lastDuration', label: 'Last Duration' },
  { name: 'actions', label: 'Actions', isVisuallyHidden: true },
];

const COMMAND_COLUMNS: Column[] = [
  { name: 'status', label: 'Status', isVisuallyHidden: true },
  { name: 'name', label: 'Name' },
  { name: 'queued', label: 'Queued' },
  { name: 'started', label: 'Started' },
  { name: 'duration', label: 'Duration' },
];

function TaskRow({ task }: { task: Task }) {
  const [isStarting, setIsStarting] = useState(false);
  const isDisabled = !!task.disabledReason;

  return (
    <TableRow className={isDisabled ? styles.disabled : undefined}>
      <TableRowCell>
        {task.taskName}
        {isDisabled ? <div className={styles.reason}>{task.disabledReason}</div> : null}
      </TableRowCell>
      <TableRowCell className={styles.nowrap}>{isDisabled ? '' : formatInterval(task.interval)}</TableRowCell>
      <TableRowCell className={styles.nowrap} title={task.lastExecution ? formatDateTime(task.lastExecution) : ''}>
        {task.isRunning ? 'Running' : task.lastExecution ? relativeDate(task.lastExecution) : ''}
      </TableRowCell>
      <TableRowCell className={styles.nowrap}>{formatDuration(task.lastDuration)}</TableRowCell>
      <TableRowCell className={styles.nowrap} title={task.nextExecution ? formatDateTime(task.nextExecution) : ''}>
        {task.nextExecution && !isDisabled ? relativeDate(task.nextExecution) : ''}
      </TableRowCell>
      <TableRowCell className={styles.actions}>
        <IconButton
          name={RefreshCw}
          title={isDisabled ? task.disabledReason : 'Execute'}
          isDisabled={isDisabled}
          isSpinning={isStarting || task.isRunning}
          onPress={() => {
            setIsStarting(true);
            runCommand('RunTask', { task: task.name }, task.taskName).finally(() => setIsStarting(false));
          }}
        />
      </TableRowCell>
    </TableRow>
  );
}

function ManualTaskRow({ task }: { task: ManualTask }) {
  const [isStarting, setIsStarting] = useState(false);

  return (
    <TableRow>
      <TableRowCell>
        {task.taskName}
        <div className={styles.reason}>{task.description}</div>
      </TableRowCell>
      <TableRowCell className={styles.nowrap} title={task.lastExecution ? formatDateTime(task.lastExecution) : ''}>
        {task.isRunning ? 'Running' : task.lastExecution ? relativeDate(task.lastExecution) : 'Never'}
      </TableRowCell>
      <TableRowCell className={styles.nowrap}>{formatDuration(task.lastDuration)}</TableRowCell>
      <TableRowCell className={styles.actions}>
        <IconButton
          name={RefreshCw}
          title="Execute"
          isSpinning={isStarting || task.isRunning}
          onPress={() => {
            setIsStarting(true);
            runCommand(task.command, {}, task.taskName).finally(() => setIsStarting(false));
          }}
        />
      </TableRowCell>
    </TableRow>
  );
}

function CommandStatus({ command }: { command: Command }) {
  if (command.status === 'completed') {
    return <Icon name={Check} kind="success" title="Completed" />;
  }

  if (command.status === 'failed') {
    return <Icon name={X} kind="danger" title="Failed" />;
  }

  if (command.status === 'started') {
    return <Icon name={LoaderCircle} isSpinning={true} title="Started" />;
  }

  return <Icon name={Clock} title="Queued" />;
}

function duration(command: Command) {
  const started = command.started ? parseDate(command.started) : null;

  if (!started) {
    return '';
  }

  const ended = command.ended ? parseDate(command.ended) : new Date();

  return formatDuration(((ended ?? new Date()).getTime() - started.getTime()) / 1000);
}

function Tasks() {
  const taskList = useQuery({
    queryKey: ['tasks'],
    queryFn: () => api<Task[]>('/system/task'),
    refetchInterval: REFRESH,
  });
  const manualList = useQuery({
    queryKey: ['tasks', 'manual'],
    queryFn: () => api<ManualTask[]>('/system/task/manual'),
    refetchInterval: REFRESH,
  });
  const commandList = useQuery({
    queryKey: ['commands'],
    queryFn: () => api<Command[]>('/command'),
    refetchInterval: REFRESH,
  });

  return (
    <PageContent title="Tasks">
      <PageContentBody>
        <h2 className={styles.legend}>Scheduled</h2>
        {taskList.isLoading ? <LoadingIndicator /> : null}
        {taskList.error ? <Alert kind="danger">Failed to load the tasks: {taskList.error.message}</Alert> : null}
        {taskList.data ? (
          <Table columns={TASK_COLUMNS}>
            {taskList.data.map((task) => (
              <TaskRow key={task.name} task={task} />
            ))}
          </Table>
        ) : null}

        <h2 className={styles.legend}>Manual</h2>
        {manualList.error ? <Alert kind="danger">Failed to load the tasks: {manualList.error.message}</Alert> : null}
        {manualList.data ? (
          <Table columns={MANUAL_COLUMNS}>
            {manualList.data.map((task) => (
              <ManualTaskRow key={task.command} task={task} />
            ))}
          </Table>
        ) : null}

        <h2 className={styles.legend}>Queue</h2>
        {commandList.error ? <Alert kind="danger">Failed to load the commands: {commandList.error.message}</Alert> : null}
        {commandList.data && !commandList.data.length ? (
          <Alert kind="info">Nothing has run since LazyLibrarian started</Alert>
        ) : null}
        {commandList.data?.length ? (
          <Table columns={COMMAND_COLUMNS}>
            {commandList.data.map((command) => (
              <TableRow key={command.id}>
                <TableRowCell className={styles.status}>
                  <CommandStatus command={command} />
                </TableRowCell>
                <TableRowCell>
                  {command.title}
                  {command.message ? <div className={styles.message}>{command.message}</div> : null}
                </TableRowCell>
                <TableRowCell className={styles.nowrap} title={formatDateTime(command.queued)}>
                  {relativeDate(command.queued)}
                </TableRowCell>
                <TableRowCell className={styles.nowrap} title={command.started ? formatDateTime(command.started) : ''}>
                  {command.started ? relativeDate(command.started) : ''}
                </TableRowCell>
                <TableRowCell className={styles.nowrap}>{duration(command)}</TableRowCell>
              </TableRow>
            ))}
          </Table>
        ) : null}
      </PageContentBody>
    </PageContent>
  );
}

export default Tasks;
