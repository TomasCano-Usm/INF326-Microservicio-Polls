// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Message } from "@/lib/graphql/types";
import { ReactionControls } from "@/components/reaction-controls";

const message: Message = {
  id: "message-1",
  channelId: "channel-1",
  authorId: "user-1",
  content: "Hola equipo",
  createdAt: "2026-05-01T10:00:00Z",
  author: { id: "user-1", displayName: "Camila" },
  reactions: {
    messageId: "message-1",
    totalReactions: 4,
    summary: [
      { reactionType: "like", count: 2 },
      { reactionType: "team_custom", count: 2 },
    ],
    reactions: [],
  },
};

afterEach(cleanup);

describe("ReactionControls", () => {
  it("opens the emoji picker and sends the selected normalized type", () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    const onRemove = vi.fn().mockResolvedValue(undefined);
    render(<ReactionControls message={message} userId="user-2" busy={false} onAdd={onAdd} onRemove={onRemove} />);

    fireEvent.click(screen.getByRole("button", { name: "Agregar reacción" }));
    expect(screen.getByRole("dialog", { name: "Seleccionar reacción" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "❤️ Corazón" }));

    expect(onAdd).toHaveBeenCalledWith(message, "heart");
    expect(screen.queryByRole("dialog", { name: "Seleccionar reacción" })).toBeNull();
  });

  it("renders known reactions as emoji, unknown types as text, and refreshes counters from new data", () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    const onRemove = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<ReactionControls message={message} userId="user-2" busy={false} onAdd={onAdd} onRemove={onRemove} />);

    expect(screen.getByRole("button", { name: "👍 Me gusta: 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "team_custom: 2" })).toBeTruthy();

    const updated: Message = {
      ...message,
      reactions: {
        ...message.reactions!,
        totalReactions: 5,
        summary: [
          { reactionType: "like", count: 3 },
          { reactionType: "team_custom", count: 2 },
        ],
      },
    };
    rerender(<ReactionControls message={updated} userId="user-2" busy={false} onAdd={onAdd} onRemove={onRemove} />);

    expect(screen.getByRole("button", { name: "👍 Me gusta: 3" })).toBeTruthy();
  });

  it("removes an existing reaction owned by the selected profile", () => {
    const onAdd = vi.fn().mockResolvedValue(undefined);
    const onRemove = vi.fn().mockResolvedValue(undefined);
    const ownMessage: Message = {
      ...message,
      reactions: {
        ...message.reactions!,
        reactions: [{ id: "reaction-1", messageId: "message-1", userId: "user-2", reactionType: "heart", createdAt: null }],
        summary: [{ reactionType: "heart", count: 1 }],
      },
    };
    render(<ReactionControls message={ownMessage} userId="user-2" busy={false} onAdd={onAdd} onRemove={onRemove} />);

    const heart = screen.getByRole("button", { name: "❤️ Corazón: 1" });
    expect(heart.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(heart);

    expect(onRemove).toHaveBeenCalledWith(ownMessage, "reaction-1");
    expect(onAdd).not.toHaveBeenCalled();
  });
});
