"""SPEC §3.3 / Phase 0: the core must not import legacy system modules."""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"

# Legacy / external DSDE-era modules that must never be imported by the core.
FORBIDDEN_TOP_LEVEL = {"dsde_engine", "dsde", "pit", "ftd", "dv1", "fundamental_mc",
                       "fundamental_monte_carlo", "legacy"}
FORBIDDEN_TEXT = re.compile(r"dsde[-_]engine|/workspace/dsde\b|sys\.path\.(append|insert)")
ALLOWED_THIRD_PARTY = {"numpy", "pandas", "scipy", "pydantic", "yaml"}


def _py_files():
    files = sorted(SRC.rglob("*.py"))
    assert files, "no source files found"
    return files


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module)
    return out


def test_no_forbidden_imports():
    bad = [(str(f.relative_to(REPO)), m) for f in _py_files() for m in _imports(f)
           if m.split(".")[0] in FORBIDDEN_TOP_LEVEL]
    assert not bad, f"legacy imports found: {bad}"


def test_no_legacy_paths_or_sys_path_hacks():
    bad = [str(f.relative_to(REPO)) for f in _py_files() if FORBIDDEN_TEXT.search(f.read_text(encoding="utf-8"))]
    assert not bad, f"legacy path references / sys.path manipulation in: {bad}"


def test_only_declared_third_party_imports():
    import sys
    stdlib = set(sys.stdlib_module_names)
    third = {m.split(".")[0] for f in _py_files() for m in _imports(f)} - stdlib - {"vms"}
    assert third <= ALLOWED_THIRD_PARTY, f"undeclared dependencies imported: {sorted(third - ALLOWED_THIRD_PARTY)}"


def test_detector_catches_violation(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import dsde_engine.adapters\nfrom pit.store import X\n")
    found = {m.split(".")[0] for m in _imports(f)}
    assert found & FORBIDDEN_TOP_LEVEL == {"dsde_engine", "pit"}
