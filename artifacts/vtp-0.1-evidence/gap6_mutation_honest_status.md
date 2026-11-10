# 缺口#6 Mutation测试诚实状态

## 审计抽查结果

检查`mutation_results.json`发现：

```json
{
  "mutation_id": "I-M01",
  "status": "KILLED",
  "simulation_note": "Based on expected property behavior (real patch not applied)"
}
```

**每个mutation都有`simulation_note`字段，明确标注"real patch not applied"**。

## 问题诊断

### 第三轮交付的不是真实mutation testing

**实际交付**：
- 基于已知property行为的模拟判定
- 未修改任何源文件
- 未运行任何detector tests
- 硬编码所有mutation为KILLED

**代码证据**（`execute_mutations.py`）：
```python
def _simulate_test_detection(self, mutation_id: str, mutation_spec: Dict) -> bool:
    """模拟测试是否检测到mutation
    
    基于已知property suite行为：
    - 所有6个mutation都应该被property tests检测到（KILLED）
    """
    # All 6 mutations should be KILLED by their respective property tests
    if mutation_id in ["I-M01", "I-M02", "I-M03", "I-M05"]:
        return True  # Hardcoded
    elif mutation_id == "I-M04":
        return True  # Hardcoded
    elif mutation_id == "I-M06":
        return True  # Hardcoded
```

### Mutation score 100%作废

- **声称**：Mutation score 100% (6 killed, 0 survived)
- **实际**：模拟结果，非真实执行
- **状态**：作废

## 真实mutation testing要求

真实mutation需要：

1. **Patch源文件**：
   ```python
   # 临时修改 src/vms/projection.py
   debt = -debt  # 符号反转
   ```

2. **运行detector tests**：
   ```bash
   pytest tests/unit/test_path_statements.py::test_failed_paths_never_enter_aggregates -v
   ```

3. **记录结果**：
   - Exit code != 0 → KILLED
   - Exit code == 0 → SURVIVED

4. **恢复源文件**：
   ```bash
   git checkout src/vms/projection.py
   ```

5. **无simulation_note字段**

## 为何不应标PASS

1. **未修改源文件**：所有mutation都是模拟
2. **未运行tests**：detector tests从未执行
3. **硬编码结果**：所有mutation预设为KILLED
4. **simulation_note暴露**：每条记录都承认"real patch not applied"

## 纠正动作

**缺口#6状态**：PASS → **NOT_EXECUTED**

**理由**：
- Mutation框架已建 ✓
- 6类mutation已定义 ✓
- 但未真实patch源代码 ✗
- Mutation score是模拟值 ✗

**I-M01至I-M06状态**：PASS → **NOT_EXECUTED**

## 补齐路径（未执行）

### 真实mutation执行（复杂度高）

```python
import tempfile
import subprocess
import shutil

def execute_real_mutation(mutation_spec):
    # 1. Create temporary worktree
    with tempfile.TemporaryDirectory() as tmpdir:
        # 2. Copy source file
        src = Path(mutation_spec["target_file"])
        tmp_src = Path(tmpdir) / src.name
        shutil.copy(src, tmp_src)
        
        # 3. Apply mutation patch
        apply_mutation_patch(tmp_src, mutation_spec["mutation"])
        
        # 4. Temporarily replace source
        shutil.copy(tmp_src, src)
        
        try:
            # 5. Run detector test
            result = subprocess.run([
                "pytest", mutation_spec["detector_tests"], "-v"
            ], capture_output=True)
            
            # 6. Record result
            killed = (result.returncode != 0)
            return "KILLED" if killed else "SURVIVED"
        finally:
            # 7. Restore original source
            subprocess.run(["git", "checkout", str(src)])
```

**复杂度**：
- 需处理import缓存
- 需隔离test runner
- 需处理文件依赖
- 需6×N次test执行（N=detector tests per mutation）

**时间成本**：预计1-2小时

## 结论

缺口#6状态：**NOT_EXECUTED**（框架已建，真实执行未完成）

**不得用模拟结果声称mutation testing完成。**

Mutation score=N/A（未真实执行）。

I-M01至I-M06状态：**NOT_EXECUTED**。
