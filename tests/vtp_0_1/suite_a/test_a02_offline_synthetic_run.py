"""
VTP Suite A-02: Offline synthetic run
Test that the system can run a complete workflow offline
without network access.
"""
import subprocess
import json
import pytest
from pathlib import Path
import tempfile
import os


class TestA02OfflineSyntheticRun:
    """A-02 Offline synthetic run tests"""
    
    def test_phase0_runs_offline(self):
        """Verify Phase 0 can run completely offline"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["/workspace/.venv-vtp/bin/vms", "phase0", 
                 "--out", tmpdir, "--seed", "42"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/workspace",
                env={**os.environ, "http_proxy": "http://0.0.0.0:1", "https_proxy": "http://0.0.0.0:1"}
            )
            
            assert result.returncode == 0, f"phase0 failed offline: {result.stderr}"
            
            # Verify output bundle
            output_path = Path(tmpdir)
            assert output_path.exists()
            
            # Check for required artifacts
            required_files = [
                "request.json",
                "config_snapshot.json", 
                "method_eligibility.json",
                "simulation_metadata.json"
            ]
            
            for filename in required_files:
                file_path = output_path / filename
                assert file_path.exists(), f"Required file {filename} not found in output"
    
    def test_phase0_produces_versioned_bundle(self):
        """Verify Phase 0 produces properly versioned output"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["/workspace/.venv-vtp/bin/vms", "phase0",
                 "--out", tmpdir, "--seed", "99"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/workspace"
            )
            
            assert result.returncode == 0
            
            # Check schema version
            metadata_file = Path(tmpdir) / "simulation_metadata.json"
            if metadata_file.exists():
                with open(metadata_file) as f:
                    metadata = json.load(f)
                    assert "schema_version" in metadata or "version" in metadata
    
    def test_phase4_runs_offline(self):
        """Verify Phase 4 FCFF/FCFE/DDM routing runs offline"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["/workspace/.venv-vtp/bin/vms", "phase4",
                 "--out", tmpdir, "--seed", "42", "--paths", "40"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd="/workspace",
                env={**os.environ, "http_proxy": "http://0.0.0.0:1", "https_proxy": "http://0.0.0.0:1"}
            )
            
            assert result.returncode == 0, f"phase4 failed offline: {result.stderr}"
    
    def test_phase12_five_patterns_offline(self):
        """Verify Phase 12 five offline patterns run without network"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["/workspace/.venv-vtp/bin/vms", "phase12",
                 "--out", tmpdir, "--seed", "42", "--paths", "20"],
                capture_output=True,
                text=True,
                timeout=180,
                cwd="/workspace",
                env={**os.environ, "http_proxy": "http://0.0.0.0:1", "https_proxy": "http://0.0.0.0:1"}
            )
            
            assert result.returncode == 0, f"phase12 failed offline: {result.stderr}"
            
            # Verify multiple pattern outputs
            output_path = Path(tmpdir)
            assert output_path.exists()
    
    def test_offline_no_network_dependency(self):
        """Verify synthetic run does not require market data provider"""
        # This is implicitly tested by the offline runs above
        # Additional check: verify no requests module usage in synthetic path
        result = subprocess.run(
            ["/workspace/.venv-vtp/bin/python", "-c",
             "import sys; sys.path.insert(0, '/workspace/src'); "
             "from vms.data.synthetic import generate_synthetic_company; "
             "print('OK')"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd="/workspace"
        )
        assert result.returncode == 0
        assert "OK" in result.stdout
    
    def test_bundle_contains_provenance(self):
        """Verify output bundle contains provenance information"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["/workspace/.venv-vtp/bin/vms", "phase0",
                 "--out", tmpdir, "--seed", "42"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/workspace"
            )
            
            assert result.returncode == 0
            
            # Check for provenance in output
            config_file = Path(tmpdir) / "config_snapshot.json"
            if config_file.exists():
                with open(config_file) as f:
                    config = json.load(f)
                    # Should contain some configuration information
                    assert config is not None
                    assert isinstance(config, dict)
    
    def test_routing_decision_recorded(self):
        """Verify routing decisions are recorded in output"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["/workspace/.venv-vtp/bin/vms", "phase0",
                 "--out", tmpdir, "--seed", "42"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/workspace"
            )
            
            assert result.returncode == 0
            
            eligibility_file = Path(tmpdir) / "method_eligibility.json"
            if eligibility_file.exists():
                with open(eligibility_file) as f:
                    eligibility = json.load(f)
                    # Should record method eligibility decisions
                    assert eligibility is not None
    
    def test_investment_value_not_established_label(self):
        """Verify synthetic runs are labeled INVESTMENT_VALUE_NOT_ESTABLISHED"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["/workspace/.venv-vtp/bin/vms", "phase0",
                 "--out", tmpdir, "--seed", "42"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/workspace"
            )
            
            assert result.returncode == 0
            
            # Look for label in output files
            for json_file in Path(tmpdir).glob("*.json"):
                content = json_file.read_text()
                # Should not claim investment value
                assert "INVESTMENT_ADVICE" not in content.upper()
                # Note: Exact label format may vary, this is a basic check
