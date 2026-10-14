from datetime import timezone

from app.models import PollResponse


def build_poll_announcement(poll: PollResponse) -> str:
    alternatives = "\n".join(
        f"- {option.text}" for option in poll.options
    )
    closes_at = poll.closes_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"📊 Nueva encuesta: {poll.question}\n"
        f"Poll ID: {poll.poll_id}\n"
        f"Alternativas:\n{alternatives}\n"
        f"Cierre: {closes_at}"
    )


def build_poll_results(poll: PollResponse) -> str:
    results = "\n".join(
        f"- {option.text}: {option.vote_count} voto(s)" for option in poll.options
    )
    return (
        f"📊 Encuesta finalizada: {poll.question}\n"
        f"Resultados finales:\n{results}\n"
        f"Total de votos: {poll.total_votes}"
    )
