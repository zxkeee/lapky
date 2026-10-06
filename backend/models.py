from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .constants import (
    FUNDRAISER_KIND_KEYS, LINK_KIND_KEYS, OBLAST_KEYS, URL_FUNDRAISER_KINDS,
)
from .links import (
    CARD_RE, HTTPS_RE, IBAN_RE, detect_fundraiser_kind, detect_link_kind, normalize_requisites,
)

Urgency = Literal["red", "orange", "white", "green"]
CategoryKey = Literal["housing", "food", "care", "finance", "volunteer"]
SubcategoryKey = Literal["kids", "adult", "sterilized", "medical"]
OblastKey = Literal[tuple(OBLAST_KEYS)]
LinkKind = Literal[tuple(LINK_KIND_KEYS)]
FundraiserKind = Literal[tuple(FUNDRAISER_KIND_KEYS)]
ShelterStatus = Literal["published", "pending", "hidden"]
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
DATETIME_RE = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$"


def check_sub(category, subcategory):
    if subcategory is not None and category != "food":
        raise ValueError("subcategory дозволена лише для category='food'")


def _https(url: str) -> str:
    url = url.strip()
    if not HTTPS_RE.match(url):
        raise ValueError("Потрібне посилання, що починається з https://")
    return url


class NeedIn(BaseModel):
    category: CategoryKey
    subcategory: Optional[SubcategoryKey] = None
    text: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _sub_only_for_food(self):
        check_sub(self.category, self.subcategory)
        return self


class NeedPatch(BaseModel):
    category: Optional[CategoryKey] = None
    subcategory: Optional[SubcategoryKey] = None
    text: Optional[str] = Field(default=None, min_length=1, max_length=500)


class Need(NeedIn):
    id: int
    updated_at: str
    pledges_active: int = 0


class LinkIn(BaseModel):
    url: str = Field(max_length=500)
    kind: Optional[LinkKind] = None

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return _https(v)

    @model_validator(mode="after")
    def _kind(self):
        if self.kind is None:
            self.kind = detect_link_kind(self.url)
        return self


class Link(BaseModel):
    id: int
    kind: LinkKind
    url: str


class FundraiserIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=500, description="Посилання на збір або реквізити")
    kind: Optional[FundraiserKind] = None
    note: Optional[str] = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _check(self):
        self.value = normalize_requisites(self.value)
        if self.kind is None:
            self.kind = detect_fundraiser_kind(self.value)
        if self.kind in URL_FUNDRAISER_KINDS or self.value.startswith(("http://", "https://")):
            _https(self.value)
        if self.kind == "iban" and not IBAN_RE.match(self.value):
            raise ValueError("IBAN має виглядати як UA + 27 цифр")
        if self.kind == "card" and not CARD_RE.match(self.value):
            raise ValueError("Номер картки — 16 цифр")
        return self


class FundraiserPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    note: Optional[str] = Field(default=None, max_length=300)
    active: Optional[bool] = None


class Fundraiser(BaseModel):
    id: int
    title: str
    kind: FundraiserKind
    value: str
    note: Optional[str] = None
    active: bool


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    starts_at: str = Field(pattern=DATETIME_RE, description="YYYY-MM-DD HH:MM, місцевий час")
    slots: int = Field(default=1, ge=1, le=100)


class TaskPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    starts_at: Optional[str] = Field(default=None, pattern=DATETIME_RE)
    slots: Optional[int] = Field(default=None, ge=1, le=100)
    status: Optional[Literal["open", "closed"]] = None


class Task(BaseModel):
    id: int
    shelter_id: int
    shelter_name: str
    title: str
    description: Optional[str] = None
    starts_at: str
    slots: int
    taken: int
    status: Literal["open", "closed"]
    distance_km: Optional[float] = None


class ShelterBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    urgency_level: Urgency = "white"
    oblast: Optional[OblastKey] = None
    city: str = Field(min_length=1, max_length=100)
    district: Optional[str] = None
    address: str = Field(min_length=1, max_length=300)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    phone: Optional[str] = None
    contact_person: Optional[str] = None
    source_url: Optional[str] = None
    verified_at: Optional[str] = Field(default=None, pattern=DATE_RE)


class ShelterIn(ShelterBase):
    needs: list[NeedIn] = []
    links: list[LinkIn] = []
    fundraisers: list[FundraiserIn] = []


class ShelterPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    urgency_level: Optional[Urgency] = None
    oblast: Optional[OblastKey] = None
    city: Optional[str] = Field(default=None, min_length=1)
    district: Optional[str] = None
    address: Optional[str] = Field(default=None, min_length=1)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    phone: Optional[str] = None
    contact_person: Optional[str] = None
    source_url: Optional[str] = None
    verified_at: Optional[str] = Field(default=None, pattern=DATE_RE)
    status: Optional[ShelterStatus] = None


class Shelter(ShelterBase):
    id: int
    status: ShelterStatus
    source: str
    has_manager: bool = False
    needs: list[Need]
    links: list[Link] = []
    fundraisers: list[Fundraiser] = []
    tasks: list[Task] = []
    updated_at: str
    distance_km: Optional[float] = None


class MeIn(BaseModel):
    username: Optional[str] = Field(default=None, max_length=64)
    first_name: Optional[str] = Field(default=None, max_length=128)


class Me(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    role: str
    is_admin: bool
    shelters: list[dict]


class NewShelterPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    oblast: OblastKey
    city: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=300)
    lat: float = Field(ge=44, le=53)
    lng: float = Field(ge=22, le=41)
    phone: Optional[str] = Field(default=None, max_length=50)
    contact_person: Optional[str] = Field(default=None, max_length=120)
    links: list[LinkIn] = Field(default=[], max_length=10)
    comment: Optional[str] = Field(default=None, max_length=1000)


class ApplicationIn(BaseModel):
    kind: Literal["new_shelter", "claim"]
    shelter_id: Optional[int] = None
    payload: Optional[NewShelterPayload] = None
    comment: Optional[str] = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _check(self):
        if self.kind == "new_shelter" and self.payload is None:
            raise ValueError("Для new_shelter потрібен payload")
        if self.kind == "claim" and self.shelter_id is None:
            raise ValueError("Для claim потрібен shelter_id")
        return self


class Decision(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class PledgeIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=300)


class PledgePatch(BaseModel):
    status: Literal["done", "cancelled"]


class SubscriptionIn(BaseModel):
    shelter_id: Optional[int] = None
    oblast: Optional[OblastKey] = None
    only_urgent: bool = False

    @model_validator(mode="after")
    def _one_target(self):
        if (self.shelter_id is None) == (self.oblast is None):
            raise ValueError("Вкажіть або shelter_id, або oblast")
        return self


class OutboxAck(BaseModel):
    id: int
    ok: bool
    error: Optional[str] = None
    blocked: bool = False
