import { createContext, useContext, useEffect, useMemo, useState } from 'react';

import { DEMO_CHANNEL_ID, DEMO_USER_ID } from '../api/demoLink';
import { DEMO_MODE } from '../config';

const CHANNEL_KEY = DEMO_MODE
  ? 'polls-ui:demo-channel-id'
  : 'polls-ui:channel-id';
const USER_KEY = DEMO_MODE ? 'polls-ui:demo-user-id' : 'polls-ui:user-id';

const PollsContext = createContext(null);

function readStoredValue(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ?? fallback;
  } catch {
    return fallback;
  }
}

export function PollsProvider({ children }) {
  const [channelId, setChannelId] = useState(() =>
    readStoredValue(CHANNEL_KEY, DEMO_MODE ? DEMO_CHANNEL_ID : ''),
  );
  const [userId, setUserId] = useState(() =>
    readStoredValue(USER_KEY, DEMO_MODE ? DEMO_USER_ID : ''),
  );

  useEffect(() => {
    try {
      window.localStorage.setItem(CHANNEL_KEY, channelId);
    } catch {
      // La UI sigue funcionando sin persistencia.
    }
  }, [channelId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(USER_KEY, userId);
    } catch {
      // La UI sigue funcionando sin persistencia.
    }
  }, [userId]);

  const value = useMemo(
    () => ({
      channelId,
      userId,
      isConfigured: Boolean(channelId && userId),
      setContext: ({ channelId: nextChannelId, userId: nextUserId }) => {
        setChannelId(String(nextChannelId ?? '').trim());
        setUserId(String(nextUserId ?? '').trim());
      },
    }),
    [channelId, userId],
  );

  return <PollsContext.Provider value={value}>{children}</PollsContext.Provider>;
}

export function usePollsContext() {
  const context = useContext(PollsContext);
  if (!context) {
    throw new Error('usePollsContext must be used within PollsProvider');
  }
  return context;
}
