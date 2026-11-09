"use client";

import { useEffect, useRef, useState } from "react";
import type { Message } from "@/lib/graphql/types";
import { REACTION_OPTIONS, reactionEmoji, reactionLabel } from "@/lib/reactions";

type ReactionControlsProps = {
  message: Message;
  userId: string | null;
  busy: boolean;
  onAdd: (message: Message, reactionType: string) => Promise<void>;
  onRemove: (message: Message, reactionId: string) => Promise<void>;
};

function pickerElementId(messageId: string): string {
  return `reaction-picker-${messageId.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

export function ReactionControls({ message, userId, busy, onAdd, onRemove }: ReactionControlsProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const controlRef = useRef<HTMLDivElement>(null);
  const summaries = message.reactions?.summary ?? [];
  const reactions = message.reactions?.reactions ?? [];
  const ownedTypes = new Set(
    reactions.filter((reaction) => reaction.userId === userId).map((reaction) => reaction.reactionType),
  );
  const pickerId = pickerElementId(message.id);

  useEffect(() => {
    if (!pickerOpen) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!controlRef.current?.contains(event.target as Node)) setPickerOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPickerOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [pickerOpen]);

  return (
    <div className="reaction-controls" ref={controlRef}>
      <div className="reaction-bar" aria-label="Reacciones">
        {summaries.map((summary) => {
          const ownReaction = reactions.find(
            (reaction) => reaction.userId === userId && reaction.reactionType === summary.reactionType,
          );
          const label = reactionLabel(summary.reactionType);
          const emoji = reactionEmoji(summary.reactionType);
          const accessibleName = emoji === summary.reactionType
            ? `${summary.reactionType}: ${summary.count}`
            : `${emoji} ${label}: ${summary.count}`;
          return (
            <button
              className={`reaction-pill${ownReaction ? " selected" : ""}`}
              key={summary.reactionType}
              type="button"
              aria-label={accessibleName}
              aria-pressed={Boolean(ownReaction)}
              title={ownReaction ? `Quitar ${label}` : `Agregar ${label}`}
              disabled={!userId || busy}
              onClick={() => ownReaction
                ? void onRemove(message, ownReaction.id)
                : void onAdd(message, summary.reactionType)}
            >
              <span aria-hidden="true">{emoji}</span>
              <span>{summary.count}</span>
            </button>
          );
        })}
        <button
          className="reaction-pill reaction-add"
          type="button"
          aria-label="Agregar reacción"
          aria-haspopup="dialog"
          aria-expanded={pickerOpen}
          aria-controls={pickerId}
          title="Agregar reacción"
          disabled={!userId || busy}
          onClick={() => setPickerOpen((open) => !open)}
        >
          <span aria-hidden="true">＋</span>
        </button>
        {!message.reactions && <span className="field-help">Reacciones no disponibles</span>}
      </div>

      {pickerOpen && (
        <div className="reaction-picker" id={pickerId} role="dialog" aria-label="Seleccionar reacción">
          {REACTION_OPTIONS.map((option) => {
            const alreadyAdded = ownedTypes.has(option.type);
            return (
              <button
                className="reaction-picker-option"
                key={option.type}
                type="button"
                aria-label={`${option.emoji} ${option.label}`}
                title={alreadyAdded ? `Ya agregaste ${option.label}` : option.label}
                disabled={busy || alreadyAdded}
                onClick={() => {
                  setPickerOpen(false);
                  void onAdd(message, option.type);
                }}
              >
                <span aria-hidden="true">{option.emoji}</span>
                <span className="sr-only">{option.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
