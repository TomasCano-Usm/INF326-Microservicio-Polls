from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PollCreateRequest(APIModel):
    channel_id: NonEmptyText
    author_id: NonEmptyText
    question: NonEmptyText
    options: list[NonEmptyText] = Field(min_length=2, max_length=10)
    duration_minutes: int = Field(default=5, ge=1, le=1440)

    @field_validator("options")
    @classmethod
    def validate_unique_options(cls, value: list[str]) -> list[str]:
        normalized = [option.strip().casefold() for option in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Las alternativas no pueden repetirse.")
        return value


class VoteRequest(APIModel):
    voter_id: NonEmptyText
    option_id: UUID


class CloseRequest(APIModel):
    author_id: NonEmptyText


class OptionResult(APIModel):
    option_id: UUID
    position: int
    text: str
    vote_count: int


class PollResponse(APIModel):
    poll_id: UUID
    channel_id: str
    author_id: str
    question: str
    options: list[OptionResult]
    status: Literal["pending_announcement", "open", "closed", "creation_failed"]
    duration_minutes: int
    closes_at: datetime
    created_at: datetime
    closed_at: datetime | None
    total_votes: int
    creation_error: str | None = None


class VoteResponse(APIModel):
    poll_id: UUID
    voter_id: str
    option_id: UUID
    cast_at: datetime
