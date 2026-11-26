#!/usr/bin/env python3
"""
VTP-0.1 Execution Harness
Systematic test execution and evidence collection per VTP specification.
"""
import subprocess
import json
import yaml
import hashlib
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import csv


class VTPExecutionHarness:
    """VTP-0.1 test execution and evidence collector"""
    
    def __init__(self, workspace_root: Path, evidence_dir: Path):
        self.workspace = workspace_root
        self.evidence = evidence_dir
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.results = {
            "execution_metadata": {},
            "test_results": {},
            "evidence_files": [],
            "hashes": {},
            "verdicts": {}
        }
    
    def collect_environment_hashes(self) -> Dict[str, str]:
        """Collect all relevant hashes for reproducibility"""
        hashes = {}
        
        # Baseline commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=self.workspace
        )
        hashes["baseline_commit"] = result.stdout.strip()
        
        # Requirements lock
        lock_file = self.workspace / "requirements.lock"
        if lock_file.exists():
            hashes["requirements_lock"] = self._file_hash(lock_file)
        
        # Python version
        result = subprocess.run(
            ["python3", "--version"],
            capture_output=True, text=True
        )
        hashes["python_version"] = result.stdout.strip()
        
        # Key source files
        for pattern in ["src/**/*.py", "tests/**/*.py"]:
            for py_file in self.workspace.glob(pattern):
                if ".venv" not in str(py_file):
                    rel_path = py_file.relative_to(self.workspace)
                    hashes[str(rel_path)] = self._file_hash(py_file)
        
        return hashes
    
    def _file_hash(self, filepath: Path) -> str:
        """Calculate SHA256 hash of file"""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def run_test_suite(self, suite_name: str, pytest_args: List[str]) -> Dict[str, Any]:
        """Run a test suite and collect results"""
        print(f"\\n=== Executing {suite_name} ===")
        
        # Run pytest with JSON report
        json_report = self.evidence / f"{suite_name}_report.json"
        log_file = self.evidence / f"{suite_name}.log"
        
        cmd = [
            str(self.workspace / ".venv-vtp/bin/pytest"),
            "-v",
            "--tb=short",
            "--junit-xml", str(self.evidence / f"{suite_name}_junit.xml"),
        ] + pytest_args
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=self.workspace,
            timeout=600
        )
        
        # Save logs
        with open(log_file, 'w') as f:
            f.write(f"Command: {' '.join(cmd)}\\n")
            f.write(f"Exit code: {result.returncode}\\n\\n")
            f.write("=== STDOUT ===\\n")
            f.write(result.stdout)
            f.write("\\n\\n=== STDERR ===\\n")
            f.write(result.stderr)
        
        # Parse results
        suite_results = {
            "suite_name": suite_name,
            "exit_code": result.returncode,
            "log_file": str(log_file),
            "timestamp": datetime.now().isoformat(),
            "stdout_lines": len(result.stdout.split('\\n')),
            "stderr_lines": len(result.stderr.split('\\n'))
        }
        
        # Extract test counts from pytest output
        for line in result.stdout.split('\\n'):
            if " passed" in line or " failed" in line or " skipped" in line:
                suite_results["summary_line"] = line.strip()
                break
        
        return suite_results
    
    def map_existing_tests_to_vtp(self) -> Dict[str, List[str]]:
        """Map existing test files to VTP requirements"""
        mapping = {
            "Suite_A_Contract_Build": [
                "tests/integration/test_cli.py",
                "tests/integration/test_cli_phase0.py",
                "tests/unit/test_no_legacy_imports.py",
                "tests/unit/test_schemas.py"
            ],
            "Suite_B_PIT_Provenance": [
                "tests/unit/test_snapshot.py",
                "tests/unit/test_fields_asof.py",
                "tests/leakage/test_leakage.py",
                "tests/leakage/test_peer_leakage.py",
                "tests/unit/test_pit_assumed_policy.py"
            ],
            "Suite_C_Financial_Statements": [
                "tests/unit/test_projection.py",
                "tests/unit/test_path_statements.py",
                "tests/unit/test_policies_invariants.py",
                "tests/property/test_projection_properties.py"
            ],
            "Suite_D_Valuation_Methods": [
                "tests/unit/test_phase4_acceptance.py",
                "tests/unit/test_phase5_acceptance.py",
                "tests/unit/test_phase6_acceptance.py",
                "tests/unit/methods/test_rim_from_snapshot.py",
                "tests/unit/methods/test_rim_r2_common_equity.py"
            ],
            "Suite_E_Routing": [
                "tests/unit/test_profiles.py",
                "tests/unit/test_profiles_phase2.py",
                "tests/unit/test_methods_registry_phase2.py"
            ],
            "Suite_F_Ensemble": [
                "tests/unit/test_phase8_acceptance.py",
                "tests/property/test_ensemble_properties.py"
            ],
            "Suite_G_Market_Pricing": [
                "tests/unit/test_phase9_acceptance.py",
                "tests/property/test_exit_price_properties.py"
            ],
            "Suite_H_Returns": [
                "tests/unit/test_returns.py",
                "tests/unit/test_phase7_acceptance.py",
                "tests/property/test_return_properties.py",
                "tests/property/test_return_track_b_properties.py"
            ],
            "Suite_I_Properties": [
                "tests/property/test_properties.py",
                "tests/property/test_regime_properties.py",
                "tests/property/test_projection_properties.py"
            ],
            "Suite_J_Historical": [
                "tests/unit/test_evaluation.py",
                "tests/unit/test_walk_forward.py",
                "tests/integration/test_cli_evaluate.py",
                "tests/leakage/test_eval_weight_freeze.py"
            ],
            "Suite_K_Bundle_Replay": [
                "tests/unit/test_phase0_done.py" if (Path("/workspace/tests/unit") / "test_phase0_done.py").exists() else "tests/integration/test_cli_phase0.py",
                "tests/unit/test_bundle_validation.py",
                "tests/unit/test_seeding_metadata.py"
            ],
            "Leakage_Tests": [
                "tests/leakage/test_leakage.py",
                "tests/leakage/test_peer_leakage.py",
                "tests/leakage/test_regime_leakage.py",
                "tests/leakage/test_multiples_peer_leakage.py",
                "tests/leakage/test_eval_weight_freeze.py"
            ]
        }
        return mapping
    
    def execute_all_vtp_tests(self):
        """Execute all VTP-mapped tests"""
        print("VTP-0.1 Comprehensive Test Execution")
        print("=" * 70)
        
        # Collect environment
        print("\\nCollecting environment hashes...")
        self.results["hashes"] = self.collect_environment_hashes()
        
        # Get test mapping
        test_mapping = self.map_existing_tests_to_vtp()
        
        # Execute each suite
        all_suite_results = []
        for suite_name, test_files in test_mapping.items():
            # Filter to existing files
            existing_tests = [t for t in test_files if (self.workspace / t).exists()]
            if not existing_tests:
                print(f"WARNING: No tests found for {suite_name}")
                continue
            
            suite_result = self.run_test_suite(suite_name, existing_tests)
            all_suite_results.append(suite_result)
            self.results["test_results"][suite_name] = suite_result
        
        # Run VTP-specific tests
        vtp_tests = list((self.workspace / "tests/vtp_0_1").glob("suite_*/test_*.py"))
        if vtp_tests:
            vtp_paths = [str(t) for t in vtp_tests]
            suite_result = self.run_test_suite("VTP_New_Tests", vtp_paths)
            all_suite_results.append(suite_result)
            self.results["test_results"]["VTP_New_Tests"] = suite_result
        
        # Run all tests together for comprehensive coverage
        print("\\n=== Running comprehensive test suite ===")
        comprehensive_result = self.run_test_suite(
            "Comprehensive_All_Tests",
            ["tests/"]
        )
        self.results["test_results"]["Comprehensive"] = comprehensive_result
        
        return all_suite_results
    
    def generate_vtp_matrix(self):
        """Generate VTP acceptance criterion matrix"""
        matrix_rows = []
        
        # Load VTP requirements (simplified structure)
        vtp_criteria = self._load_vtp_criteria()
        
        for criterion in vtp_criteria:
            row = {
                "Criterion_ID": criterion["id"],
                "Criterion_Description": criterion["description"],
                "Test_IDs": ",".join(criterion.get("test_files", [])),
                "Status": criterion.get("status", "PENDING"),
                "Evidence_Files": ",".join(criterion.get("evidence", [])),
                "Exit_Code": criterion.get("exit_code", ""),
                "Notes": criterion.get("notes", "")
            }
            matrix_rows.append(row)
        
        # Write CSV matrix
        matrix_file = self.evidence / "vtp_acceptance_matrix.csv"
        with open(matrix_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(matrix_rows[0].keys()))
            writer.writeheader()
            writer.writerows(matrix_rows)
        
        # Write Markdown matrix
        md_file = self.evidence / "vtp_acceptance_matrix.md"
        with open(md_file, 'w') as f:
            f.write("# VTP-0.1 Acceptance Criterion Matrix\\n\\n")
            f.write("| Criterion ID | Description | Test IDs | Status | Evidence |\\n")
            f.write("|---|---|---|---|---|\\n")
            for row in matrix_rows:
                f.write(f"| {row['Criterion_ID']} | {row['Criterion_Description'][:50]} | {row['Test_IDs'][:30]} | {row['Status']} | {row['Evidence_Files'][:30]} |\\n")
        
        self.results["evidence_files"].append(str(matrix_file))
        self.results["evidence_files"].append(str(md_file))
    
    def _load_vtp_criteria(self) -> List[Dict[str, Any]]:
        """Load VTP criteria from audit-corrected mapping (100 items)
        
        AUDIT CORRECTION: 原硬编码只返回A-01到A-04四行。
        现从审计提供的corrected_mapping.json加载完整100项映射。
        """
        mapping_file = Path(__file__).parent / "fixtures" / "vtp_criteria_mapping.json"
        
        if not mapping_file.exists():
            # Fallback to minimal set if mapping not found
            print(f"WARNING: {mapping_file} not found, using minimal criteria")
            return [
                {"id": "A-01", "description": "Clean install", "test_files": [], "status": "UNVERIFIED"},
                {"id": "A-02", "description": "Offline synthetic run", "test_files": [], "status": "FAIL"},
            ]
        
        with open(mapping_file, 'r', encoding='utf-8') as f:
            full_mapping = json.load(f)
        
        # Convert audit mapping format to harness format
        criteria = []
        for item in full_mapping:
            criterion = {
                "id": item["id"],
                "description": item.get("acceptance_standard", "")[:100],  # First 100 chars
                "spec_lines": item.get("spec_lines", ""),
                "status": item.get("status", "UNVERIFIED"),
                "evidence": item.get("evidence", []),
                "test_nodes": [t["node"] for t in item.get("test_results_in_delivered_junit", [])],
                "observed_execution": item.get("observed_execution", ""),
                "missing_or_limitations": item.get("missing_or_limitations", "")
            }
            criteria.append(criterion)
        
        return criteria
    
    def generate_final_report(self):
        """Generate comprehensive VTP final report in Chinese"""
        report_file = self.evidence / "VTP-0.1_执行报告.md"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("# VMS-0.2 VTP-0.1 验证测试执行报告\\n\\n")
            f.write(f"**执行时间:** {datetime.now().isoformat()}\\n\\n")
            f.write(f"**基线提交:** {self.results['hashes'].get('baseline_commit', 'N/A')}\\n\\n")
            f.write(f"**Python版本:** {self.results['hashes'].get('python_version', 'N/A')}\\n\\n")
            
            f.write("## 1. 执行概要\\n\\n")
            f.write("本报告记录了针对VMS-0.2系统的VTP-0.1全面验证测试执行过程和结果。\\n\\n")
            
            f.write("## 2. 测试套件执行结果\\n\\n")
            for suite_name, result in self.results["test_results"].items():
                f.write(f"### {suite_name}\\n\\n")
                f.write(f"- **退出代码:** {result['exit_code']}\\n")
                f.write(f"- **执行时间:** {result['timestamp']}\\n")
                f.write(f"- **日志文件:** `{result['log_file']}`\\n")
                if "summary_line" in result:
                    f.write(f"- **测试摘要:** {result['summary_line']}\\n")
                f.write("\\n")
            
            f.write("## 3. 环境哈希值\\n\\n")
            f.write("```json\\n")
            f.write(json.dumps(self.results["hashes"], indent=2))
            f.write("\\n```\\n\\n")
            
            f.write("## 4. 证据文件清单\\n\\n")
            for evidence_file in self.results["evidence_files"]:
                f.write(f"- `{evidence_file}`\\n")
            
            f.write("\\n## 5. VTP验收判定\\n\\n")
            f.write("TODO: 根据测试结果填写判定\\n")
        
        print(f"\\n报告已生成: {report_file}")
        self.results["evidence_files"].append(str(report_file))
        
        # Save JSON results
        json_file = self.evidence / "vtp_execution_results.json"
        with open(json_file, 'w') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        return report_file


def main():
    workspace = Path("/workspace")
    evidence_dir = Path("/workspace/artifacts/vtp-0.1-evidence")
    
    harness = VTPExecutionHarness(workspace, evidence_dir)
    harness.execute_all_vtp_tests()
    harness.generate_vtp_matrix()
    report = harness.generate_final_report()
    
    print(f"\\n{'='*70}")
    print(f"VTP-0.1 执行完成")
    print(f"报告: {report}")
    print(f"证据目录: {evidence_dir}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
