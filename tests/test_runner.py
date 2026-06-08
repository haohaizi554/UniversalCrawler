"""测试运行引擎 — 封装 pytest 调用与结果解析。

提供：
- 同步运行测试
- 异步/后台运行（QThread 友好）
- 解析 pytest 输出为结构化结果
- 进度回调（适用于 GUI 进度条）
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class TestResult:
    """单个测试类别运行结果。"""
    category_id: str
    category_name: str
    file_count: int
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration: float = 0.0
    returncode: int = 0
    output: str = ""
    success: bool = False
    started_at: float = 0.0
    finished_at: float = 0.0
    failed_tests: list[str] = field(default_factory=list)

    def total(self) -> int:
        return self.passed + self.failed + self.skipped + self.errors

    def to_dict(self) -> dict:
        return {
            "category_id": self.category_id,
            "category_name": self.category_name,
            "file_count": self.file_count,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "total": self.total(),
            "duration": self.duration,
            "success": self.success,
            "failed_tests": self.failed_tests,
        }


# 进度回调签名：(当前文件索引, 总文件数, 文件名, 输出行)
ProgressCallback = Callable[[int, int, str, str], None]


def _parse_pytest_output(output: str) -> tuple[int, int, int, int, list[str]]:
    """解析 pytest 输出。

    Returns:
        (passed, failed, skipped, errors, failed_test_names)
    """
    passed = failed = skipped = errors = 0
    failed_names: list[str] = []

    # 匹配 summary 行: "5 passed, 2 failed, 1 skipped in 1.23s"
    #   或: "=== 5 passed, 2 failed in 1.23s ==="
    #   或: "31 passed in 60.72s (0:01:00)"
    summary_match = re.search(
        r"(?:=+\s*)?([\d\w\s,]+\b(?:passed|failed|skipped|error)\b[\d\w\s,]*)"
        r"\s+(?:in\s+[\d.]+s|"
        r"in\s+\d+m[\d.]+s)\s*"
        r"(?:\([\d:]+?\))?\s*=*",
        output,
    )
    if summary_match:
        stats = summary_match.group(1)
        for stat in re.findall(r"(\d+)\s+(passed|failed|skipped|error)", stats):
            count, label = stat
            count = int(count)
            if label == "passed":
                passed = count
            elif label == "failed":
                failed = count
            elif label == "skipped":
                skipped = count
            elif label == "error":
                errors = count

    # 匹配 FAILED 行（短名）
    for m in re.finditer(r"^FAILED\s+(\S+)", output, re.MULTILINE):
        failed_names.append(m.group(1))

    return passed, failed, skipped, errors, failed_names


def run_category(
    category_id: str,
    category_name: str,
    files: list[str],
    verbose: bool = False,
    no_failfast: bool = True,
    timeout: int = 600,
    progress_cb: Optional[ProgressCallback] = None,
    extra_args: Optional[list[str]] = None,
) -> TestResult:
    """运行一个测试类别。

    Args:
        category_id: 类别 ID
        category_name: 类别显示名
        files: 测试文件列表（相对项目根）
        verbose: 是否详细输出
        no_failfast: 是否遇失败不停止
        timeout: 单个文件超时（秒）
        progress_cb: 进度回调
        extra_args: 额外的 pytest 参数

    Returns:
        TestResult
    """
    result = TestResult(
        category_id=category_id,
        category_name=category_name,
        file_count=len(files),
    )
    result.started_at = time.time()

    if not files:
        result.success = True
        result.finished_at = time.time()
        return result

    # 过滤存在的文件
    existing = [f for f in files if (PROJECT_ROOT / f).exists()]
    missing = [f for f in files if f not in existing]
    if missing:
        result.output += f"⚠ 缺少测试文件: {missing}\n"

    if not existing:
        result.success = True
        result.finished_at = time.time()
        return result

    # 构造 pytest 命令
    pytest_args = ["--tb=line"]  # 简短的错误回溯
    if verbose:
        pytest_args.append("-v")
    else:
        pytest_args.append("-q")
    if not no_failfast:
        pytest_args.append("-x")
    if extra_args:
        pytest_args.extend(extra_args)

    cmd = [
        sys.executable, "-m", "pytest",
        *existing,
        *pytest_args,
    ]

    # #region debug-point B:test-runner-command
    try:
        import json, urllib.request, time as _dbg_time; _p='.dbg/cli-platform-regressions.env'; _u='http://127.0.0.1:7777/event'; _s='cli-platform-regressions'; exec("try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept Exception: pass"); urllib.request.urlopen(urllib.request.Request(_u, data=json.dumps({"sessionId":_s,"runId":"pre-fix","hypothesisId":"B","location":"tests/test_runner.py:run_category","msg":"[DEBUG] run_category aggregate cmd built","data":{"category_id":category_id,"verbose":verbose,"no_failfast":no_failfast,"extra_args":extra_args or [],"cmd":cmd,"existing":existing},"ts":int(_dbg_time.time()*1000)}).encode(), headers={"Content-Type":"application/json"}), timeout=0.5).read()
    except Exception:
        pass
    # #endregion

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    # 禁用 Qt 弹窗（offscreen）
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    # 逐文件运行（便于进度回调）
    agg_passed = agg_failed = agg_skipped = agg_errors = 0
    agg_failed_names: list[str] = []
    start = time.time()
    full_output = ""
    for idx, f in enumerate(existing):
        if progress_cb:
            try:
                progress_cb(idx, len(existing), f, "")
            except Exception:
                pass
        single_cmd = [
            sys.executable, "-m", "pytest",
            f,
            *pytest_args,
        ]
        # #region debug-point B:test-runner-single-cmd
        try:
            import json, urllib.request, time as _dbg_time; _p='.dbg/cli-platform-regressions.env'; _u='http://127.0.0.1:7777/event'; _s='cli-platform-regressions'; exec("try:\n with open(_p, encoding='utf-8') as f: c=f.read(); _u=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SERVER_URL=')),_u); _s=next((l.split('=',1)[1] for l in c.split('\\n') if l.startswith('DEBUG_SESSION_ID=')),_s)\nexcept Exception: pass"); urllib.request.urlopen(urllib.request.Request(_u, data=json.dumps({"sessionId":_s,"runId":"pre-fix","hypothesisId":"B","location":"tests/test_runner.py:single_cmd","msg":"[DEBUG] run_category single file cmd built","data":{"file":f,"verbose":verbose,"single_cmd":single_cmd},"ts":int(_dbg_time.time()*1000)}).encode(), headers={"Content-Type":"application/json"}), timeout=0.5).read()
        except Exception:
            pass
        # #endregion
        try:
            cp = subprocess.run(
                single_cmd,
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            file_output = cp.stdout + cp.stderr
            p, fa, sk, er, names = _parse_pytest_output(file_output)
            agg_passed += p
            agg_failed += fa
            agg_skipped += sk
            agg_errors += er
            agg_failed_names.extend(names)
            full_output += f"\n=== {f} ===\n{file_output}\n"
            if progress_cb:
                progress_cb(idx + 1, len(existing), f, file_output[-500:])
        except subprocess.TimeoutExpired:
            full_output += f"\n=== {f} ===\n[TIMEOUT after {timeout}s]\n"
            agg_errors += 1
        except Exception as e:
            full_output += f"\n=== {f} ===\n[ERROR: {e}]\n"
            agg_errors += 1

    result.passed = agg_passed
    result.failed = agg_failed
    result.skipped = agg_skipped
    result.errors = agg_errors
    result.failed_tests = agg_failed_names
    result.output = full_output
    result.duration = time.time() - start
    result.returncode = 0 if agg_failed == 0 and agg_errors == 0 else 1
    result.success = (result.returncode == 0)
    result.finished_at = time.time()
    return result


def run_categories(
    category_ids: list[str],
    verbose: bool = False,
    no_failfast: bool = True,
    progress_cb: Optional[ProgressCallback] = None,
) -> list[TestResult]:
    """顺序运行多个测试类别。

    Args:
        category_ids: 类别 ID 列表
        verbose: 详细输出
        no_failfast: 遇失败不停止
        progress_cb: 进度回调（每次切类别时触发一次）

    Returns:
        TestResult 列表
    """
    from test_registry import get_category, get_resolved_files  # noqa: E402

    results: list[TestResult] = []
    for cid in category_ids:
        cat = get_category(cid)
        files = get_resolved_files(cid)
        if progress_cb:
            try:
                progress_cb(-1, len(category_ids), cid, f"开始: {cat.name}")
            except Exception:
                pass
        result = run_category(
            category_id=cid,
            category_name=cat.name,
            files=files,
            verbose=verbose,
            no_failfast=no_failfast,
        )
        results.append(result)
    return results


def format_summary(results: list[TestResult]) -> str:
    """格式化结果汇总（多行文本）。"""
    lines = ["=" * 70, "测试结果汇总", "=" * 70]
    total_passed = total_failed = total_skipped = total_errors = 0
    total_duration = 0.0
    for r in results:
        status = "✓ PASS" if r.success else "✗ FAIL"
        lines.append(
            f"  [{status}] {r.category_name:14s} "
            f"P={r.passed:3d} F={r.failed:2d} S={r.skipped:2d} E={r.errors:2d} "
            f"({r.duration:6.2f}s)"
        )
        total_passed += r.passed
        total_failed += r.failed
        total_skipped += r.skipped
        total_errors += r.errors
        total_duration += r.duration
    lines.append("-" * 70)
    lines.append(
        f"  总计: P={total_passed} F={total_failed} "
        f"S={total_skipped} E={total_errors} 耗时={total_duration:.2f}s"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    # 简单命令行测试
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="unit")
    args = parser.parse_args()
    results = run_categories([args.category], verbose=True)
    print(format_summary(results))
    sys.exit(0 if all(r.success for r in results) else 1)
