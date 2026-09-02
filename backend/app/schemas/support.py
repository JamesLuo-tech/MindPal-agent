from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class SafetyPlanOut(BaseModel):
    warning_signs: str | None
    internal_coping: str | None
    distraction_people_places: str | None
    help_contacts: str | None
    professional_contacts: str | None
    safe_environment: str | None
    updated_at: datetime | None


class SafetyPlanUpsert(BaseModel):
    warning_signs: str | None = None
    internal_coping: str | None = None
    distraction_people_places: str | None = None
    help_contacts: str | None = None
    professional_contacts: str | None = None
    safe_environment: str | None = None


class TrustedContactOut(BaseModel):
    id: UUID
    name: str
    relationship: str | None
    phone: str | None
    created_at: datetime


class TrustedContactCreate(BaseModel):
    name: str
    relationship: str | None = None
    phone: str | None = None
