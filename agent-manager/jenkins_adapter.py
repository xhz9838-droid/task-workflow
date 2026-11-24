# -*- coding: utf-8 -*-
"""P11 Phase 5 — Jenkins Adapter：CI 接管。

流程（P11 §九）：
    Agent 改代码 → Verifier 初验 → Git 检查 → Jenkins ai-test-* Job
    → 取结果 → Verifier 二验 → 禅道记录 + 钉钉通知

**复用现有 `scripts/jenkins_run.py`**，不重写 REST 客户端。

硬约束：
    - 只允许 `ai-test-*` Job（P11 §九.5）
    - 禁止生产构建/部署
    - Jenkins 不可用 → 记 BLOCKED，**不伪装通过**
    - 支持 build number 关联、执行超时
    - 不得把「Jenkins 未执行」标记为通过

当前基础设施现状（见 reports/P11_AUDIT.md）：
    现有白名单 Job 为生产部署 Job（ct-jeebootx-* / jeebootx-ui），
    **不是** ai-test-*。故本 Adapter 先做接口 + Mock + 连接检查，
    真实执行待 ai-test-* Job 就绪。
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from .exceptions import JenkinsUnavailableError
    from .models import VerifyCheck, VerifyStatus
except ImportError:
    from exceptions import JenkinsUnavailableError  # type: ignore
    from models import VerifyCheck, VerifyStatus  # type: ignore

JENKINS_SCRIPT = os.path.join(_ROOT, "scripts", "jenkins_run.py")
DEFAULT_ALLOWED_PREFIX = "ai-test-"

# Jenkins result → VerifyStatus
RESULT_MAP = {
    "SUCCESS": VerifyStatus.PASS,
    "UNSTABLE": VerifyStatus.FAIL,  # 有测试失败 → 不算通过，须分析
    "FAILURE": VerifyStatus.FAIL,
    "ABORTED": VerifyStatus.FAIL,
    "NOT_BUILT": VerifyStatus.NOT_RUN,
}


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class JenkinsAdapter:
    """Jenkins 接管。白名单强制 + 超时 + Mock 支持。"""

    def __init__(
        self,
        *,
        allowed_prefix: str = DEFAULT_ALLOWED_PREFIX,
        enabled: bool = True,
        mock: bool = False,
        timeout_seconds: int = 1800,
        logger=None,
    ):
        self.allowed_prefix = allowed_prefix
        self.enabled = enabled
        self.mock = mock
        self.timeout_seconds = timeout_seconds
        self._log = logger or (lambda m: None)

    # ------------------------------------------------------- 白名单
    def is_allowed(self, job: str) -> bool:
        """P11 §九.5：只允许 ai-test-* Job。生产 Job 一律拒绝。"""
        return bool(job) and job.startswith(self.allowed_prefix)

    def _guard(self, job: str) -> None:
        if not self.is_allowed(job):
            raise JenkinsUnavailableError(
                f"拒绝操作 Job [{job}]：不在 {self.allowed_prefix}* 白名单内。"
                f"禁止生产构建/部署。"
            )

    # ------------------------------------------------------- 环境检查
    def check_infra(self) -> dict:
        """连接状态检查。返回可执行性与待办清单。"""
        result = {
            "adapter_enabled": self.enabled,
            "mock_mode": self.mock,
            "script_exists": os.path.exists(JENKINS_SCRIPT),
            "env_configured": False,
            "allowed_prefix": self.allowed_prefix,
            "ready_for_real": False,
            "todo": [],
        }
        # 检查 .env 是否配 Jenkins
        envf = os.path.join(_ROOT, ".env")
        if not os.path.exists(envf):
            envf = os.path.join(_ROOT, "config", ".env")
        if os.path.exists(envf):
            txt = open(envf, encoding="utf-8", errors="replace").read()
            has_url = "JENKINS_URL=" in txt and not txt.split("JENKINS_URL=")[1][:1].startswith("\n")
            result["env_configured"] = has_url
        else:
            result["todo"].append("创建 .env 并配置 JENKINS_URL / JENKINS_USER / JENKINS_TOKEN")

        if not result["script_exists"]:
            result["todo"].append("scripts/jenkins_run.py 不存在")
        if not result["env_configured"]:
            result["todo"].append("Jenkins 凭据未配置")
        result["todo"].append(f"需创建 {self.allowed_prefix}* 测试 Job（现有 Job 均为生产部署 Job）")
        result["todo"].append("Jenkins 节点需 Git 只读凭据 + Tool Check（Java/Maven/Node）")

        result["ready_for_real"] = bool(
            result["script_exists"] and result["env_configured"] and self.enabled and not self.mock
        )
        return result

    # ------------------------------------------------------- 触发
    def trigger(
        self,
        *,
        job: str,
        project_key: str,
        task_id: str,
        repo_url: str = "",
        branch: str = "",
        commit: str = "",
        scope: str = "unit",
        wait: bool = True,
    ) -> dict:
        """触发构建。返回 {status, build, result, verify_status, evidence}。"""
        self._guard(job)

        if not self.enabled:
            return self._blocked("Jenkins 适配器未启用")

        if self.mock:
            return {
                "status": "MOCK",
                "build": 0,
                "result": "MOCK",
                "verify_status": VerifyStatus.NOT_RUN.value,
                "evidence": "Mock 模式，未真实执行（不计为通过）",
                "job": job,
            }

        infra = self.check_infra()
        if not infra["ready_for_real"]:
            return self._blocked(
                "Jenkins 基础设施未就绪: " + "; ".join(infra["todo"][:3])
            )

        args = [
            "trigger",
            "--job", job,
            "--task", str(task_id),
            "--repo-url", repo_url,
            "--branch", branch or "main",
            "--scope", scope,
        ]
        if commit:
            args += ["--commit", commit]
        if wait:
            args += ["--wait"]

        rc, out = self._run_jenkins(args, timeout=self.timeout_seconds)
        if rc != 0:
            # Jenkins 调用失败 → BLOCKED，不伪装通过
            return self._blocked(f"Jenkins 调用失败 rc={rc}: {out[:200]}")

        result = self._parse_result(out)
        vs = RESULT_MAP.get(result.get("result", ""), VerifyStatus.BLOCKED)
        return {
            "status": "EXECUTED",
            "job": job,
            "build": result.get("build"),
            "result": result.get("result"),
            "verify_status": vs.value,
            "evidence": out[-300:],
            "raw": result,
        }

    # ------------------------------------------------------- 查询
    def get_status(self, job: str, build: int) -> dict:
        self._guard(job)
        if self.mock:
            return {"result": "MOCK", "building": False}
        rc, out = self._run_jenkins(["status", "--job", job, "--build", str(build)])
        return self._parse_result(out)

    def get_report(self, job: str, build: int) -> dict:
        self._guard(job)
        if self.mock:
            return {"result": "MOCK"}
        rc, out = self._run_jenkins(["report", "--job", job, "--build", str(build)])
        return {"raw": out[-1000:], "rc": rc}

    def get_logs(self, job: str, build: int, tail: int = 100) -> str:
        self._guard(job)
        if self.mock:
            return "[mock logs]"
        rc, out = self._run_jenkins(["logs", "--job", job, "--build", str(build), "--tail", str(tail)])
        return out

    # ------------------------------------------------------- 结果 → VerifyCheck
    def to_verify_check(self, name: str, result: dict) -> VerifyCheck:
        vs_raw = result.get("verify_status")
        try:
            vs = VerifyStatus(vs_raw) if vs_raw else VerifyStatus.BLOCKED
        except Exception:
            vs = VerifyStatus.BLOCKED
        return VerifyCheck(
            check_name=name,
            status=vs,
            evidence=f"job={result.get('job','?')} build={result.get('build','?')} "
                     f"result={result.get('result','?')} | {str(result.get('evidence',''))[:120]}",
        )

    def to_verify_check_blocked(self, name: str, reason: str) -> VerifyCheck:
        return VerifyCheck(check_name=name, status=VerifyStatus.BLOCKED, evidence=reason)

    # ------------------------------------------------------- 内部
    def _blocked(self, reason: str) -> dict:
        return {
            "status": "BLOCKED",
            "build": None,
            "result": None,
            "verify_status": VerifyStatus.BLOCKED.value,
            "evidence": reason,
        }

    def _run_jenkins(self, args: list[str], timeout: int = 300) -> tuple[int, str]:
        if not os.path.exists(JENKINS_SCRIPT):
            raise JenkinsUnavailableError(f"Jenkins 适配器脚本不存在: {JENKINS_SCRIPT}")
        try:
            p = subprocess.run(
                [sys.executable, "-I", JENKINS_SCRIPT, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            raise JenkinsUnavailableError(f"Jenkins 调用超时 {timeout}s")

    @staticmethod
    def _parse_result(out: str) -> dict:
        """从 jenkins_run.py 输出解析 build/result。"""
        import re

        result: dict = {}
        m = re.search(r"build[\s:=#]+(\d+)", out, re.I)
        if m:
            result["build"] = int(m.group(1))
        m = re.search(r"\b(SUCCESS|FAILURE|UNSTABLE|ABORTED|NOT_BUILT)\b", out)
        if m:
            result["result"] = m.group(1)
        return result
