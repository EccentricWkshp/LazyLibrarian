// How many health problems there are, beside System in the sidebar, like Sonarr's
import { Label } from 'Components/Misc';
import { useHealth } from './useHealth';

function HealthStatus() {
  const { data } = useHealth();
  const problems = (data ?? []).filter((check) => check.type !== 'notice');

  if (!problems.length) {
    return null;
  }

  return (
    <Label kind={problems.some((check) => check.type === 'error') ? 'danger' : 'warning'}>{problems.length}</Label>
  );
}

export default HealthStatus;
