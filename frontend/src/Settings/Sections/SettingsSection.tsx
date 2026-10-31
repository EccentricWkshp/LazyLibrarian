// A Settings page, as Sonarr's: fieldsets of settings, Save Changes in the toolbar once something
// changed, and the advanced settings shown when asked for. What it shows is the section's fields
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, Eye, EyeOff, RefreshCw, Save, Settings2, X } from 'lucide-react';
import { ReactNode, useMemo, useState } from 'react';
import { runCommand } from 'App/commands';
import { showMessage } from 'App/messagesStore';
import queryClient from 'App/queryClient';
import {
  CheckInput,
  FormInputHelpText,
  FormLabel,
  FormRow,
  SelectInput,
  TextArea,
  TextInput,
} from 'Components/Form/Form';
import Button from 'Components/Link/Button';
import IconButton from 'Components/Link/IconButton';
import { Alert, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { PageToolbar, PageToolbarButton, PageToolbarSection } from 'Components/Page/Toolbar/PageToolbar';
import { remember, remembered } from 'Library/library';
import { api } from 'Utilities/api';
import {
  ConfigChoices,
  ConfigValue,
  Field,
  FieldValue,
  Group,
  INTERVAL_UNITS,
  Option,
  splitList,
  TestResult,
  Values,
} from './fields';
import styles from './SettingsSection.module.css';

function options(field: Field, choices: ConfigChoices | undefined, values: Values): Option[] {
  if (field.optionsFor) {
    return field.optionsFor(values);
  }

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

// switches for a list of values separated by commas
function FlagsInput({ value, flags, onChange }: { value: FieldValue; flags: Option[]; onChange: (value: string) => void }) {
  const on = splitList(value);

  return (
    <div className={styles.flags}>
      {flags.map((flag) => (
        <label key={flag.key} className={styles.check}>
          <CheckInput
            checked={on.includes(flag.key)}
            label={flag.value}
            onChange={(checked) =>
              onChange(
                flags
                  .map((each) => each.key)
                  .filter((key) => (key === flag.key ? checked : on.includes(key)))
                  .join(',')
              )
            }
          />
          <span>{flag.value}</span>
        </label>
      ))}
    </div>
  );
}

// the preferred languages: each language chosen adds all of its codes, other codes are typed
function LanguagesInput({
  value,
  languages,
  onChange,
}: {
  value: FieldValue;
  languages: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  const codes = splitList(value);
  const chosen = languages.filter((language) => splitList(language.value).some((code) => codes.includes(code)));
  const covered = new Set(chosen.flatMap((language) => splitList(language.value)));
  const other = codes.filter((code) => !covered.has(code));

  function update(next: typeof chosen, otherCodes: string[]) {
    onChange([...next.flatMap((language) => splitList(language.value)), ...otherCodes].join(', '));
  }

  return (
    <div className={styles.languages}>
      <div className={styles.chips}>
        {chosen.map((language) => (
          <span key={language.label} className={styles.chip} title={language.value}>
            {language.label}
            <IconButton
              name={X}
              size={12}
              title={`Take ${language.label} out`}
              onPress={() => update(chosen.filter((each) => each !== language), other)}
            />
          </span>
        ))}
      </div>
      <SelectInput
        className={styles.input}
        value=""
        values={[
          { key: '', value: 'Add a language' },
          ...languages
            .filter((language) => !chosen.includes(language))
            .map((language) => ({ key: language.label, value: language.label })),
        ]}
        onChange={(label) => {
          const language = languages.find((each) => each.label === label);
          if (language) {
            update([...chosen, language], other);
          }
        }}
      />
      <TextInput
        aria-label="Other language codes"
        className={styles.input}
        placeholder="Other codes, separated by commas: Unknown, or All for any language"
        value={other.join(', ')}
        onChange={(text) => update(chosen, splitList(text))}
      />
    </div>
  );
}

export function FieldInput({
  field,
  config,
  value,
  values,
  choices,
  onChange,
}: {
  field: Field;
  config: ConfigValue | undefined;
  value: FieldValue;
  values: Values;
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
    const shown = options(field, choices, values);
    // a value the choices don't have is still shown as it is
    const all = shown.some((option) => option.key === String(value))
      ? shown
      : [{ key: String(value), value: String(value) || 'None' }, ...shown];
    return (
      <SelectInput id={field.key} className={styles.input} value={String(value)} values={all} onChange={onChange} />
    );
  }

  if (field.input === 'flags') {
    return <FlagsInput value={value} flags={options(field, choices, values)} onChange={onChange} />;
  }

  if (field.input === 'languages') {
    return <LanguagesInput value={value} languages={choices?.bookLanguages ?? []} onChange={onChange} />;
  }

  if (field.input === 'textarea') {
    return (
      <TextArea
        id={field.key}
        className={styles.input}
        placeholder={field.placeholder}
        value={String(value ?? '')}
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
          step={kind === 'float' ? 'any' : undefined}
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

  const isPassword = field.input === 'password' || kind === 'password';
  return (
    <TextInput
      id={field.key}
      className={styles.input}
      type={isPassword ? 'password' : 'text'}
      autoComplete={isPassword ? 'new-password' : 'off'}
      placeholder={field.placeholder}
      value={String(value ?? '')}
      onChange={onChange}
    />
  );
}

export function FieldRows({
  fields,
  configs,
  values,
  changes = {},
  choices,
  showAdvanced,
  onChange,
}: {
  fields: Field[];
  configs: Record<string, ConfigValue>;
  values: Values;
  // what's changed and not saved, a key's test uses it
  changes?: Values;
  choices: ConfigChoices | undefined;
  showAdvanced: boolean;
  onChange: (key: string, value: FieldValue) => void;
}) {
  return (
    <>
      {fields
        .filter((field) => (showAdvanced || !field.advanced) && (!field.showIf || field.showIf(values)))
        .map((field) => {
          const config = configs[field.key];
          const input = (
            <FieldInput
              field={field}
              config={config}
              value={values[field.key]}
              values={values}
              choices={choices}
              onChange={(value) => onChange(field.key, value)}
            />
          );
          return (
            <FormRow key={field.key}>
              <div className={field.advanced ? styles.advancedRow : styles.row}>
                <div className={styles.labelColumn}>
                  {config?.kind === 'bool' ? null : <FormLabel htmlFor={field.key}>{field.label}</FormLabel>}
                </div>
                <div className={styles.inputColumn}>
                  {field.test ? (
                    <FieldTest field={field} changes={changes}>
                      {input}
                    </FieldTest>
                  ) : (
                    input
                  )}
                  {field.help ? <FormInputHelpText text={field.help} /> : null}
                </div>
              </div>
            </FormRow>
          );
        })}
    </>
  );
}

// a test with these settings as the page has them, the ones not changed as they're kept
function useConfigTest() {
  const [running, setRunning] = useState('');
  const [result, setResult] = useState<TestResult | null>(null);

  async function run(test: string, keys: string[], changes: Values) {
    setRunning(test);
    setResult(null);
    try {
      const tested = await api<TestResult>('/config/test', {
        method: 'POST',
        body: { test, values: Object.fromEntries(Object.entries(changes).filter(([key]) => keys.includes(key))) },
      });
      setResult(tested);
      if (tested.ok) {
        await queryClient.invalidateQueries({ queryKey: ['config'] });
      }
    } catch (error) {
      setResult({ ok: false, message: (error as Error).message, index: null });
    } finally {
      setRunning('');
    }
  }

  return { running, result, run };
}

function TestResultAlert({ result }: { result: TestResult | null }) {
  return result ? (
    <Alert kind={result.ok ? 'success' : 'danger'}>
      <span className={styles.testMessage}>{result.message || (result.ok ? 'It works' : "It didn't work")}</span>
    </Alert>
  ) : null;
}

// a key's test, beside it
function FieldTest({ field, changes, children }: { field: Field; changes: Values; children: ReactNode }) {
  const { running, result, run } = useConfigTest();
  const test = field.test!;

  return (
    <>
      <span className={styles.withTest}>
        {children}
        <Button isSpinning={!!running} onPress={() => run(test.test, [field.key, ...(test.testWith ?? [])], changes)}>
          {test.label}
        </Button>
      </span>
      <TestResultAlert result={result} />
    </>
  );
}

// a group's tests, with the group's settings as the page has them
function GroupTests({ group, changes }: { group: Group; changes: Values }) {
  const { running, result, run } = useConfigTest();
  const keys = group.fields.map((field) => field.key);

  return (
    <div className={styles.tests}>
      <div className={styles.testButtons}>
        {group.tests!.map((each) => (
          <Button key={each.test} isSpinning={running === each.test} onPress={() => run(each.test, keys, changes)}>
            {each.label}
          </Button>
        ))}
      </div>
      <TestResultAlert result={result} />
    </div>
  );
}

// a group's commands, run in the background with their progress in the sidebar
function GroupCommands({ group }: { group: Group }) {
  const [running, setRunning] = useState('');

  return (
    <div className={styles.tests}>
      {group.commands!.map((each) => (
        <div key={each.command}>
          <Button
            isSpinning={running === each.command}
            onPress={() => {
              setRunning(each.command);
              runCommand(each.command, {}, each.label).finally(() => setRunning(''));
            }}
          >
            {each.label}
          </Button>
          {each.help ? <FormInputHelpText text={each.help} /> : null}
        </div>
      ))}
    </div>
  );
}

export function SettingsGroups({
  groups,
  configs,
  values,
  changes,
  choices,
  showAdvanced,
  onChange,
}: {
  groups: Group[];
  configs: Record<string, ConfigValue>;
  values: Values;
  // what's changed and not saved, the tests use it
  changes: Values;
  choices: ConfigChoices | undefined;
  showAdvanced: boolean;
  onChange: (key: string, value: FieldValue) => void;
}) {
  return (
    <>
      {groups
        .filter((group) => (showAdvanced || !group.advanced) && (!group.showIf || group.showIf(values)))
        .map((group) => (
          <fieldset key={group.legend} className={styles.fieldset}>
            <legend className={styles.legend}>{group.legend}</legend>
            {group.help ? <p className={styles.groupHelp}>{group.help}</p> : null}
            <FieldRows
              fields={group.fields}
              configs={configs}
              values={values}
              changes={changes}
              choices={choices}
              showAdvanced={showAdvanced}
              onChange={onChange}
            />
            {group.tests ? <GroupTests group={group} changes={changes} /> : null}
            {group.commands ? <GroupCommands group={group} /> : null}
          </fieldset>
        ))}
    </>
  );
}

export function groupKeys(groups: Group[], uses: string[] = []) {
  return [...groups.flatMap((group) => group.fields.map((field) => field.key)), ...uses];
}

// settings by name from /config, with the changes made on the page and saving them
export function useSettings(title: string, keys: string[], usesChoices: boolean) {
  const [edited, setEdited] = useState<Values>({});
  const [isSaving, setIsSaving] = useState(false);
  const [messages, setMessages] = useState<string[]>([]);

  const { data, error, isLoading } = useQuery({
    queryKey: ['config', title],
    queryFn: () => api<ConfigValue[]>('/config', { query: { keys } }),
    enabled: keys.length > 0,
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
  const changes = Object.fromEntries(changed.map((key) => [key, edited[key]]));

  async function save() {
    setIsSaving(true);
    const id = `settings-${Date.now()}`;
    try {
      const result = await api<{ messages: string[] }>('/config', { method: 'PUT', body: { values: changes } });
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

  return {
    data,
    error,
    isLoading,
    configs,
    values,
    changed,
    changes,
    choices: choices.data,
    messages,
    isSaving,
    save,
    setValue: (key: string, value: FieldValue) => setEdited((current) => ({ ...current, [key]: value })),
  };
}

export function useShowAdvanced() {
  const [showAdvanced, setShowAdvanced] = useState(() => remembered('settings.advanced', '') === '1');
  return [
    showAdvanced,
    () => {
      setShowAdvanced(!showAdvanced);
      remember('settings.advanced', showAdvanced ? '' : '1');
    },
  ] as const;
}

export function SettingsToolbar({
  changed,
  isSaving,
  showAdvanced,
  onSave,
  onToggleAdvanced,
}: {
  changed: boolean;
  isSaving: boolean;
  showAdvanced: boolean;
  onSave: () => void;
  onToggleAdvanced: () => void;
}) {
  return (
    <PageToolbar>
      <PageToolbarSection>
        <PageToolbarButton
          label={changed ? 'Save Changes' : 'No Changes'}
          iconName={Save}
          isDisabled={!changed}
          isSpinning={isSaving}
          onPress={onSave}
        />
        <PageToolbarButton
          label={showAdvanced ? 'Hide Advanced' : 'Show Advanced'}
          iconName={Settings2}
          onPress={onToggleAdvanced}
        />
      </PageToolbarSection>
      <PageToolbarSection alignContent="right">
        <PageToolbarButton label="All Settings (old page)" iconName={ExternalLink} to="/config" />
      </PageToolbarSection>
    </PageToolbar>
  );
}

export function SettingsMessages({ messages }: { messages: string[] }) {
  return messages.length ? (
    <Alert kind="warning">
      {messages.map((message) => (
        <div key={message}>{message}</div>
      ))}
    </Alert>
  ) : null;
}

export function usesChoices(groups: Group[]) {
  return groups.some((group) =>
    group.fields.some((field) => field.choices || field.input === 'languages')
  );
}

interface SettingsSectionProps {
  title: string;
  groups: Group[];
  // other settings the fields are shown by
  uses?: string[];
}

function SettingsSection({ title, groups, uses = [] }: SettingsSectionProps) {
  const keys = useMemo(() => groupKeys(groups, uses), [groups, uses]);
  const settings = useSettings(title, keys, usesChoices(groups));
  const [showAdvanced, toggleAdvanced] = useShowAdvanced();

  return (
    <PageContent title={title}>
      <SettingsToolbar
        changed={settings.changed.length > 0}
        isSaving={settings.isSaving}
        showAdvanced={showAdvanced}
        onSave={settings.save}
        onToggleAdvanced={toggleAdvanced}
      />

      <PageContentBody>
        {settings.isLoading ? <LoadingIndicator /> : null}
        {settings.error ? (
          <Alert kind="danger">Failed to load the settings: {(settings.error as Error).message}</Alert>
        ) : null}
        <SettingsMessages messages={settings.messages} />
        {settings.data ? (
          <SettingsGroups
            groups={groups}
            configs={settings.configs}
            values={settings.values}
            changes={settings.changes}
            choices={settings.choices}
            showAdvanced={showAdvanced}
            onChange={settings.setValue}
          />
        ) : null}
      </PageContentBody>
    </PageContent>
  );
}

export default SettingsSection;
