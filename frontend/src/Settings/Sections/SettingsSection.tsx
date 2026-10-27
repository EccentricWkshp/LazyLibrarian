// A Settings page, as Sonarr's: fieldsets of settings, Save Changes in the toolbar once something
// changed, and the advanced settings shown when asked for. What it shows is the section's fields
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, Eye, EyeOff, RefreshCw, Save, Settings2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import { CheckInput, FormInputHelpText, FormLabel, FormRow, SelectInput, TextInput } from 'Components/Form/Form';
import IconButton from 'Components/Link/IconButton';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { remember, remembered } from 'Library/library';
import { api } from 'Utilities/api';
import { ConfigChoices, ConfigValue, Field, FieldValue, Group, INTERVAL_UNITS, Values } from './fields';
import styles from './SettingsSection.module.css';

interface SettingsSectionProps {
  title: string;
  groups: Group[];
  // other settings the fields are shown by
  uses?: string[];
}

function options(field: Field, choices: ConfigChoices | undefined) {
  if (field.options) {
    return field.options;
  }

  const found = field.choices ? choices?.[field.choices] : undefined;

  if (!found) {
    return [];
  }

  return (found as (string | { value: string; label: string; example: string })[]).map((choice) =>
    typeof choice === 'string'
      ? { key: choice, value: choice }
      : { key: choice.value, value: choice.example ? `${choice.example}  (${choice.value})` : choice.label || choice.value }
  );
}

function FieldInput({
  field,
  config,
  value,
  choices,
  onChange,
}: {
  field: Field;
  config: ConfigValue | undefined;
  value: FieldValue;
  choices: ConfigChoices | undefined;
  onChange: (value: FieldValue) => void;
}) {
  const kind = config?.kind ?? 'str';
  const [isMaking, setIsMaking] = useState(false);
  // an API key shown, it comes masked
  const [shownKey, setShownKey] = useState<string | null>(null);

  if (kind === 'bool') {
    return (
      <label className={styles.check}>
        <CheckInput checked={!!value} label={field.label} onChange={onChange} />
        <span>{field.label}</span>
      </label>
    );
  }

  if (field.input === 'select') {
    return (
      <SelectInput
        id={field.key}
        className={styles.input}
        value={String(value)}
        values={options(field, choices)}
        onChange={onChange}
      />
    );
  }

  if (kind === 'int' || kind === 'float' || kind === 'interval') {
    const unit = field.unit ?? (kind === 'interval' ? INTERVAL_UNITS[config?.unit ?? ''] : '');
    return (
      <span className={styles.number}>
        <TextInput
          id={field.key}
          type="number"
          className={styles.numberInput}
          value={String(value)}
          onChange={(next) => onChange(kind === 'float' ? next : next.replace(/[^0-9-]/g, ''))}
        />
        {unit ? <span className={styles.unit}>{unit}</span> : null}
      </span>
    );
  }

  if (field.input === 'apikey') {
    const readOnly = field.key === 'API_RO_KEY';
    return (
      <span className={styles.apiKey}>
        <TextInput
          id={field.key}
          className={styles.input}
          value={shownKey ?? String(value)}
          readOnly={true}
          onChange={onChange}
          onFocus={(event) => event.target.select()}
        />
        <IconButton
          name={shownKey ? EyeOff : Eye}
          title={shownKey ? 'Hide the key' : 'Show the key'}
          isDisabled={!value}
          onPress={() =>
            shownKey
              ? setShownKey(null)
              : api<{ key: string }>('/config/apikey/show', { method: 'POST', body: { readOnly } }).then((shown) =>
                  setShownKey(shown.key)
                )
          }
        />
        <IconButton
          name={RefreshCw}
          title="Make a new key, the old one stops working"
          isSpinning={isMaking}
          onPress={() => {
            setIsMaking(true);
            api<{ key: string }>('/config/apikey', { method: 'POST', body: { readOnly } })
              .then((made) => {
                setShownKey(made.key);
                return queryClient.invalidateQueries({ queryKey: ['config'] });
              })
              .finally(() => setIsMaking(false));
          }}
        />
      </span>
    );
  }

  return (
    <TextInput
      id={field.key}
      className={styles.input}
      type={field.input === 'password' || kind === 'password' ? 'password' : 'text'}
      autoComplete={field.input === 'password' || kind === 'password' ? 'new-password' : 'off'}
      placeholder={field.placeholder}
      value={String(value ?? '')}
      onChange={onChange}
    />
  );
}

