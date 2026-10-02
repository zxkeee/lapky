from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Urgency = Literal["red", "orange", "white", "green"]
CategoryKey = Literal["housing", "food", "care", "finance", "volunteer"]
SubcategoryKey = Literal["kids", "adult", "sterilized", "medical"]
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


def check_sub(category, subcategory):
    if subcategory is not None and category != "food":
        raise ValueError("subcategory дозволена лише для category='food'")


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


class ShelterBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    urgency_level: Urgency = "white"
    city: str = Field(min_length=1, max_length=100)
    district: Optional[str] = None
    address: str = Field(min_length=1, max_length=300)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    phone: Optional[str] = None
    contact_person: Optional[str] = None
    social_links: list[str] = []
    requisites: Optional[str] = None
    bank: Optional[str] = None
    source_url: Optional[str] = None
    verified_at: Optional[str] = Field(default=None, pattern=DATE_RE)


class ShelterIn(ShelterBase):
    needs: list[NeedIn] = []


class ShelterPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    urgency_level: Optional[Urgency] = None
    city: Optional[str] = Field(default=None, min_length=1)
    district: Optional[str] = None
    address: Optional[str] = Field(default=None, min_length=1)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    phone: Optional[str] = None
    contact_person: Optional[str] = None
    social_links: Optional[list[str]] = None
    requisites: Optional[str] = None
    bank: Optional[str] = None
    source_url: Optional[str] = None
    verified_at: Optional[str] = Field(default=None, pattern=DATE_RE)


class Shelter(ShelterBase):
    id: int
    needs: list[Need]
    updated_at: str
