export const TEST_PREFIX = '[TEST-UI]';

export function formatDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('es-CL', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function shortId(value, length = 8) {
  if (!value) return '—';
  const text = String(value);
  return text.length <= length ? text : `${text.slice(0, length)}…`;
}

export function errorMessage(error) {
  if (!error) return '';
  return (
    error.graphQLErrors?.[0]?.message ||
    error.networkError?.message ||
    error.message ||
    'Error inesperado.'
  );
}

export function pollStatusMeta(status) {
  switch (status) {
    case 'open':
      return { label: 'Abierta', colorScheme: 'green' };
    case 'closed':
      return { label: 'Cerrada', colorScheme: 'gray' };
    case 'pending_announcement':
      return { label: 'Anunciando', colorScheme: 'orange' };
    case 'creation_failed':
      return { label: 'Error de creación', colorScheme: 'red' };
    default:
      return { label: status || 'Desconocido', colorScheme: 'gray' };
  }
}

export function applyTestPrefix(value, enabled) {
  const text = value.trim();
  if (!enabled || !text || text.startsWith(TEST_PREFIX)) return text;
  return `${TEST_PREFIX} ${text}`;
}

export function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