function SettingsSection({ title, groups, uses = [] }: SettingsSectionProps) {
  const keys = useMemo(
    () => [...groups.flatMap((group) => group.fields.map((field) => field.key)), ...uses],
    [groups, uses]
  );
  const usesChoices = groups.some((group) => group.fields.some((field) => field.choices));
  const [edited, setEdited] = useState<Values>({});
  const [isSaving, setIsSaving] = useState(false);
  const [messages, setMessages] = useState<string[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(() => remembered('settings.advanced', '') === '1');

  const { data, error, isLoading } = useQuery({
    queryKey: ['config', title],
    queryFn: () => api<ConfigValue[]>('/config', { query: { keys } }),
  });
  const choices = useQuery({
    queryKey: ['config', 'choices'],
    queryFn: () => api<ConfigChoices>('/config/choices'),
    enabled: usesChoices,
  });

  const configs = useMemo(() => Object.fromEntries((data ?? []).map((item) => [item.key, item])), [data]);
  const values: Values = { ...Object.fromEntries((data ?? []).map((item) => [item.key, item.value])), ...edited };
  // a number comes back as one and is typed as text
  const changed = Object.keys(edited).filter((key) => String(edited[key]) !== String(configs[key]?.value));

  async function save() {
    setIsSaving(true);
    const id = `settings-${Date.now()}`;
    try {
      const result = await api<{ messages: string[] }>('/config', {
        method: 'PUT',
        body: { values: Object.fromEntries(changed.map((key) => [key, edited[key]])) },
      });
      setMessages(result.messages);
      // what wasn't saved shows as it is, the messages say why
      setEdited({});
      showMessage({
        id,
        text: result.messages.length ? `${title} saved, see the page for what wasn't` : `${title} saved`,
        kind: result.messages.length ? 'warning' : 'success',
        isWorking: false,
      });
      await queryClient.invalidateQueries({ queryKey: ['config'] });
    } catch (saveError) {
      showMessage({ id, text: `Saving failed: ${(saveError as Error).message}`, kind: 'danger', isWorking: false });
    } finally {
      setIsSaving(false);
    }
  }

  const shownGroups = groups.filter(
    (group) => (showAdvanced || !group.advanced) && (!group.showIf || group.showIf(values))
  );

  return (
    <PageContent title={title}>
      <PageToolbar>
        <PageToolbarSection>
          <PageToolbarButton
            label={changed.length ? 'Save Changes' : 'No Changes'}
            iconName={Save}
            isDisabled={!changed.length}
            isSpinning={isSaving}
            onPress={save}
          />
          <PageToolbarButton
            label={showAdvanced ? 'Hide Advanced' : 'Show Advanced'}
            iconName={Settings2}
            onPress={() => {
              setShowAdvanced(!showAdvanced);
              remember('settings.advanced', showAdvanced ? '' : '1');
            }}
          />
        </PageToolbarSection>
        <PageToolbarSection alignContent="right">
          <PageToolbarButton label="All Settings (old page)" iconName={ExternalLink} to="/config" />
        </PageToolbarSection>
      </PageToolbar>

      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the settings: {(error as Error).message}</Alert> : null}
        {messages.length ? (
          <Alert kind="warning">
            {messages.map((message) => (
              <div key={message}>{message}</div>
            ))}
          </Alert>
        ) : null}
        {data
          ? shownGroups.map((group) => (
              <fieldset key={group.legend} className={styles.fieldset}>
                <legend className={styles.legend}>{group.legend}</legend>
                {group.help ? <p className={styles.groupHelp}>{group.help}</p> : null}
                {group.fields
                  .filter((field) => (showAdvanced || !field.advanced) && (!field.showIf || field.showIf(values)))
                  .map((field) => {
                    const config = configs[field.key];
                    const isBool = config?.kind === 'bool';
                    return (
                      <FormRow key={field.key}>
                        <div className={field.advanced ? styles.advancedRow : styles.row}>
                          <div className={styles.labelColumn}>
                            {isBool ? null : <FormLabel htmlFor={field.key}>{field.label}</FormLabel>}
                          </div>
                          <div className={styles.inputColumn}>
                            <FieldInput
                              field={field}
                              config={config}
                              value={values[field.key]}
                              choices={choices.data}
                              onChange={(value) => setEdited((current) => ({ ...current, [field.key]: value }))}
                            />
                            {field.help ? <FormInputHelpText text={field.help} /> : null}
                          </div>
                        </div>
                      </FormRow>
                    );
                  })}
              </fieldset>
            ))
          : null}
      </PageContentBody>
    </PageContent>
  );
}

export default SettingsSection;
