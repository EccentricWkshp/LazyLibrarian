// Sonarr's Calendar: the books out on each day, with what's wanted of each format, and the
// magazines' issues, the ones there are and the ones missing or due. A month, a week or the days
// ahead as a list, and an iCal link for calendar apps
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import classNames from 'classnames';
import { BookOpen, CalendarDays, ChevronLeft, ChevronRight, Eye, EyeOff, Newspaper, Rss } from 'lucide-react';
import { useState } from 'react';
import Link from 'Components/Link/Link';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import {
  PageToolbar,
  PageToolbarButton,
  PageToolbarSection,
  PageToolbarSeparator,
} from 'Components/Page/Toolbar/PageToolbar';
import { Cover, remember, remembered } from 'Library/library';
import { CalendarEntry, CalendarState } from 'typings/Calendar';
import { api } from 'Utilities/api';
import { useDates } from 'Utilities/dates';
import CalendarLinkModal from './CalendarLinkModal';
import styles from './Calendar.module.css';

type View = 'month' | 'week' | 'agenda';

const VIEWS: { key: View; label: string }[] = [
  { key: 'month', label: 'Month' },
  { key: 'week', label: 'Week' },
  { key: 'agenda', label: 'Agenda' },
];
const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const AGENDA_DAYS = 31;

export const STATE_NAMES: Record<CalendarState, string> = {
  downloaded: 'Downloaded',
  downloading: 'Downloading',
  missing: 'Missing',
  unreleased: 'Unreleased',
  unmonitored: 'Unmonitored',
};
const FORMAT_NAMES = { ebook: 'eBook', audiobook: 'Audiobook' };

// days as yyyy-mm-dd in local time, which is what the books' dates are
function iso(day: Date) {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
}

function addDays(day: Date, days: number) {
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() + days);
}

function startOfWeek(day: Date) {
  return addDays(day, -day.getDay());
}

// the days a view shows around a day: a month's weeks, a week, or the days from it
function daysOf(view: View, day: Date): Date[] {
  let first = startOfWeek(day);
  let count = 7;
  if (view === 'month') {
    first = startOfWeek(new Date(day.getFullYear(), day.getMonth(), 1));
    const last = new Date(day.getFullYear(), day.getMonth() + 1, 0);
    count = Math.round((addDays(last, 6 - last.getDay()).getTime() - first.getTime()) / 86400000) + 1;
  } else if (view === 'agenda') {
    first = day;
    count = AGENDA_DAYS;
  }
  return Array.from({ length: count }, (_, n) => addDays(first, n));
}

function move(view: View, day: Date, direction: number) {
  if (view === 'month') {
    return new Date(day.getFullYear(), day.getMonth() + direction, 1);
  }
  return addDays(day, direction * (view === 'week' ? 7 : AGENDA_DAYS));
}

function heading(view: View, days: Date[], focus: Date) {
  const month = (day: Date, year = true) =>
    day.toLocaleDateString(undefined, { month: 'long', ...(year ? { year: 'numeric' } : {}) });
  if (view === 'month') {
    return month(focus);
  }
  const first = days[0];
  const last = days[days.length - 1];
  const short = (day: Date) => day.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return `${short(first)} - ${short(last)}, ${last.getFullYear()}`;
}

function entryLink(entry: CalendarEntry) {
  return entry.kind === 'book' ? `/book/${encodeURIComponent(entry.itemId)}` : `/magazine?title=${encodeURIComponent(entry.parentId)}`;
}

function entryTitle(entry: CalendarEntry) {
  if (entry.kind === 'book') {
    return entry.title;
  }
  return entry.kind === 'due' ? (entry.state === 'missing' ? 'Missing issue' : 'Issue due') : 'Issue';
}

function stateTitle(entry: CalendarEntry) {
  const formats = entry.formats.map((found) => `${FORMAT_NAMES[found.format]}: ${found.status}`);
  return [STATE_NAMES[entry.state], ...formats].join('\n');
}

function EventItem({ entry, isLarge }: { entry: CalendarEntry; isLarge: boolean }) {
  return (
    <Link to={entryLink(entry)} className={classNames(styles.event, styles[entry.state])} title={stateTitle(entry)}>
      {isLarge ? (
        <span className={styles.eventCover}>
          <Cover src={entry.image} size={20} icon={entry.kind === 'book' ? BookOpen : Newspaper} />
        </span>
      ) : null}
      <span className={styles.eventText}>
        <span className={styles.eventParent}>{entry.parent}</span>
        <span className={styles.eventTitle}>{entryTitle(entry)}</span>
        {isLarge && entry.series ? <span className={styles.eventSeries}>{entry.series}</span> : null}
        {isLarge && entry.formats.length > 1 ? (
          <span className={styles.formats}>
            {entry.formats.map((found) => (
              <span key={found.format} className={classNames(styles.formatDot, styles[found.state])}>
                {FORMAT_NAMES[found.format]}
              </span>
            ))}
          </span>
        ) : null}
      </span>
    </Link>
  );
}

function AgendaItem({ entry }: { entry: CalendarEntry }) {
  return (
    <div className={classNames(styles.agendaItem, styles[entry.state])}>
      <span className={styles.agendaCover}>
        <Cover src={entry.image} size={24} icon={entry.kind === 'book' ? BookOpen : Newspaper} />
      </span>
      <div className={styles.agendaText}>
        <Link to={entryLink(entry)} className={styles.agendaTitle}>
          {entry.kind === 'book' ? entry.title : entry.parent}
        </Link>
        {entry.subtitle ? <span className={styles.muted}>: {entry.subtitle}</span> : null}
        <div className={styles.muted}>
          {entry.kind === 'book' ? (
            <Link to={`/author/${encodeURIComponent(entry.parentId)}`}>{entry.parent}</Link>
          ) : (
            entryTitle(entry)
          )}
          {entry.series ? ` · ${entry.series}` : ''}
        </div>
      </div>
      <div className={styles.agendaStates}>
        {entry.formats.length ? (
          entry.formats.map((found) => (
            <span key={found.format} className={classNames(styles.stateLabel, styles[found.state])}>
              {FORMAT_NAMES[found.format]}: {found.status}
            </span>
          ))
        ) : (
          <span className={classNames(styles.stateLabel, styles[entry.state])}>{STATE_NAMES[entry.state]}</span>
        )}
      </div>
    </div>
  );
}

