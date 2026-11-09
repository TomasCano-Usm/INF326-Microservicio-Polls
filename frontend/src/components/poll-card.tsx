import { useState } from "react";
import type { Poll } from "@/lib/graphql/types";
import { formatDateTime, pollStatusLabel } from "@/lib/polls";

type PollCardProps = {
  poll: Poll;
  userId: string | null;
  voted: boolean;
  busy: boolean;
  onVote: (poll: Poll, optionId: string) => Promise<void>;
  onClose: (poll: Poll) => Promise<void>;
};

export function PollCard({ poll, userId, voted, busy, onVote, onClose }: PollCardProps) {
  const [selectedOptionId, setSelectedOptionId] = useState("");
  const isOpen = poll.status === "open";
  const isPending = poll.status === "pending_announcement";
  const isClosed = poll.status === "closed";
  const isAuthor = Boolean(userId && userId === poll.authorId);
  const showResults = isClosed || voted;

  return (
    <section className="poll-card" aria-label={`Encuesta: ${poll.question}`}>
      <div className="poll-topline">
        <div>
          <p className="poll-label"><span aria-hidden="true">◈</span> Encuesta</p>
          <h3 className="poll-question">{poll.question}</h3>
        </div>
        <span className={`status-badge ${poll.status}`}>{pollStatusLabel(poll.status)}</span>
      </div>

      {isPending ? (
        <p className="pending-copy">El anuncio se está publicando en el canal. La encuesta estará disponible para votar cuando quede abierta.</p>
      ) : poll.status === "creation_failed" ? (
        <p className="error-copy">{poll.creationError || "No fue posible publicar esta encuesta."}</p>
      ) : (
        <div className="poll-options">
          {[...poll.options].sort((left, right) => left.position - right.position).map((option) => {
            const percent = poll.totalVotes > 0 ? Math.round((option.voteCount / poll.totalVotes) * 100) : 0;
            return (
              <label className="poll-option" key={option.optionId}>
                {showResults && <span className="poll-progress" style={{ width: `${percent}%` }} />}
                {isOpen && !voted && (
                  <input
                    type="radio"
                    name={`poll-${poll.pollId}`}
                    value={option.optionId}
                    checked={selectedOptionId === option.optionId}
                    onChange={() => setSelectedOptionId(option.optionId)}
                    disabled={!userId || busy}
                  />
                )}
                <span className="poll-option-text">{option.text}</span>
                <span className="poll-option-count">{option.voteCount} · {percent}%</span>
              </label>
            );
          })}
        </div>
      )}

      <div className="poll-footer">
        <span className="poll-meta">
          {poll.totalVotes} {poll.totalVotes === 1 ? "voto" : "votos"}
          {isOpen && ` · Cierra ${formatDateTime(poll.closesAt)}`}
        </span>
        <div className="poll-actions">
          {isOpen && !voted && (
            <button
              className="primary-button"
              type="button"
              disabled={!userId || !selectedOptionId || busy}
              onClick={() => void onVote(poll, selectedOptionId)}
            >
              {busy ? "Enviando…" : "Votar"}
            </button>
          )}
          {isOpen && voted && <span className="muted" aria-live="polite">Voto enviado por este perfil</span>}
          {isOpen && isAuthor && (
            <button className="secondary-button" type="button" disabled={busy} onClick={() => void onClose(poll)}>
              Cerrar encuesta
            </button>
          )}
          {isClosed && poll.closedAt && <span className="poll-meta">Cerrada {formatDateTime(poll.closedAt)}</span>}
        </div>
      </div>
      {!userId && isOpen && <p className="field-help">Selecciona un perfil de demostración para votar.</p>}
      {isOpen && isAuthor && <p className="field-help">El cierre se valida en Polls; el selector de perfil no es autenticación.</p>}
    </section>
  );
}
