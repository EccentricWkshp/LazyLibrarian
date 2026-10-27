// Sonarr's Settings, Profiles: the quality profiles for eBooks and audiobooks, each a card with the
// qualities it wants, best first, and the cutoff it upgrades until. The default one is what the
// searches use
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useState } from 'react';
import Icon from 'Components/Icon';
import Link from 'Components/Link/Link';
import { Alert, Label, LoadingIndicator } from 'Components/Misc';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import { ProfileMediaType, QualityProfile } from 'typings/Profiles';
import { api } from 'Utilities/api';
import EditQualityProfileModal from './EditQualityProfileModal';
import styles from './Profiles.module.css';

const SECTIONS: { mediaType: ProfileMediaType; title: string }[] = [
  { mediaType: 'ebook', title: 'eBook Profiles' },
  { mediaType: 'audiobook', title: 'Audiobook Profiles' },
];

function ProfileCard({ profile, onPress }: { profile: QualityProfile; onPress: () => void }) {
  const allowed = profile.items.filter((item) => item.allowed);

  return (
    <Link className={styles.card} onPress={onPress}>
      <div className={styles.cardName}>
        {profile.name}
        {profile.isDefault ? <Label kind="primary">Default</Label> : null}
      </div>
      <div className={styles.chips}>
        {allowed.map((item) => (
          <Label
            key={item.quality}
            kind={profile.upgradeAllowed && item.quality === profile.cutoff ? 'info' : 'default'}
            title={profile.upgradeAllowed && item.quality === profile.cutoff ? 'Upgrade until' : undefined}
          >
            {item.name}
          </Label>
        ))}
      </div>
      <div className={styles.cardNote}>
        {profile.upgradeAllowed
          ? `Upgrades until ${allowed.find((item) => item.quality === profile.cutoff)?.name ?? profile.cutoff}`
          : 'No upgrades'}
      </div>
    </Link>
  );
}

function Profiles() {
  const [editing, setEditing] = useState<QualityProfile | null>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ['qualityprofile'],
    queryFn: () => api<QualityProfile[]>('/qualityprofile'),
  });

  async function add(mediaType: ProfileMediaType) {
    setEditing(await api<QualityProfile>('/qualityprofile/schema', { query: { mediaType } }));
  }

  return (
    <PageContent title="Profiles">
      <PageContentBody>
        {isLoading ? <LoadingIndicator /> : null}
        {error ? <Alert kind="danger">Failed to load the profiles: {(error as Error).message}</Alert> : null}
        {data
          ? SECTIONS.map(({ mediaType, title }) => (
              <section key={mediaType}>
                <h2 className={styles.legend}>{title}</h2>
                <div className={styles.cards}>
                  {data
                    .filter((profile) => profile.mediaType === mediaType)
                    .map((profile) => (
                      <ProfileCard key={profile.id} profile={profile} onPress={() => setEditing(profile)} />
                    ))}
                  <Link className={styles.addCard} onPress={() => add(mediaType)} aria-label={`Add ${title}`}>
                    <Icon name={Plus} size={36} />
                  </Link>
                </div>
              </section>
            ))
          : null}
        <p className={styles.note}>
          A quality is a format. The search takes the best quality the default profile wants, turns down a release
          worse than the file there is, and with upgrades allowed keeps looking for a better one until the cutoff, see
          Wanted, Cutoff Unmet. A release that doesn't say its format is Unknown.
        </p>
      </PageContentBody>

      <EditQualityProfileModal isOpen={!!editing} profile={editing} onModalClose={() => setEditing(null)} />
    </PageContent>
  );
}

export default Profiles;
