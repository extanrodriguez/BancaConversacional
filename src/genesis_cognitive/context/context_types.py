"""Context provider return types."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from genesis_cognitive.context.types import PortfolioSnapshot, RecentTurn
from genesis_cognitive.enums import SessionStatus


class ConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    session_id: str
    turn_number: int = Field(ge=1)
    session_status: SessionStatus
    recent_turns: tuple[RecentTurn, ...]


class PortfolioContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    snapshot: PortfolioSnapshot


class PendingOperationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    pending_operation: None = None
    last_operation_request: None = None
    last_operation_result: None = None


class HistoricalActivityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    description: str
    timestamp: datetime

    @model_validator(mode="after")
    def validate_timezone_aware(self) -> "HistoricalActivityItem":
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            msg = "timestamp must be timezone-aware."
            raise ValueError(msg)
        return self


class HistoricalActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    items: tuple[HistoricalActivityItem, ...] = ()
