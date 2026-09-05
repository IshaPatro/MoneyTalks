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


class Explanation(BaseModel):
    variance_id: str
    headline: str
    explanation: str
    driver_ids: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)
    historical_context: Optional[str] = None
