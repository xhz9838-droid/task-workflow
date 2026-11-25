# -*- coding: utf-8 -*-
"""工作日志工时计算（纯函数，不依赖禅道客户端）。

规则：
- 总工时优先级：计划工作日（estStarted..deadline，周一至周五）× 8 → 任务 estimate。
- 本次 consumed = 总工时 × 进度 − 任务当前 consumed（增量）。
- left = 总工时 − 总工时 × 进度。
- 无可靠基线时抛 NO_BASELINE，不编造工时。
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class WorklogError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _dec(value, default=None) -> Decimal:
    if value is None or str(value).strip() == "":
        if default is not None:
            return default
        raise WorklogError("INVALID_NUMBER", "无法解析数值：%r" % (value,))
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        if default is not None:
            return default
        raise WorklogError("INVALID_NUMBER", "无法解析数值：%r" % (value,))


def _date(value):
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def planned_workdays(start, end) -> int:
    """含首尾的周一至周五天数；日期缺失/倒置返回 0。"""
    s, e = _date(start), _date(end)
    if not s or not e or e < s:
        return 0
    days = 0
    cur = s
    while cur <= e:
        if cur.weekday() < 5:
            days += 1
        cur += datetime.timedelta(days=1)
    return days


def total_hours(task: dict, explicit=None) -> Decimal:
    """总工时基线：显式 > 计划工作日×8 > estimate；都没有则拒绝。"""
    if explicit is not None and str(explicit).strip() != "":
        value = _dec(explicit)
        if value <= 0:
            raise WorklogError("NO_BASELINE", "总工时必须大于 0")
        return value
    days = planned_workdays(task.get("estStarted"), task.get("deadline"))
    if days > 0:
        return Decimal(days * 8)
    est = _dec(task.get("estimate"), default=Decimal(0))
    if est > 0:
        return est
    raise WorklogError(
        "NO_BASELINE",
        "任务缺少完整计划周期（estStarted/deadline）且无 estimate，无法可靠计算总工时；"
        "请提供 --total-hours 或补全禅道计划字段",
    )


def _fmt(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_entry(task: dict, *, progress, work: str, stage: str = "milestone",
                total=None, date: str = "", task_id: str = "") -> dict:
    """生成 workhour 行；已到/超过目标进度时返回 skipped（不重复写）。"""
    text = (work or "").strip()
    if not text:
        raise WorklogError("EMPTY_WORK", "工作日志内容不能为空")
    try:
        pct = Decimal(str(progress))
    except (InvalidOperation, ValueError):
        raise WorklogError("INVALID_PROGRESS", "进度必须是 0–100 的数字")
    if pct < 0 or pct > 100:
        raise WorklogError("INVALID_PROGRESS", "进度必须在 0–100 之间")

    total_h = total_hours(task, total)
    prior = _dec(task.get("consumed"), default=Decimal(0))
    cumulative = (total_h * pct / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    delta = cumulative - prior
    left = total_h - cumulative
    if left < 0:
        left = Decimal(0)

    tid = str(task_id or task.get("id") or "")
    marker = "[AI-%s-%s]" % (tid, stage or "milestone")
    base = {
        "task_id": tid, "stage": stage or "milestone", "marker": marker,
        "progress": _fmt(pct), "total": _fmt(total_h),
        "consumed_before": _fmt(prior), "cumulative": _fmt(cumulative),
        "left": _fmt(left),
    }
    if delta <= 0:
        return dict(base, ok=True, skipped=True, reason="ALREADY_AT_OR_ABOVE_PROGRESS",
                    consumed=0.0,
                    message="当前 consumed=%s 已达到进度 %s%% 对应工时，跳过重复记录"
                            % (_fmt(prior), _fmt(pct)))
    if delta > total_h:
        delta = total_h
    body = (
        "%s %s\n"
        "当前整体进度：%s%%\n"
        "本次消耗：%s 小时\n"
        "剩余工时：%s 小时"
        % (marker, text, _fmt(pct), _fmt(delta), _fmt(left))
    )
    day = date or datetime.date.today().isoformat()
    return dict(
        base, ok=True, skipped=False, consumed=_fmt(delta), left=_fmt(left),
        date=day, work=body,
        message="本次记录 consumed=%s left=%s（总工时 %s）"
                % (_fmt(delta), _fmt(left), _fmt(total_h)),
    )
