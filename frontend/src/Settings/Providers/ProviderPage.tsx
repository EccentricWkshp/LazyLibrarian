// Sonarr's Download Clients, Indexers and Connect settings: a card for each one set up, a card to add
// another, and the options that go with them, saved from the toolbar
import { useQueries, useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { ReactNode, useMemo, useState } from 'react';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import { Modal, ModalBody, ModalContent, ModalHeader } from 'Components/Modal/Modal';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { ConfigValue, DOWNLOAD_TYPES, Group, splitList, Values } from 'Settings/Sections/fields';
import {
  groupKeys,
  SettingsGroups,
  SettingsMessages,
  SettingsToolbar,
  useSettings,
  useShowAdvanced,
} from 'Settings/Sections/SettingsSection';
import { api } from 'Utilities/api';
import cardStyles from '../Profiles/Profiles.module.css';
import EditProviderModal, { Editing } from './EditProviderModal';
import { isOn, Kind, kindKeys } from './kinds';
import styles from './Providers.module.css';

interface ListItem {
  index: number;
  name: string;
  values: ConfigValue[];
}

// another kind of card the page has, as Connect's webhooks
export interface OtherKind {
  name: string;
  description: string;
  protocol: string;
  onAdd: () => void;
}

interface ProviderPageProps {
  title: string;
  heading: string;
  kinds: Kind[];
  groups?: Group[];
  otherCards?: ReactNode;
  otherKinds?: OtherKind[];
  note?: ReactNode;
  children?: ReactNode;
}

interface Card {
  kind: Kind;
  index: number | null;
  name: string;
  values: Values;
  configs: Record<string, ConfigValue>;
}

function chips(card: Card) {
  const { kind, values } = card;
  if (!isOn(kind, values)) {
    return [<Label key="off">Disabled</Label>];
  }
  if (kind.triggers) {
    return kind.triggers
      .filter((trigger) => values[trigger.key])
      .map((trigger) => (
        <Label key={trigger.key} kind="success">
          {trigger.label}
        </Label>
      ));
  }
  const types = values.DLTYPES ?? values[`${kind.id}_DLTYPES`];
  const searched = DOWNLOAD_TYPES.filter((type) => splitList(types).includes(type.key));
  return [
    <Label key="on" kind="success">
      Enabled
    </Label>,
    ...searched.map((type) => <Label key={type.key}>{type.value}</Label>),
  ];
}

function AddProviderModal({
  isOpen,
  kinds,
  setUp,
  otherKinds,
  onAdd,
  onModalClose,
}: {
  isOpen: boolean;
  kinds: Kind[];
  setUp: Set<string>;
  otherKinds: OtherKind[];
  onAdd: (kind: Kind) => void;
  onModalClose: () => void;
}) {
  const all = [...otherKinds.map((other) => ({ other, kind: null })), ...kinds.map((kind) => ({ other: null, kind }))];
  const protocols = [...new Set(all.map((each) => (each.kind ?? each.other!).protocol))];

  return (
    <Modal isOpen={isOpen} size="large" onModalClose={onModalClose}>
      <ModalContent onModalClose={onModalClose}>
        <ModalHeader>Add</ModalHeader>
        <ModalBody>
          {protocols.map((protocol) => (
            <section key={protocol}>
              <h3 className={styles.protocol}>{protocol}</h3>
              <div className={styles.choices}>
                {all
                  .filter((each) => (each.kind ?? each.other!).protocol === protocol)
                  .map(({ kind, other }) => {
                    const shown = kind ?? other!;
                    // one that isn't a list is set up once
                    const isTaken = !!kind && !kind.list && setUp.has(kind.id);
                    return (
                      <Link
                        key={shown.name}
                        className={styles.choice}
                        isDisabled={isTaken}
                        onPress={() => (kind ? onAdd(kind) : other!.onAdd())}
                      >
                        <span className={styles.choiceName}>{shown.name}</span>
                        <span className={styles.choiceDescription}>
                          {isTaken ? 'Set up already' : shown.description}
                        </span>
                      </Link>
                    );
                  })}
              </div>
            </section>
          ))}
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}

function ProviderPage({ title, heading, kinds, groups = [], otherCards, otherKinds = [], note, children }: ProviderPageProps) {
  const flat = kinds.filter((kind) => !kind.list);
  const lists = kinds.filter((kind) => kind.list);
  // the kinds and groups are constants
  const keys = useMemo(() => [...new Set([...flat.flatMap(kindKeys), ...groupKeys(groups)])], [kinds, groups]);
  const settings = useSettings(title, keys, true);
  const [showAdvanced, toggleAdvanced] = useShowAdvanced();
  const [isAdding, setIsAdding] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);

  const listItems = useQueries({
    queries: lists.map((kind) => ({
      queryKey: ['config', 'list', kind.id],
      queryFn: () => api<ListItem[]>(`/config/list/${kind.id}`),
    })),
  });
  const schemas = useQuery({
    queryKey: ['config', 'list', 'schemas', title],
    queryFn: () =>
      Promise.all(lists.map((kind) => api<ConfigValue[]>(`/config/list/${kind.id}/schema`))).then((found) =>
        Object.fromEntries(lists.map((kind, index) => [kind.id, found[index]]))
      ),
    enabled: lists.length > 0,
  });

  const cards: Card[] = [];
  if (settings.data) {
    for (const kind of flat) {
      const address = kind.address ? settings.values[kind.address] : '';
      const isSetUp =
        isOn(kind, settings.values) ||
        (!!address && String(address) !== String(settings.configs[kind.address!]?.default ?? ''));
      if (isSetUp) {
        cards.push({ kind, index: null, name: kind.name, values: settings.values, configs: settings.configs });
      }
    }
  }
  lists.forEach((kind, position) => {
    for (const item of listItems[position].data ?? []) {
      const values = Object.fromEntries(item.values.map((value) => [value.key, value.value]));
      const configs = Object.fromEntries(item.values.map((value) => [value.key, value]));
      cards.push({ kind, index: item.index, name: String(values.DISPNAME || kind.name), values, configs });
    }
  });

  function add(kind: Kind) {
    setIsAdding(false);
    if (kind.list) {
      const schema = schemas.data?.[kind.id] ?? [];
      setEditing({
        kind,
        index: null,
        isNew: true,
        values: Object.fromEntries(schema.map((value) => [value.key, value.value])),
        configs: Object.fromEntries(schema.map((value) => [value.key, value])),
      });
    } else {
      setEditing({ kind, index: null, isNew: true, values: settings.values, configs: settings.configs });
    }
  }

  const error = settings.error ?? listItems.find((query) => query.error)?.error;

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
        {error ? <Alert kind="danger">Failed to load the settings: {(error as Error).message}</Alert> : null}
        <SettingsMessages messages={settings.messages} />
        <section className={styles.section}>
          <h2 className={cardStyles.legend}>{heading}</h2>
          <div className={cardStyles.cards}>
            {otherCards}
            {cards.map((card) => (
              <Link
                key={`${card.kind.id}-${card.index}`}
                className={cardStyles.card}
                onPress={() =>
                  setEditing({
                    kind: card.kind,
                    index: card.index,
                    isNew: false,
                    values: card.values,
                    configs: card.configs,
                  })
                }
              >
                <div className={cardStyles.cardName}>{card.name}</div>
                <div className={cardStyles.chips}>{chips(card)}</div>
                <div className={cardStyles.cardNote}>{card.kind.name}</div>
              </Link>
            ))}
            <Link className={cardStyles.addCard} onPress={() => setIsAdding(true)} aria-label={`Add to ${heading}`}>
              <Icon name={Plus} size={36} />
            </Link>
          </div>
        </section>
        {children}
        {settings.data && groups.length ? (
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
        {note ? <p className={cardStyles.note}>{note}</p> : null}
      </PageContentBody>

      <AddProviderModal
        isOpen={isAdding}
        kinds={kinds}
        setUp={new Set(cards.filter((card) => !card.kind.list).map((card) => card.kind.id))}
        otherKinds={otherKinds.map((other) => ({
          ...other,
          onAdd: () => {
            setIsAdding(false);
            other.onAdd();
          },
        }))}
        onAdd={add}
        onModalClose={() => setIsAdding(false)}
      />
      <EditProviderModal editing={editing} choices={settings.choices} onModalClose={() => setEditing(null)} />
    </PageContent>
  );
}

export default ProviderPage;
