import { describe, expect, it } from "vitest";
import type { Poll } from "@/lib/graphql/types";
import { mergePolls, pollIdFromAnnouncement } from "@/lib/polls";

const poll: Poll = {
  pollId: "11111111-1111-4111-8111-111111111111",
  channelId: "c-1",
  authorId: "u-1",
  question: "¿Qué prefieres?",
  options: [],
  status: "open",
  durationMinutes: 5,
  closesAt: "2026-01-01T12:00:00Z",
  createdAt: "2026-01-01T11:55:00Z",
  closedAt: null,
  totalVotes: 0,
  creationError: null,
};

describe("Poll helpers", () => {
  it("extracts an announcement identifier without discovering or fetching polls", () => {
    expect(pollIdFromAnnouncement(`Encuesta del equipo\nPoll ID: ${poll.pollId}`)).toBe(poll.pollId);
    expect(pollIdFromAnnouncement("Un mensaje normal sin encuesta")).toBeNull();
  });

  it("merges Gateway polls with recently created polls by id", () => {
    const updated = { ...poll, status: "closed", totalVotes: 2 };
    expect(mergePolls([poll], [updated])).toEqual([updated]);
  });
});
