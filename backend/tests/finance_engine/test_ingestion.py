from pathlib import Path

import pytest

from backend.finance_engine.ingestion import (
    DatasetValidationError, load_dataset, month_to_period, period_to_month,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_CSV = REPO_ROOT / "data" / "subscription_accounts.csv"

pytestmark = pytest.mark.skipif(not DATA_CSV.exists(), reason="synthetic dataset not present")


def test_month_period_roundtrip():
    for m in [1, 2, 12, 13, 24, 25]:
        assert period_to_month(month_to_period(m)) == m


def test_month_to_period_matches_generator_anchor():
    assert month_to_period(1) == "2025-01"
    assert month_to_period(12) == "2025-12"
    assert month_to_period(13) == "2026-01"


def test_load_real_dataset():
    dataset = load_dataset(DATA_CSV)
    info = dataset.info()
    assert info["account_count"] > 0
    assert "2025-01" in info["periods"]
    assert set(info["available_dimensions"]) == {"account", "company_size", "industry", "contract_type"}
    assert set(info["billing_categories"]) == {
        "new_arr", "expansion", "contraction", "churn", "sla_credit", "refund", "usage_overage",
    }


def test_list_columns_are_parsed_into_real_lists():
    dataset = load_dataset(DATA_CSV)
    df = dataset.accounts_df
    sample = df[df["transaction_count"] > 0].iloc[0]
    assert isinstance(sample["transaction_ids"], list)
    assert isinstance(sample["transaction_amounts"], list)
    assert len(sample["transaction_ids"]) == sample["transaction_count"]


def test_missing_required_column_raises(tmp_path: Path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("account_id,month\nACC-1,1\n")
    with pytest.raises(DatasetValidationError):
        load_dataset(bad_csv)
