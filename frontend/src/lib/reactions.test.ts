import { describe, expect, it } from "vitest";
import { REACTION_OPTIONS, reactionEmoji, reactionLabel } from "@/lib/reactions";

describe("reaction catalog", () => {
  it("maps all documented picker options to normalized backend types", () => {
    expect(REACTION_OPTIONS.map(({ emoji, type }) => [emoji, type])).toEqual([
      ["👍", "like"],
      ["❤️", "heart"],
      ["😂", "laugh"],
      ["😢", "sad"],
      ["😮", "surprised"],
      ["😡", "angry"],
      ["🔥", "fire"],
      ["🎉", "celebrate"],
      ["👎", "dislike"],
    ]);
    for (const { type } of REACTION_OPTIONS) {
      expect(type).toMatch(/^[a-z0-9_-]{1,32}$/);
    }
  });

  it("preserves unrecognized backend reaction names as fallback text", () => {
    expect(reactionEmoji("team_custom")).toBe("team_custom");
    expect(reactionLabel("team_custom")).toBe("team_custom");
  });
});
