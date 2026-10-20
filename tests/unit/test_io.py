"""CSV/Parquet ingestion (Phase 1 deliverable)."""

import pandas as pd
import pytest

from vms.data import synthetic
from vms.data.io import load_directory, write_directory
from vms.reporting.metadata import hash_models


@pytest.mark.parametrize("fmt", ["csv", "parquet"])
def test_round_trip(tmp_path, syn, fmt):
    fin, mkt, ca = syn
    write_directory(tmp_path, fin, mkt, ca, synthetic.source_descriptors(), fmt=fmt)
    res = load_directory(tmp_path)
    assert res.ok, res.errors
    assert res.corporate_actions_provided and res.sources_provided
    assert hash_models(res.financial) == hash_models(fin)
    assert hash_models(res.market) == hash_models(mkt)
    assert hash_models(res.corporate_actions) == hash_models(ca)
    assert all(info["format"] in (fmt, "yaml") for info in res.files.values())


def test_csv_and_parquet_identical_records(tmp_path, syn):
    write_directory(tmp_path / "c", *syn, synthetic.source_descriptors(), fmt="csv")
    write_directory(tmp_path / "p", *syn, synthetic.source_descriptors(), fmt="parquet")
    a, b = load_directory(tmp_path / "c"), load_directory(tmp_path / "p")
    assert hash_models([*a.financial, *a.market, *a.corporate_actions]) == \
        hash_models([*b.financial, *b.market, *b.corporate_actions])


def test_both_formats_present_is_error(tmp_path, syn):
    write_directory(tmp_path, *syn, fmt="csv")
    write_directory(tmp_path, *syn, fmt="parquet")
    res = load_directory(tmp_path)
    assert any("keep exactly one" in e for e in res.errors)


def test_parquet_naive_timestamp_rejected_with_row(tmp_path, syn):
    write_directory(tmp_path, *syn, fmt="parquet")
    p = tmp_path / "market_observations.parquet"
    df = pd.read_parquet(p)
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    df.to_parquet(p, index=False)
    res = load_directory(tmp_path)
    assert any("market_observations.parquet:row 0: timestamp" in e and "timezone-naive" in e for e in res.errors)


def test_optional_tables_absent(tmp_path, syn):
    fin, mkt, _ = syn
    write_directory(tmp_path, fin, mkt)
    res = load_directory(tmp_path)
    assert res.ok and not res.corporate_actions_provided and not res.sources_provided


def test_bad_sources_yaml(tmp_path, syn):
    write_directory(tmp_path, *syn)
    (tmp_path / "sources.yaml").write_text("sources:\n  - {source_id: S, reporting_convention: YTD, versioning: X}\n")
    res = load_directory(tmp_path)
    assert any("sources.yaml:sources[0]" in e and "reporting_convention" in e for e in res.errors)
