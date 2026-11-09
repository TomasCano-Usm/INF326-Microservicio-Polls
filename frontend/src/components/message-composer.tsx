import { useEffect, useRef, useState, type FormEvent } from "react";

type MessageComposerProps = {
  disabled: boolean;
  sending: boolean;
  channelName?: string;
  onSend: (content: string) => Promise<void>;
};

const MAX_TEXTAREA_HEIGHT = 140;

export function MessageComposer({ disabled, sending, channelName, onSend }: MessageComposerProps) {
  const [content, setContent] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`;
    textarea.style.overflowY = textarea.scrollHeight > MAX_TEXTAREA_HEIGHT ? "auto" : "hidden";
  }, [content]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = content.trim();
    if (!message || disabled || sending) return;
    try {
      await onSend(message);
      setContent("");
    } catch {
      // The parent surfaces the GraphQL error and the draft remains available to retry.
    }
  }

  return (
    <div className="composer-wrap">
      <form className="composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="message-composer">Escribe un mensaje</label>
        <textarea
          ref={textareaRef}
          id="message-composer"
          placeholder={channelName ? `Escribe en #${channelName}` : "Selecciona un canal para escribir"}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          rows={1}
          disabled={disabled || sending}
        />
        <button className="send-button" type="submit" disabled={disabled || sending || !content.trim()} aria-label="Enviar mensaje">
          {sending ? "…" : "↑"}
        </button>
      </form>
      <p className="composer-hint">
        {disabled ? "Selecciona un usuario y un canal para participar." : "Enter para enviar · Shift + Enter para una nueva línea"}
      </p>
    </div>
  );
}
