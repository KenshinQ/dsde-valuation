from pathlib import Path

from vms.quality.checks import CHECK_CATALOGUE
from vms.schemas.fields import FIELDS

DOC = (Path(__file__).resolve().parents[2] / "docs/data_contracts.md").read_text()


def test_every_canonical_field_documented_with_kind_and_sign():
    for f in FIELDS:
        assert f"| `{f.name}` | {f.statement_type} | {f.kind} | {f.sign} |" in DOC, f.name


def test_every_check_documented():
    for c in CHECK_CATALOGUE:
        assert c in DOC, c


def test_assumption_register_documented():
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("gen", root / "scripts/gen_assumptions_doc.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert (root / "docs/assumptions.md").read_text(encoding="utf-8") == gen.render(), \
        "docs/assumptions.md out of date: run python scripts/gen_assumptions_doc.py"


def test_assumption_ids_versioned_and_cite_rejects_unknown():
    import re

    import pytest

    from vms.assumptions import ASSUMPTIONS, SUPERSEDED, cite
    assert all(re.fullmatch(r"[A-Z0-9-]+-v\d+", k) for k in ASSUMPTIONS)
    with pytest.raises(KeyError):
        cite("NOT-AN-ASSUMPTION-v1")
    assert all(k in ASSUMPTIONS and v in ASSUMPTIONS for k, v in SUPERSEDED.items())
    with pytest.raises(KeyError, match="superseded"):
        cite("PAYOUT-SAME-YEAR-v1")
