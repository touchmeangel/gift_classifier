from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class Collection(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: UUID
    name: str
    short_name: str
    photo_url: str | None = None
    is_premarket: bool
    is_crafted: bool
    is_new: bool
    zero_commission: bool
    created_at: datetime | None = None
    day_volume: Decimal
    volume: Decimal
    floor_price: Decimal
    supply: int
    listed_count: int
    sales_24h_count: int
    market_cap: Decimal

    @field_validator("photo_url", mode="before")
    @classmethod
    def empty_url_to_none(cls, v):
        return v or None

    @field_validator("created_at", mode="after")
    @classmethod
    def zero_time_to_none(cls, v):
        return None if v is not None and v.year == 1 else v


class CollectionsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    collections: list[Collection]
    floor_changes: dict[UUID, float]
    volume_changes: dict[UUID, float | None]
