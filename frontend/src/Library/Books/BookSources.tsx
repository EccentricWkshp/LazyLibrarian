// A book's ids at the info sources, which Fix Match on the book's page puts right
import { Label } from 'Components/Misc';
import { EditField } from 'Library/Edit/edit';
import styles from 'Library/Edit/Edit.module.css';

function BookSources({ ids, own }: { ids: Record<string, string>; own: string }) {
  const linked = Object.entries(ids).filter(([, id]) => id);

  return (
    <EditField label="Info Sources" help="Fix Match on the book's page links it to the right book at a source">
      <p className={styles.readonly}>
        {linked.length
          ? linked.map(([source, id]) => (
              <span key={source}>
                <Label kind={source === own ? 'primary' : 'default'}>{source}</Label> {id}{' '}
              </span>
            ))
          : 'Not linked to any'}
      </p>
    </EditField>
  );
}

export default BookSources;
