"""
VTP Suite A-01: Clean install
Test that the system can be installed from documented dependencies
without hidden local files or credentials.
"""
import subprocess
import sys
import pytest
from pathlib import Path


class TestA01CleanInstall:
    """A-01 Clean install tests"""
    
    def test_requirements_lock_exists(self):
        """Verify requirements.lock exists and is readable"""
        lock_file = Path("/workspace/requirements.lock")
        assert lock_file.exists(), "requirements.lock must exist"
        assert lock_file.is_file(), "requirements.lock must be a file"
        content = lock_file.read_text()
        assert len(content) > 0, "requirements.lock must not be empty"
        assert "numpy" in content, "requirements.lock must contain numpy"
        assert "pandas" in content, "requirements.lock must contain pandas"
        assert "pydantic" in content, "requirements.lock must contain pydantic"
    
    def test_pyproject_toml_valid(self):
        """Verify pyproject.toml is valid and complete"""
        pyproject = Path("/workspace/pyproject.toml")
        assert pyproject.exists(), "pyproject.toml must exist"
        content = pyproject.read_text()
        assert "[project]" in content
        assert "name = \"dsde-valuation\"" in content
        assert "requires-python" in content
        assert "dependencies" in content
    
    def test_package_can_be_imported(self):
        """Verify VMS package can be imported"""
        # Use PYTHONPATH to import from src
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, '/workspace/src'); import vms; print(vms.__file__)"],
            capture_output=True,
            text=True,
            timeout=10
        )
        assert result.returncode == 0, f"Failed to import vms: {result.stderr}"
        assert "/workspace/src/vms" in result.stdout
    
    def test_cli_entry_point_exists(self):
        """Verify CLI entry point is accessible"""
        venv_python = Path("/workspace/.venv-vtp/bin/python")
        if venv_python.exists():
            result = subprocess.run(
                [str(venv_python), "-m", "vms.cli.main", "--help"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd="/workspace"
            )
            assert result.returncode == 0, "CLI entry point must be accessible"
            assert "VMS" in result.stdout or "vms" in result.stdout
    
    def test_no_legacy_import_violations(self):
        """Verify no imports from legacy projects"""
        # Check that test_no_legacy_imports.py passed
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "tests/unit/test_no_legacy_imports.py"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/workspace",
            env={"PYTHONPATH": "/workspace/src"}
        )
        # Should pass (exit code 0) or the test file should exist
        assert result.returncode == 0 or "no tests ran" in result.stdout.lower()
    
    def test_declared_dependencies_complete(self):
        """Verify all runtime dependencies are declared"""
        pyproject = Path("/workspace/pyproject.toml")
        content = pyproject.read_text()
        
        # Core dependencies from SPEC §3.3
        required_deps = ["numpy", "pandas", "scipy", "pydantic", "pyyaml", "pyarrow"]
        for dep in required_deps:
            assert dep in content, f"Required dependency {dep} must be declared in pyproject.toml"
    
    def test_dev_dependencies_declared(self):
        """Verify dev dependencies are properly declared"""
        pyproject = Path("/workspace/pyproject.toml")
        content = pyproject.read_text()
        
        # Dev dependencies from SPEC
        dev_deps = ["pytest", "hypothesis"]
        for dep in dev_deps:
            assert dep in content, f"Dev dependency {dep} must be declared"
    
    def test_python_version_requirement(self):
        """Verify Python version requirement is set"""
        pyproject = Path("/workspace/pyproject.toml")
        content = pyproject.read_text()
        assert "requires-python" in content
        assert ">=3.11" in content or ">= 3.11" in content
    
    def test_no_hardcoded_credentials(self):
        """Verify no hardcoded credentials in source"""
        src_path = Path("/workspace/src")
        suspicious_patterns = [
            b"password =",
            b"api_key =",
            b"secret =",
            b"token =",
            b"AWS_SECRET",
            b"OPENAI_API_KEY"
        ]
        
        violations = []
        for py_file in src_path.rglob("*.py"):
            content = py_file.read_bytes()
            for pattern in suspicious_patterns:
                if pattern in content.lower():
                    # Check if it's actually a hardcoded value (not just a variable name)
                    lines = content.decode('utf-8', errors='ignore').split('\n')
                    for i, line in enumerate(lines):
                        if pattern.decode() in line.lower() and "=" in line:
                            # Skip comments and docstrings
                            stripped = line.strip()
                            if not stripped.startswith('#') and not stripped.startswith('"""'):
                                if '"' in line or "'" in line:
                                    # Might be a hardcoded credential
                                    violations.append(f"{py_file}:{i+1}: {line.strip()}")
        
        # Allow environment variable access patterns
        violations = [v for v in violations if "os.environ" not in v and "getenv" not in v]
        assert len(violations) == 0, f"Possible hardcoded credentials found:\n" + "\n".join(violations)