function Calendar() {
  const [view, setView] = useState<View>(() => {
    const saved = remembered('calendar.view', 'month');
    return VIEWS.some((found) => found.key === saved) ? (saved as View) : 'month';
  });
  const [focus, setFocus] = useState(() => new Date());
  const [unmonitored, setUnmonitored] = useState(() => remembered('calendar.unmonitored', '') === 'true');
  const [isLinkOpen, setIsLinkOpen] = useState(false);
  const dates = useDates();
  const days = daysOf(view, focus);
  const start = iso(days[0]);
  const end = iso(days[days.length - 1]);
  const today = iso(new Date());

  const { data, error, isLoading, isFetching } = useQuery({
    queryKey: ['library', 'calendar', start, end, unmonitored],
    queryFn: () => api<CalendarEntry[]>('/calendar', { query: { start, end, unmonitored: String(unmonitored) } }),
    placeholderData: keepPreviousData,
  });

  const byDay = new Map<string, CalendarEntry[]>();
  (data ?? []).forEach((entry) => byDay.set(entry.date, [...(byDay.get(entry.date) ?? []), entry]));

  function chooseView(next: View) {
    setView(next);
    remember('calendar.view', next);
  }

  return (
    <PageContent title="Calendar">
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton label="iCal Link" iconName={Rss} onPress={() => setIsLinkOpen(true)} />
          <PageToolbarSeparator />
          <PageToolbarButton
            label={unmonitored ? 'Hide Unmonitored' : 'Show Unmonitored'}
            iconName={unmonitored ? EyeOff : Eye}
            onPress={() => {
              setUnmonitored(!unmonitored);
              remember('calendar.unmonitored', String(!unmonitored));
            }}
          />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        <div className={styles.header}>
          <div className={styles.navigation}>
            <button type="button" className={styles.navButton} aria-label="Before" onClick={() => setFocus(move(view, focus, -1))}>
              <ChevronLeft size={18} />
            </button>
            <button type="button" className={styles.navButton} aria-label="After" onClick={() => setFocus(move(view, focus, 1))}>
              <ChevronRight size={18} />
            </button>
            <button type="button" className={styles.todayButton} onClick={() => setFocus(new Date())}>
              <CalendarDays size={15} /> Today
            </button>
          </div>
          <h2 className={styles.title}>
            {heading(view, days, focus)}
            {isFetching && !isLoading ? <span className={styles.fetching}>…</span> : null}
          </h2>
          <div className={styles.views} role="group" aria-label="View">
            {VIEWS.map((found) => (
              <button
                key={found.key}
                type="button"
                className={classNames(styles.viewButton, view === found.key && styles.viewActive)}
                aria-pressed={view === found.key}
                onClick={() => chooseView(found.key)}
              >
                {found.label}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">{(error as Error).message}</Alert> : null}

        {data && view !== 'agenda' ? (
          <div className={classNames(styles.grid, view === 'week' && styles.week)}>
            {DAY_NAMES.map((name) => (
              <div key={name} className={styles.dayName}>
                {name}
              </div>
            ))}
            {days.map((day) => {
              const key = iso(day);
              const isOtherMonth = view === 'month' && day.getMonth() !== focus.getMonth();
              return (
                <div
                  key={key}
                  className={classNames(styles.day, key === today && styles.today, isOtherMonth && styles.otherMonth)}
                >
                  <div className={styles.dayNumber}>
                    {view === 'week' ? dates.date(key) : day.getDate()}
                  </div>
                  {(byDay.get(key) ?? []).map((entry) => (
                    <EventItem key={entry.id} entry={entry} isLarge={view === 'week'} />
                  ))}
                </div>
              );
            })}
          </div>
        ) : null}

        {data && view === 'agenda' ? (
          <div className={styles.agenda}>
            {days
              .filter((day) => byDay.has(iso(day)))
              .map((day) => (
                <div key={iso(day)} className={styles.agendaDay}>
                  <div className={classNames(styles.agendaDate, iso(day) === today && styles.agendaToday)}>
                    <span>{day.toLocaleDateString(undefined, { weekday: 'long' })}</span>
                    <span>{dates.date(iso(day))}</span>
                  </div>
                  <div className={styles.agendaItems}>
                    {(byDay.get(iso(day)) ?? []).map((entry) => (
                      <AgendaItem key={entry.id} entry={entry} />
                    ))}
                  </div>
                </div>
              ))}
            {!data.length ? <Alert kind="info">Nothing is out in the next {AGENDA_DAYS} days</Alert> : null}
          </div>
        ) : null}

        <div className={styles.legend}>
          {(Object.keys(STATE_NAMES) as CalendarState[])
            .filter((state) => unmonitored || state !== 'unmonitored')
            .map((state) => (
              <span key={state} className={styles.legendItem}>
                <span className={classNames(styles.legendSwatch, styles[state])} />
                {STATE_NAMES[state]}
              </span>
            ))}
        </div>
      </PageContentBody>
      <CalendarLinkModal isOpen={isLinkOpen} onModalClose={() => setIsLinkOpen(false)} />
    </PageContent>
  );
}

export default Calendar;
