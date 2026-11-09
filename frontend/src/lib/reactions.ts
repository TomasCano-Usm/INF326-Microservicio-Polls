export type ReactionOption = {
  type: string;
  emoji: string;
  label: string;
};

export const REACTION_OPTIONS: ReactionOption[] = [
  { emoji: "👍", type: "like", label: "Me gusta" },
  { emoji: "❤️", type: "heart", label: "Corazón" },
  { emoji: "😂", type: "laugh", label: "Risa" },
  { emoji: "😢", type: "sad", label: "Triste" },
  { emoji: "😮", type: "surprised", label: "Sorpresa" },
  { emoji: "😡", type: "angry", label: "Enojo" },
  { emoji: "🔥", type: "fire", label: "Fuego" },
  { emoji: "🎉", type: "celebrate", label: "Celebración" },
  { emoji: "👎", type: "dislike", label: "No me gusta" },
];

const REACTION_BY_TYPE = new Map(REACTION_OPTIONS.map((option) => [option.type, option]));

export function reactionEmoji(reactionType: string): string {
  return REACTION_BY_TYPE.get(reactionType)?.emoji ?? reactionType;
}

export function reactionLabel(reactionType: string): string {
  return REACTION_BY_TYPE.get(reactionType)?.label ?? reactionType;
}
