
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class NftAttribute(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    value: str
    rarity_per_mille: float


class Nft(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: UUID
    name: str
    photo_url: str | None = None
    collection_id: UUID
    external_collection_number: int
    price: Decimal | None = None
    status: str
    animation_url: str | None = None
    has_animation: bool
    attributes: list[NftAttribute]
    emoji_id: str
    is_owned: bool
    floor_price: Decimal
    ton_address: str | None = None
    is_crafted: bool

    @field_validator("photo_url", "animation_url", mode="before")
    @classmethod
    def empty_url_to_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class Action(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    nft: Nft
    bundle: Any = None
    offer_id: Any = None
    type: str
    amount: Decimal
    old_price: Decimal | None = None
    created_at: datetime


class ActionsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    actions: list[Action]