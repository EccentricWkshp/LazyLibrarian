import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { QueueItem } from 'typings/Queue';
import { api } from 'Utilities/api';

// The live updates say when a download is added, imported or fails. Its progress is the download
// client's, so this asks for that every few seconds
const REFRESH = 5000;

export function useQueue() {
  return useQuery({
    queryKey: ['queue'],
    queryFn: () => api<QueueItem[]>('/queue'),
    refetchInterval: REFRESH,
  });
}

export interface RemovalOptions {
  removeFromClient: boolean;
  blocklist: boolean;
  skipRedownload: boolean;
}

export function useRemoveQueueItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ ids, options }: { ids: number[]; options: RemovalOptions }) =>
      Promise.all(
        ids.map((id) =>
          api<{ message: string }>(`/queue/${id}`, {
            method: 'DELETE',
            query: {
              removeFromClient: options.removeFromClient,
              blocklist: options.blocklist,
              skipRedownload: options.skipRedownload,
            },
          })
        )
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['queue'] }),
  });
}
