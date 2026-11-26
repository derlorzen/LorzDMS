"""Strukturiertes Analyseergebnis. Nicht erkannte Angaben sind ``null`` – nie geraten."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Evidence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    field: str
    quote: str = Field(max_length=300)
    page: int | None = None


class Deadline(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kind: Literal["payment", "cancellation", "objection", "response", "appointment", "resubmission", "other"]
    date: str | None = None
    explicit: bool = Field(description="true = Datum steht wörtlich im Dokument; false = berechnet")
    quote: str | None = Field(default=None, max_length=300)
    page: int | None = None


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    document_type: str | None = None
    title: str | None = Field(default=None, max_length=200)
    sender: str | None = Field(default=None, max_length=200)
    recipient: str | None = Field(default=None, max_length=200)
    persons: list[str] = Field(default_factory=list, max_length=20)
    companies: list[str] = Field(default_factory=list, max_length=20)
    document_date: str | None = None
    invoice_number: str | None = None
    contract_number: str | None = None
    customer_number: str | None = None
    insurance_number: str | None = None
    case_number: str | None = None
    tax_year: int | None = None
    amount: float | None = None
    currency: str | None = None
    vat: float | None = None
    due_date: str | None = None
    deadlines: list[Deadline] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    summary: str | None = Field(default=None, max_length=1500)
    action_required: str | None = Field(default=None, max_length=500)
    confidentiality: Literal["normal", "sensitive", "highly_sensitive"] | None = None
    suggested_folder_id: str | None = None
    alternative_folder_ids: list[str] = Field(default_factory=list, max_length=5)
    suggested_filename: str | None = Field(default=None, max_length=200)
    reasoning: str | None = Field(default=None, max_length=1000)
    uncertainties: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)

    @field_validator("document_date", "due_date")
    @classmethod
    def _iso_date(cls, v: str | None) -> str | None:
        import re

        if v is None or v == "":
            return None
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return None  # Ungültige Datumsangaben verwerfen statt raten
        return v


def json_schema() -> dict:
    return AnalysisResult.model_json_schema()
