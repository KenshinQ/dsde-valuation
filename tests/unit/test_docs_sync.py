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
