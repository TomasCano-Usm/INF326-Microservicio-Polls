import type { Poll } from "@/lib/graphql/types";

const ANNOUNCEMENT_POLL_ID = /^\s*Poll ID:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s*$/im;

export function pollIdFromAnnouncement(content: string): string | null {
  return content.match(ANNOUNCEMENT_POLL_ID)?.[1] ?? null;
}

export function mergePolls(...groups: Poll[][]): Poll[] {
  const byId = new Map<string, Poll>();
  for (const poll of groups.flat()) byId.set(poll.pollId, poll);
  return [...byId.values()].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-CL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function pollStatusLabel(status: string): string {
  switch (status) {
    case "pending_announcement":
      return "Pendiente de publicación";
    case "open":
      return "Abierta";
    case "closed":
      return "Cerrada";
    case "creation_failed":
      return "No se pudo publicar";
    default:
      return "Estado desconocido";
  }
}
