import { useQuery } from '@tanstack/react-query';
import { HealthCheck } from 'typings/System';
import { api } from 'Utilities/api';

// the live updates say when the queue changes, which an import that's blocked shows in. The rest
// is settings and download clients, asked about now and then
const REFRESH = 60000;

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api<HealthCheck[]>('/health'),
    refetchInterval: REFRESH,
  });
}
