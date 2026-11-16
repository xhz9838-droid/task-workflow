# -*- coding: utf-8 -*-
"""P11 Phase 3 — Verifier：结果验证质量门禁。

验证内容（P11 §五.1）：
    Git 验证   : 工作区/修改文件/diff/提交/越权修改/冲突
    测试验证   : 按任务类型**动态**确定（不默认跑全部）
    需求验证   : 覆盖需求/验收条件/遗漏/回归风险
    结果五态   : PASS / FAIL / BLOCKED / SKIPPED / NOT_RUN

**铁律**：BLOCKED / SKIPPED / NOT_RUN 绝不标记为 PASS。

BLOCKED 聚合（P11 §五.3）：多个测试因相同原因无法执行时，聚合为一条环境阻塞说明，
不为每项重复生成长篇恢复步骤。
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .models import VerifyCheck, VerifyReport, VerifyStatus
except ImportError:
    from models import VerifyCheck, VerifyReport, VerifyStatus  # type: ignore


def _iso_now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------- Git 验证
@dataclass
class GitEvidence:
    status: VerifyStatus
    changed_files: list[str] = field(default_factory=list)
    commit: str = ""
    uncommitted: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)  # 越权修改
    evidence: str = ""


class GitVerifier:
    """Git 状态验证。只读命令，不改仓库。"""

    def __init__(self, workdir: str):
        self.workdir = workdir

    def _run(self, *args: str) -> tuple[int, str]:
        try:
            p = subprocess.run(
                ["git", *args],
                cwd=self.workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except Exception as e:
            return -1, str(e)

    def verify(self, allowed_files: Optional[list[str]] = None, *, require_commit: bool = True) -> GitEvidence:
        """验证 Git 状态。

        allowed_files：文件所有权白名单（越权检测）。None 表示不检测。
        """
        if not os.path.isdir(os.path.join(self.workdir, ".git")) and not os.path.isdir(self.workdir):
            return GitEvidence(
                status=VerifyStatus.BLOCKED,
                evidence=f"工作目录不存在或非 Git 仓库: {self.workdir}",
            )

        # 1) HEAD commit
        rc, out = self._run("rev-parse", "HEAD")
        commit = out.strip() if rc == 0 else ""

        # 2) 工作区状态
        rc, out = self._run("status", "--porcelain")
        if rc != 0:
            return GitEvidence(status=VerifyStatus.BLOCKED, evidence=f"git status 失败: {out[:200]}")
        uncommitted = [l[3:].strip() for l in out.splitlines() if l.strip()]

        # 3) 最近提交的变更文件
        rc, out = self._run("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
        changed = [l.strip() for l in out.splitlines() if l.strip()]

        # 4) 越权检测
        out_of_scope: list[str] = []
        if allowed_files is not None:
            all_files = set(changed) | set(uncommitted)
            for f in all_files:
                if not any(self._match(f, a) for a in allowed_files):
                    out_of_scope.append(f)

        # 5) 冲突检测
        rc, out = self._run("diff", "--check")
        has_conflict = rc != 0 and bool(out.strip())

        # 判定
        if out_of_scope:
            return GitEvidence(
                status=VerifyStatus.FAIL,
                changed_files=changed,
                commit=commit,
                uncommitted=uncommitted,
                out_of_scope=out_of_scope,
                evidence=f"越权修改 {len(out_of_scope)} 个文件（超出分配范围）: {out_of_scope[:5]}",
            )
        if has_conflict:
            return GitEvidence(
                status=VerifyStatus.FAIL,
                changed_files=changed,
                commit=commit,
                uncommitted=uncommitted,
                evidence="存在冲突标记（<<<<<<< / >>>>>>>）",
            )
        if require_commit and not changed and not commit:
            return GitEvidence(
                status=VerifyStatus.FAIL,
                changed_files=[],
                commit="",
                evidence="无有效提交且无变更",
            )
        return GitEvidence(
            status=VerifyStatus.PASS,
            changed_files=changed,
            commit=commit,
            uncommitted=uncommitted,
            evidence=f"commit={commit[:8] if commit else 'none'}, changed={len(changed)}, uncommitted={len(uncommitted)}",
        )

    @staticmethod
    def _match(file_path: str, pattern: str) -> bool:
        fnmatch = __import__("fnmatch")
        return fnmatch.fnmatch(file_path, pattern) or file_path.startswith(pattern.rstrip("*"))


# --------------------------------------------------------------- 测试验证
@dataclass
class TestSpec:
    """单个测试项（动态选择，不默认全跑）"""

    name: str
    cmd: list[str] | None = None
    workdir: str = ""
    timeout: int = 600
    # 若无法在本机执行，标 blocked 并说明
    blocked_reason: str = ""
    user_skipped: bool = False


class TestVerifier:
    """测试执行 + 五态判定。"""

    def __init__(self, workdir: str = ""):
        self.workdir = workdir

    def run_one(self, spec: TestSpec) -> VerifyCheck:
        """执行单个测试。五态判定，绝不伪装 PASS。"""
        now = _iso_now()

        # 用户跳过
        if spec.user_skipped:
            return VerifyCheck(spec.name, VerifyStatus.SKIPPED, "用户指令跳过", now)

        # 环境阻塞
        if spec.blocked_reason:
            return VerifyCheck(spec.name, VerifyStatus.BLOCKED, spec.blocked_reason, now)

        # 无命令 → 未执行
        if not spec.cmd:
            return VerifyCheck(spec.name, VerifyStatus.NOT_RUN, "未配置执行命令", now)

        try:
            p = subprocess.run(
                spec.cmd,
                cwd=spec.workdir or self.workdir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=spec.timeout,
            )
        except subprocess.TimeoutExpired:
            return VerifyCheck(spec.name, VerifyStatus.FAIL, f"执行超时 {spec.timeout}s", now)
        except FileNotFoundError as e:
            return VerifyCheck(spec.name, VerifyStatus.BLOCKED, f"命令不存在: {e}", now)
        except Exception as e:
            return VerifyCheck(spec.name, VerifyStatus.FAIL, f"执行异常: {e}", now)

        tail = ((p.stdout or "") + (p.stderr or ""))[-400:].strip()
        if p.returncode == 0:
            return VerifyCheck(spec.name, VerifyStatus.PASS, f"exit=0 | {tail[:150]}", now)
        return VerifyCheck(spec.name, VerifyStatus.FAIL, f"exit={p.returncode} | {tail[:150]}", now)


# --------------------------------------------------------------- BLOCKED 聚合
def aggregate_blocked(checks: list[VerifyCheck]) -> Optional[str]:
    """把同因 BLOCKED 聚合成一条环境阻塞说明（P11 §五.3）。

    不为每项重复生成长篇恢复步骤 —— 浪费时间且无用。
    """
    blocked = [c for c in checks if c.status == VerifyStatus.BLOCKED]
    if not blocked:
        return None

    by_reason: dict[str, list[str]] = defaultdict(list)
    for c in blocked:
        key = c.evidence.split("|")[0].strip()[:60] or "未知原因"
        by_reason[key].append(c.check_name)

    lines = [f"环境阻塞 {len(blocked)} 项（{len(by_reason)} 类原因）："]
    for reason, names in by_reason.items():
        lines.append(f"  · {reason} → 影响 {len(names)} 项: {', '.join(names)}")
    lines.append("待环境就绪后补跑上述检查；当前不计入通过。")
    return "\n".join(lines)


# --------------------------------------------------------------- 总验证器
class Verifier:
    """统一验证入口。"""

    def __init__(self, workdir: str = ""):
        self.workdir = workdir
        self.git = GitVerifier(workdir) if workdir else None
        self.tests = TestVerifier(workdir)

    def verify(
        self,
        *,
        allowed_files: Optional[list[str]] = None,
        test_specs: Optional[list[TestSpec]] = None,
        requirement_checks: Optional[list[tuple[str, bool, str]]] = None,
        require_commit: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> VerifyReport:
        """执行完整验证，返回 VerifyReport。

        requirement_checks: [(名称, 是否满足, 说明), ...]
        """
        report = VerifyReport()
        checks: list[VerifyCheck] = []

        # 1) Git
        if self.git:
            ge = self.git.verify(allowed_files, require_commit=require_commit)
            report.git_status = ge.status
            report.changed_files = ge.changed_files
            report.commit = ge.commit
            checks.append(VerifyCheck("git", ge.status, ge.evidence))
            if on_progress:
                on_progress(f"git: {ge.status.value} {ge.evidence}")

        # 2) Tests（动态）
        for spec in test_specs or []:
            if on_progress:
                on_progress(f"test {spec.name}: 执行中...")
            c = self.tests.run_one(spec)
            report.tests[spec.name] = c.status
            checks.append(c)
            if on_progress:
                on_progress(f"test {spec.name}: {c.status.value}")

        # 3) Requirements
        if requirement_checks:
            for name, ok, note in requirement_checks:
                st = VerifyStatus.PASS if ok else VerifyStatus.FAIL
                checks.append(VerifyCheck(name, st, note))
            report.requirements_status = (
                VerifyStatus.PASS
                if all(ok for _, ok, _ in requirement_checks)
                else VerifyStatus.FAIL
            )
            report.requirements_details = [f"{n}: {note}" for n, ok, note in requirement_checks]
        else:
            report.requirements_status = VerifyStatus.NOT_RUN

        # 4) BLOCKED 聚合
        report.blocked_summary = aggregate_blocked(checks)
        report.checks = checks

        # 5) overall（真实证据，绝不把非 PASS 算成功）
        report.compute_overall()
        return report

    @staticmethod
    def to_json(report: VerifyReport) -> str:
        import json

        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
