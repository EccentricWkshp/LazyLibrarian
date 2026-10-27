// A magazine's or comic's own quality profile, or the default one of its kind: which formats its
// searches want, best first, and whether a better one replaces the file there is
import { useQuery } from '@tanstack/react-query';
import { SelectInput } from 'Components/Form/Form';
import { QualityProfile } from 'typings/Profiles';
import { api } from 'Utilities/api';
import { EditField } from './edit';

function ProfileField({
  mediaType,
  value,
  onChange,
}: {
  mediaType: 'magazine' | 'comic';
  value: number;
  onChange: (profileId: number) => void;
}) {
  const { data } = useQuery({
    queryKey: ['qualityprofile'],
    queryFn: () => api<QualityProfile[]>('/qualityprofile'),
  });
  const profiles = (data ?? []).filter((profile) => profile.mediaType === mediaType);
  const standard = profiles.find((profile) => profile.isDefault);

  return (
    <EditField
      id={`${mediaType}Profile`}
      label="Quality Profile"
      help="The formats its searches want, best first, and whether a better one replaces the file there is. See Settings, Profiles"
    >
      <SelectInput
        id={`${mediaType}Profile`}
        value={String(value)}
        values={[
          { key: '0', value: standard ? `The default, ${standard.name}` : 'The default' },
          ...profiles.map((profile) => ({ key: String(profile.id), value: profile.name })),
        ]}
        onChange={(profileId) => onChange(Number(profileId))}
      />
    </EditField>
  );
}

export default ProfileField;
