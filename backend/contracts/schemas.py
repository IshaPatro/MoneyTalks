"""Shared data contracts between Role 1 (analytics) and Role 2 (agent/memory).

These mirror the JSON contracts in the project README (section 9) and must
stay stable across all three workstreams. Role 2 treats these as read-only
inputs coming from Role 1 -- it never recomputes the numeric fields itself.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Variance(BaseModel):
    variance_id: str
    account: str
    previous: float
    current: float
    change: float
    change_pct: float


class Driver(BaseModel):
    driver_id: str
    dimension: str  # e.g. "customer", "vendor", "product", "department", "region"
    entity: str
    change: float
    transaction_ids: list[str] = Field(default_factory=list)


class Transaction(BaseModel):
    transaction_id: str
    date: str
    period: str
    account: str
    amount: float
    description: Optional[str] = None
    customer: Optional[str] = None
    vendor: Optional[str] = None
    product: Optional[str] = None
    department: Optional[str] = None
    region: Optional[str] = None


class ConfirmedContextRef(BaseModel):
    """Lightweight view of a `memory.store.ConfirmedContext` row, kept as
    its own contract so `backend/contracts` doesn't need to import
    `backend/memory` (which owns the actual SQLite-backed dataclass)."""

    account: str
    period: str
    explanation: str
    entity: Optional[str] = None


class NarrativeVerdict(BaseModel):
    """Result of checking a public statement (e.g. an earnings-call quote)
    against the real driver/transaction data for a variance.

    Optional, additive feature -- does not affect the core Variance /
    Driver / Explanation contracts above.
    """

    variance_id: str
    claim_text: str
    claimed_entities: list[str] = Field(default_factory=list)
    matched_entities: list[str] = Field(default_factory=list)
    actual_top_entities: list[str] = Field(default_factory=list)
    match_pct: Optional[float] = None
    verdict: str  # "supported" | "partially_supported" | "unsupported" | "contradicted" | "unverifiable"
    reasoning: str
    driver_ids: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    variance_id: str
    headline: str
    explanation: str
    driver_ids: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)
    historical_context: Optional[str] = None
