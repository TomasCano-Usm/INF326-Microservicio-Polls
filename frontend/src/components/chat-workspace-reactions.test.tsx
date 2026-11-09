// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatWorkspace } from "@/components/chat-workspace";
import type { MessageReactions } from "@/lib/graphql/types";
import {
  ADD_REACTION_MUTATION,
  CHANNEL_QUERY,
  CHANNELS_QUERY,
  CHANNEL_WORKSPACE_QUERY,
  USER_QUERY,
} from "@/lib/graphql/operations";

const channel = { id: "channel-1", name: "general" };
const user = { id: "user-1", displayName: "Camila" };
const message = {
  id: "message-1",
  channelId: channel.id,
  authorId: user.id,
  content: "Hola equipo",
  createdAt: "2026-05-01T10:00:00Z",
  author: user,
};

function workspacePayload(reactions: unknown) {
  return {
    data: {
      messages: [{ ...message, reactions }],
      polls: [],
    },
  };
}

function seedDemoProfile() {
  window.localStorage.setItem("inf326-demo-profile", JSON.stringify(user));
  window.localStorage.setItem("inf326-selected-channel", channel.id);
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("ChatWorkspace reactions", () => {
  it("sends a selected emoji through addReaction and renders the refreshed count", async () => {
    seedDemoProfile();
    let reactionState: MessageReactions = {
      messageId: message.id,
      totalReactions: 0,
      summary: [],
      reactions: [],
    };
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { query: string; variables?: Record<string, string> };
      if (body.query === CHANNELS_QUERY) return Response.json({ data: { channels: [channel] } });
      if (body.query === USER_QUERY) return Response.json({ data: { user } });
      if (body.query === CHANNEL_QUERY) return Response.json({ data: { channel } });
      if (body.query === CHANNEL_WORKSPACE_QUERY) return Response.json(workspacePayload(reactionState));
      if (body.query === ADD_REACTION_MUTATION) {
        expect(body.variables).toMatchObject({
          messageId: message.id,
          channelId: channel.id,
          userId: user.id,
          reactionType: "heart",
        });
        reactionState = {
          messageId: message.id,
          totalReactions: 1,
          summary: [{ reactionType: "heart", count: 1 }],
          reactions: [{ id: "reaction-1", messageId: message.id, userId: user.id, reactionType: "heart", createdAt: "2026-05-01T10:01:00Z" }],
        };
        return Response.json({
          data: { addReaction: { id: "reaction-1", messageId: message.id, userId: user.id, reactionType: "heart", createdAt: "2026-05-01T10:01:00Z" } },
        });
      }
      throw new Error(`Unexpected GraphQL operation: ${body.query}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ChatWorkspace />);
    await screen.findByText("Hola equipo");
    fireEvent.click(screen.getByRole("button", { name: "Agregar reacción" }));
    fireEvent.click(screen.getByRole("button", { name: "❤️ Corazón" }));

    expect(await screen.findByRole("button", { name: "❤️ Corazón: 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "❤️ Corazón: 1" }).getAttribute("aria-pressed")).toBe("true");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/graphql")).toBe(true);
  });

  it("surfaces a duplicate-reaction 409 and does not show or render a false success", async () => {
    seedDemoProfile();
    const reactionState = {
      messageId: message.id,
      totalReactions: 0,
      summary: [],
      reactions: [],
    };
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { query: string };
      if (body.query === CHANNELS_QUERY) return Response.json({ data: { channels: [channel] } });
      if (body.query === USER_QUERY) return Response.json({ data: { user } });
      if (body.query === CHANNEL_QUERY) return Response.json({ data: { channel } });
      if (body.query === CHANNEL_WORKSPACE_QUERY) return Response.json(workspacePayload(reactionState));
      if (body.query === ADD_REACTION_MUTATION) {
        return Response.json({
          data: null,
          errors: [{
            message: "reaction already exists",
            extensions: { code: "UPSTREAM_ERROR", service: "reactions", status: 409 },
          }],
        });
      }
      throw new Error(`Unexpected GraphQL operation: ${body.query}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ChatWorkspace />);
    await screen.findByText("Hola equipo");
    fireEvent.click(screen.getByRole("button", { name: "Agregar reacción" }));
    fireEvent.click(screen.getByRole("button", { name: "❤️ Corazón" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("podría estar ya agregada");
    expect(screen.queryByRole("button", { name: "❤️ Corazón: 1" })).toBeNull();
    expect(fetchMock.mock.calls.filter(([, init]) => {
      const body = JSON.parse(String(init?.body)) as { query: string };
      return body.query === ADD_REACTION_MUTATION;
    })).toHaveLength(1);
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => {
      const body = JSON.parse(String(init?.body)) as { query: string };
      return body.query === CHANNEL_WORKSPACE_QUERY;
    }).length).toBeGreaterThan(1));
  });
});
