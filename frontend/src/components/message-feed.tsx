import { useEffect, useMemo } from "react";
import type { Message, Poll, User } from "@/lib/graphql/types";
import { formatDateTime, pollIdFromAnnouncement } from "@/lib/polls";
import { PollCard } from "@/components/poll-card";
import { ReactionControls } from "@/components/reaction-controls";

type MessageFeedProps = {
  messages: Message[];
  polls: Poll[];
  user: User | null;
  loading: boolean;
  error: string | null;
  busyPollId: string | null;
  busyReactionMessageId: string | null;
  votedPollIds: Set<string>;
  highlightedMessageId: string | null;
  onRetry: () => void;
  onVote: (poll: Poll, optionId: string) => Promise<void>;
  onClosePoll: (poll: Poll) => Promise<void>;
  onAddReaction: (message: Message, reactionType: string) => Promise<void>;
  onRemoveReaction: (message: Message, reactionId: string) => Promise<void>;
};

function initials(label: string): string {
  return label.trim().charAt(0).toUpperCase() || "?";
}

export function MessageFeed({
  messages,
  polls,
  user,
  loading,
  error,
  busyPollId,
  busyReactionMessageId,
  votedPollIds,
  highlightedMessageId,
  onRetry,
  onVote,
  onClosePoll,
  onAddReaction,
  onRemoveReaction,
}: MessageFeedProps) {
  const pollById = useMemo(() => new Map(polls.map((poll) => [poll.pollId, poll])), [polls]);
  const sortedMessages = useMemo(
    () => [...messages].sort((left, right) => left.createdAt.localeCompare(right.createdAt)),
    [messages],
  );

  useEffect(() => {
    if (!highlightedMessageId) return;
    const timeout = window.setTimeout(() => {
      document.getElementById(`message-${highlightedMessageId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [highlightedMessageId, messages]);

  const linkedPollIds = new Set<string>();
  const renderedPollIds = new Set<string>();
  const visibleMessages = sortedMessages.map((message) => {
    const pollId = pollIdFromAnnouncement(message.content);
    const foundPoll = pollId ? pollById.get(pollId) : undefined;
    const poll = foundPoll && !renderedPollIds.has(foundPoll.pollId) ? foundPoll : undefined;
    if (foundPoll) linkedPollIds.add(foundPoll.pollId);
    if (poll) renderedPollIds.add(poll.pollId);
    return { message, poll };
  });
  const unlinkedPolls = polls.filter((poll) => !linkedPollIds.has(poll.pollId));

  return (
    <div className="message-scroll" id="conversation-scroll">
      <section className="welcome-card">
        <p className="welcome-eyebrow">Tu espacio de equipo</p>
        <h2 className="welcome-title">Conversaciones que terminan en decisiones.</h2>
        <p className="welcome-copy">Comparte ideas, consulta al equipo y convierte las preguntas en encuestas. Todo en un mismo canal.</p>
      </section>

      {error && (
        <div className="conversation-error" role="alert">
          <div>{error}</div>
          <button className="text-button" type="button" onClick={onRetry}>Reintentar</button>
        </div>
      )}

      {unlinkedPolls.length > 0 && (
        <section className="unlinked-polls" aria-label="Encuestas del canal sin anuncio relacionado">
          <p className="section-kicker">Encuestas del canal</p>
          <div className="unlinked-poll-list">
            {unlinkedPolls.map((poll) => (
              <PollCard
                key={poll.pollId}
                poll={poll}
                userId={user?.id ?? null}
                voted={votedPollIds.has(poll.pollId)}
                busy={busyPollId === poll.pollId}
                onVote={onVote}
                onClose={onClosePoll}
              />
            ))}
          </div>
        </section>
      )}

      {loading && messages.length === 0 ? (
        <div aria-label="Cargando mensajes" aria-live="polite">
          <div className="loading-line" /><div className="loading-line" /><div className="loading-line" />
        </div>
      ) : sortedMessages.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true">✦</div>
          <h3 className="empty-title">Este canal está listo para empezar</h3>
          <p className="empty-copy">Envía el primer mensaje o crea una encuesta para iniciar la conversación.</p>
        </div>
      ) : (
        <>
          <div className="day-divider"><span>Conversación</span></div>
          <div className="message-list">
            {visibleMessages.map(({ message, poll }) => {
              const authorName = message.author?.displayName ?? `Usuario ${message.authorId}`;
              const isAnnouncement = Boolean(poll);
              return (
                <article
                  className={`message-row${highlightedMessageId === message.id ? " highlighted" : ""}`}
                  id={`message-${message.id}`}
                  key={message.id}
                >
                  <div className="message-avatar" aria-hidden="true">{initials(authorName)}</div>
                  <div className="message-main">
                    <div className="message-meta">
                      <span className="message-author">{authorName}</span>
                      <time className="message-time" dateTime={message.createdAt}>{formatDateTime(message.createdAt)}</time>
                      {!message.author && <span className="message-author-id">ID: {message.authorId}</span>}
                    </div>
                    <p className={`message-content${isAnnouncement ? " poll-announcement" : ""}`}>{message.content}</p>
                    {poll && (
                      <PollCard
                        poll={poll}
                        userId={user?.id ?? null}
                        voted={votedPollIds.has(poll.pollId)}
                        busy={busyPollId === poll.pollId}
                        onVote={onVote}
                        onClose={onClosePoll}
                      />
                    )}
                    <ReactionControls
                      message={message}
                      userId={user?.id ?? null}
                      onAdd={onAddReaction}
                      onRemove={onRemoveReaction}
                      busy={busyReactionMessageId === message.id}
                    />
                  </div>
                </article>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
