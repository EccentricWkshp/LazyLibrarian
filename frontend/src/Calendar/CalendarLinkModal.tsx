// Sonarr's iCal link: the calendar's feed for a calendar app, with the API key, the read-only one
// when there is one, as the app can't log in
import { useQuery } from '@tanstack/react-query';
import { Copy } from 'lucide-react';
import { useState } from 'react';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import Link from 'Components/Link/Link';
import { CheckInput, FormInputHelpText, FormLabel, FormRow, TextInput } from 'Components/Form/Form';
import { Alert } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from 'Components/Modal/Modal';
import { ConfigValue } from 'Settings/Sections/fields';
import { api, urlBase } from 'Utilities/api';
import styles from './Calendar.module.css';

function CalendarLinkModal({ isOpen, onModalClose }: { isOpen: boolean; onModalClose: () => void }) {
  const [unmonitored, setUnmonitored] = useState(false);
  const [pastDays, setPastDays] = useState('7');
  const [futureDays, setFutureDays] = useState('28');
  const [isCopied, setIsCopied] = useState(false);

  const settings = useQuery({
    queryKey: ['config', 'calendar'],
    queryFn: () => api<ConfigValue[]>('/config', { query: { keys: ['API_ENABLED', 'API_RO_KEY'] } }),
    enabled: isOpen,
  });
  const values = Object.fromEntries((settings.data ?? []).map((found) => [found.key, found.value]));
  const readOnly = !!values.API_RO_KEY;
  const key = useQuery({
    queryKey: ['config', 'calendar', 'key', readOnly],
    queryFn: () => api<{ key: string }>('/config/apikey/show', { method: 'POST', body: { readOnly } }),
    enabled: isOpen && !!settings.data && !!values.API_ENABLED,
  });

  const query = new URLSearchParams({
    pastDays: String(Number(pastDays) || 0),
    futureDays: String(Number(futureDays) || 0),
    ...(unmonitored ? { unmonitored: 'true' } : {}),
    ...(key.data?.key ? { apikey: key.data.key } : {}),
  });
  const url = `${window.location.origin}${urlBase()}/feed/v1/calendar/LazyLibrarian.ics?${query}`;

  return (
    <Modal isOpen={isOpen} onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>iCal Link</ModalHeader>
        <ModalBody>
          {settings.data && !values.API_ENABLED ? (
            <Alert kind="warning">
              A calendar app needs the API, which is off: turn it on in{' '}
              <Link to="/settings/general">Settings, General</Link>
            </Alert>
          ) : null}
          <FormRow>
            <FormLabel>Unmonitored</FormLabel>
            <label className={styles.check}>
              <CheckInput checked={unmonitored} onChange={setUnmonitored} />
              Include the books and issues not looked for
            </label>
          </FormRow>
          <FormRow>
            <FormLabel htmlFor="pastDays">Days before</FormLabel>
            <TextInput id="pastDays" type="number" min={0} value={pastDays} onChange={setPastDays} />
          </FormRow>
          <FormRow>
            <FormLabel htmlFor="futureDays">Days after</FormLabel>
            <TextInput id="futureDays" type="number" min={0} value={futureDays} onChange={setFutureDays} />
          </FormRow>
          <FormRow>
            <FormLabel htmlFor="icalUrl">iCal feed</FormLabel>
            <div className={styles.feedUrl}>
              <TextInput id="icalUrl" value={url} readOnly={true} onChange={() => undefined} onFocus={(event) => event.target.select()} />
              <IconButton
                name={Copy}
                title={isCopied ? 'Copied' : 'Copy to the clipboard'}
                onPress={() => navigator.clipboard?.writeText(url).then(() => setIsCopied(true))}
              />
              <FormInputHelpText
                text={
                  readOnly
                    ? 'Has the read-only API key, so the calendar app can only read'
                    : 'Has the full API key: a read-only key in Settings, General would be safer to give a calendar app'
                }
                isWarning={!readOnly}
              />
            </div>
          </FormRow>
        </ModalBody>
        <ModalFooter>
          <a className={styles.subscribe} href={url.replace(/^https?:/, 'webcal:')}>
            Subscribe
          </a>
          <Button onPress={onModalClose}>Close</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  );
}

export default CalendarLinkModal;
