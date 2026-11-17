
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jenkins 工作流构建调度脚本。

只允许触发以下白名单 Job：
  - ct-jeebootx-sanitation  后端
  - jeebootx-ui             Web 前端

禁止触发其他 Job，包括未经授权的部署 Job。

凭据从项目根目录 .env 读取，不输出到日志。

用法：
  # 检查 Jenkins 连通性、认证、两个白名单 Job
  python -I scripts/jenkins_run.py toolcheck

  # 触发后端构建
  python -I scripts/jenkins_run.py trigger \
    --job ct-jeebootx-sanitation \
    --task 3413 \
    --repo-url https://codeup.example.com/jeebootx/jeebootx-sanitation.git \
    --branch ai/zt-3413 \
    --scope build --wait

  # 触发 Web 构建
  python -I scripts/jenkins_run.py trigger \
    --job jeebootx-ui \
    --task 3413 \
    --repo-url https://codeup.example.com/jeebootx/jeebootx-ui.git \
    --branch ai/zt-3413 \
    --scope build --wait

  # 查询构建状态
  python -I scripts/jenkins_run.py status \
    --job jeebootx-ui --build 12

  # 查询测试报告
  python -I scripts/jenkins_run.py report \
    --job jeebootx-ui --build 12

  # 查看最近 100 行控制台日志
  python -I scripts/jenkins_run.py logs \
    --job jeebootx-ui --build 12 --tail 100

返回码：
  0 = 成功
  1 = 构建中
  2 = 构建不稳定 / 测试存在失败
  3 = 操作失败
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


# ============================================================
# 基础配置
# ============================================================

def _resolve_root() -> str:
    """工作流根目录（统一解析，见 _home.py）；解析失败回退脚本所在仓库。"""
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from _home import resolve_workflow_home
        return resolve_workflow_home()[0]
    except Exception:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


ROOT = _resolve_root()

# 严格白名单：从 config/adapters/jenkins.yaml → jenkins.jobs 加载（项目无关）。
# 不允许通过命令行传入白名单外的 Job；部署 Job 一律禁止自动触发。
def _load_whitelist():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _config import load_config, get as _get
        _jobs = _get(load_config(), "jenkins.jobs", None)
        if _jobs:
            return set(_jobs)
    except Exception:
        pass
    return set()


WHITELIST = _load_whitelist()

# Jenkins 构建参数映射。
# 如果 Jenkins Job 中的参数名称不同，只修改这里。
PARAM_NAMES = {
    "repo_url": "REPO_URL",
    "branch": "GIT_BRANCH",
    "commit": "GIT_COMMIT",
    "task": "ZENTAO_TASK_ID",
    "workflow": "WORKFLOW_ID",
    "scope": "TEST_SCOPE",
}

HTTP_TIMEOUT = 30
QUEUE_MAX_ROUNDS = 60
QUEUE_INTERVAL = 3
BUILD_MAX_ROUNDS = 120
BUILD_INTERVAL = 5


# ============================================================
# 环境变量
# ============================================================

def _load_env():
    """加载项目根目录 .env，不覆盖系统环境变量。"""

    envfile = os.path.join(ROOT, ".env")

    if os.path.exists(envfile):
        with open(envfile, encoding="utf-8-sig") as f:
            for raw_line in f:
                line = raw_line.strip()

                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # 支持 KEY="VALUE" 和 KEY='VALUE'
                if (
                    len(value) >= 2
                    and value[0] == value[-1]
                    and value[0] in ("'", '"')
                ):
                    value = value[1:-1]

                os.environ.setdefault(key, value)

    required = (
        "JENKINS_URL",
        "JENKINS_USER",
        "JENKINS_TOKEN",
    )

    missing = [key for key in required if not os.environ.get(key)]

    if missing:
        raise SystemExit(
            f"缺少环境变量：{', '.join(missing)}。"
            f"请检查项目根目录 {envfile}"
        )

    base = os.environ["JENKINS_URL"].rstrip("/")
    parsed = urllib.parse.urlparse(base)

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SystemExit("JENKINS_URL 格式错误，必须是有效的 HTTP/HTTPS 地址")

    if parsed.username or parsed.password:
        raise SystemExit("JENKINS_URL 不允许包含用户名或密码")


def _base_url():
    return os.environ["JENKINS_URL"].rstrip("/")


def _job_path(job):
    """Job 路径统一编码，且必须经过白名单校验。"""
    _verify_whitelist(job)
    return f"/job/{urllib.parse.quote(job, safe='')}"


def _url(path):
    return _base_url() + path


def _auth():
    from base64 import b64encode

    username = os.environ["JENKINS_USER"]
    token = os.environ["JENKINS_TOKEN"]

    value = f"{username}:{token}".encode("utf-8")
    return "Basic " + b64encode(value).decode("ascii")


# ============================================================
# 白名单校验
# ============================================================

def _verify_whitelist(job):
    if job not in WHITELIST:
        raise SystemExit(
            f"拒绝操作：Job [{job}] 不在白名单中。\n"
            f"允许的 Job：{', '.join(sorted(WHITELIST))}"
        )


def _verify_build_number(build):
    if not re.fullmatch(r"\d+", str(build)):
        raise SystemExit(f"非法 Build Number：{build}")


def _verify_job(job):
    """检查 Jenkins 中是否真实存在该 Job。"""

    _verify_whitelist(job)

    result = _req(f"{_job_path(job)}/api/json?tree=name,buildable")

    if (
        isinstance(result, dict)
        and result.get("name") == job
        and result.get("buildable") is True
    ):
        return True

    raise SystemExit(
        f"Job 不存在或不可构建：{job}；"
        f"返回信息：{_safe_error(result)}"
    )


# ============================================================
# HTTP 请求
# ============================================================

def _safe_error(result):
    """限制错误响应长度，避免输出过多服务端信息。"""

    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)[:1000]

    return str(result)[:1000]


def _req(path, method="GET", body=None, accept="application/json",
         timeout=HTTP_TIMEOUT):
    """普通 HTTP 请求。"""

    headers = {
        "Authorization": _auth(),
        "Accept": accept,
    }

    data = None

    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        _url(path),
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")

            if "json" in content_type:
                return json.loads(raw.decode("utf-8"))

            return raw.decode("utf-8", errors="replace")

    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")

        return {
            "error": exc.code,
            "body": body_text[:2000],
        }

    except urllib.error.URLError as exc:
        return {
            "error": -1,
            "body": str(exc.reason),
        }

    except TimeoutError:
        return {
            "error": -1,
            "body": "请求超时",
        }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """保留 Jenkins POST 的 302 响应，以读取 Queue Location。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post_form(path, params, headers=None):
    """
    POST 表单请求。

    Jenkins 通常返回 201 或 302，并通过 Location 返回 Queue URL。
    禁止自动跟随重定向，避免丢失 Queue 信息。
    """

    request_headers = {
        "Authorization": _auth(),
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    if headers:
        request_headers.update(headers)

    data = urllib.parse.urlencode(params).encode("utf-8")

    request = urllib.request.Request(
        _url(path),
        data=data,
        headers=request_headers,
        method="POST",
    )

    opener = urllib.request.build_opener(_NoRedirectHandler())

    try:
        with opener.open(request, timeout=15) as response:
            return {
                "status": response.status,
                "location": response.headers.get("Location", ""),
            }

    except urllib.error.HTTPError as exc:
        # Jenkins 302 是正常的入队响应
        if exc.code in (201, 302, 303):
            return {
                "status": exc.code,
                "location": exc.headers.get("Location", ""),
            }

        # 不输出完整响应，避免意外泄露敏感信息
        return {
            "error": exc.code,
            "body": exc.read().decode("utf-8", errors="replace")[:1000],
        }

    except urllib.error.URLError as exc:
        return {
            "error": -1,
            "body": str(exc.reason),
        }


# ============================================================
# Jenkins CSRF
# ============================================================

def _crumb():
    """获取 Jenkins CSRF crumb。未启用时返回 None。"""

    result = _req("/crumbIssuer/api/json")

    if isinstance(result, dict) and result.get("crumb"):
        return (
            result["crumb"],
            result.get("crumbRequestField", "Jenkins-Crumb"),
        )

    # Jenkins 未启用 CSRF 时通常返回 404
    if isinstance(result, dict) and result.get("error") == 404:
        return None, None

    if isinstance(result, dict) and "error" in result:
        raise SystemExit(
            f"获取 Jenkins CSRF crumb 失败：{_safe_error(result)}"
        )

    return None, None


# ============================================================
# Tool Check
# ============================================================

def cmd_toolcheck(args):
    """只检查连通性、认证和白名单 Job，不触发构建。"""

    _load_env()

    result = _req("/api/json?tree=nodeDescription,quietingDown")

    if not isinstance(result, dict) or "nodeDescription" not in result:
        print("Jenkins 连接失败：", _safe_error(result))
        return 3

    if result.get("quietingDown"):
        print("⚠️ Jenkins 正在准备关闭，不建议触发构建")
        return 3

    print("✅ Jenkins 连接正常：", result.get("nodeDescription", ""))

    me = _req("/whoAmI/api/json")

    if isinstance(me, dict) and me.get("authenticated"):
        print(f"✅ Jenkins 认证通过：{me.get('name', '?')}")
    else:
        print("❌ Jenkins 认证失败：", _safe_error(me))
        return 3

    jobs = [args.job] if args.job else sorted(WHITELIST)

    for job in jobs:
        try:
            _verify_job(job)
            print(f"✅ 白名单 Job 存在且可构建：{job}")
        except SystemExit as exc:
            print(f"❌ {exc}")
            return 3

    crumb_value, _ = _crumb()

    print(
        "CSRF crumb：",
        "已启用" if crumb_value else "未启用或无需 crumb",
    )

    print("Tool Check 完成，未触发任何构建。")
    return 0


# ============================================================
# Trigger
# ============================================================

def cmd_trigger(args):
    _load_env()
    _verify_job(args.job)

    if not args.task.isdigit():
        raise SystemExit("task 必须是数字")

    if not args.repo_url.startswith(("http://", "https://", "ssh://")):
        raise SystemExit("repo-url 必须是有效的 Git HTTP/HTTPS/SSH 地址")

    if not args.branch.strip():
        raise SystemExit("branch 不能为空")

    params = {
        PARAM_NAMES["repo_url"]: args.repo_url,
        PARAM_NAMES["branch"]: args.branch,
        PARAM_NAMES["commit"]: args.commit,
        PARAM_NAMES["task"]: str(args.task),
        PARAM_NAMES["workflow"]: args.workflow,
        PARAM_NAMES["scope"]: args.scope,
    }

    # 去掉空值参数，避免向 Jenkins 传入无意义参数
    params = {
        key: value
        for key, value in params.items()
        if value is not None
    }

    crumb_value, crumb_header = _crumb()

    headers = {}

    if crumb_value:
        headers[crumb_header] = crumb_value

    path = f"{_job_path(args.job)}/buildWithParameters"

    result = _post_form(path, params, headers)

    # 无参数 Job（如 jeebootx-ui）不接受 buildWithParameters（400 "is not parameterized"）→ 回退 /build
    if "error" in result and "not parameterized" in str(result.get("body", "")):
        print(f"ℹ️ [{args.job}] 为无参数 Job，回退 /build 触发（忽略构建参数）")
        result = _post_form(f"{_job_path(args.job)}/build", {}, headers)

    if "error" in result:
        print(
            f"❌ Jenkins 构建触发失败：HTTP {result['error']} "
            f"{result.get('body', '')[:500]}"
        )
        return 3

    location = result.get("location", "")

    if not location:
        print(
            "❌ Jenkins 未返回 Queue Location，"
            "无法确认构建是否成功入队。HTTP 状态：",
            result.get("status"),
        )
        return 3

    queue_url = urllib.parse.urljoin(_base_url() + "/", location)
    match = re.search(r"/queue/item/(\d+)/?", queue_url)

    if not match:
        print("❌ 无法从 Jenkins Location 解析 Queue ID")
        return 3

    queue_id = match.group(1)

    print(f"✅ 已触发 Jenkins Job：{args.job}")
    print(f"   Task：{args.task}")
    print(f"   Branch：{args.branch}")
    print(f"   Queue ID：{queue_id}")
    print(f"   Queue URL：{queue_url}")

    if args.wait:
        return _wait_queue(args, queue_id)

    return 0


# ============================================================
# Status
# ============================================================

def _get_build_status(job, build):
    _verify_whitelist(job)
    _verify_build_number(build)

    path = (
        f"{_job_path(job)}/{build}/api/json"
        "?tree=number,result,timestamp,duration,building,url"
    )

    return _req(path)


def _print_build_status(result):
    timestamp = result.get("timestamp") or 0

    started = datetime.datetime.fromtimestamp(
        timestamp / 1000
    ).isoformat(" ", "seconds") if timestamp else "-"

    print(
        f"Build #{result.get('number')}  "
        f"building={result.get('building')}  "
        f"result={result.get('result') or '-'}"
    )

    print(f"开始时间：{started}")
    print(f"耗时：{int(result.get('duration') or 0) // 1000}s")
    print(f"URL：{result.get('url', '')}")


def cmd_status(args):
    _load_env()

    result = _get_build_status(args.job, args.build)

    if isinstance(result, dict) and "number" in result:
        _print_build_status(result)

        if result.get("building"):
            return 1

        return _result_code(result.get("result"))

    print("状态查询失败：", _safe_error(result))
    return 3


# ============================================================
# Test Report
# ============================================================

def cmd_report(args):
    _load_env()
    _verify_whitelist(args.job)
    _verify_build_number(args.build)

    path = (
        f"{_job_path(args.job)}/{args.build}/testReport/api/json"
        "?tree=failCount,skipCount,totalCount,passCount,"
        "suites[name,cases[name,status,duration]]"
    )

    result = _req(path)

    if isinstance(result, dict) and "totalCount" in result:
        print(json.dumps(result, ensure_ascii=False, indent=2))

        fail_count = result.get("failCount", 0)

        if fail_count > 0:
            return 2

        return 0

    print(
        "测试报告不可用或查询失败：",
        _safe_error(result),
    )
    return 3


# ============================================================
# Console Logs
# ============================================================

def cmd_logs(args):
    _load_env()
    _verify_whitelist(args.job)
    _verify_build_number(args.build)

    if args.tail < 1 or args.tail > 10000:
        raise SystemExit("tail 范围必须是 1 到 10000")

    path = f"{_job_path(args.job)}/{args.build}/consoleText"

    result = _req(path, accept="text/plain")

    if isinstance(result, str):
        lines = result.splitlines()

        for line in lines[-args.tail:]:
            print(line)

        return 0

    print("日志获取失败：", _safe_error(result))
    return 3


# ============================================================
# Wait Queue / Build
# ============================================================

def _wait_queue(args, queue_id):
    """等待 Queue 获取 Build Number。"""

    for _ in range(QUEUE_MAX_ROUNDS):
        result = _req(
            f"/queue/item/{queue_id}/api/json"
            "?tree=cancelled,executable[number,url],why"
        )

        if isinstance(result, dict) and result.get("cancelled"):
            print("❌ Jenkins Queue 已取消")
            return 3

        if isinstance(result, dict) and result.get("executable"):
            build_number = result["executable"]["number"]

            print(
                f"✅ Jenkins Build 已启动："
                f"#{build_number} "
                f"{result['executable'].get('url', '')}"
            )

            return _wait_build(args, build_number)

        if isinstance(result, dict) and result.get("why"):
            print(f"排队中：{result['why'][:120]}")

        time.sleep(QUEUE_INTERVAL)

    print("❌ 等待 Jenkins Queue 超时")
    return 3


def _wait_build(args, build_number):
    """等待 Build 执行完成。"""

    for _ in range(BUILD_MAX_ROUNDS):
        result = _get_build_status(args.job, build_number)

        if isinstance(result, dict) and "number" in result:
            if not result.get("building"):
                print(
                    f"Build #{build_number} 完成："
                    f"{result.get('result')}"
                )

                _print_build_status(result)

                return _result_code(result.get("result"))

        time.sleep(BUILD_INTERVAL)

    print(f"❌ Build #{build_number} 等待超时")
    return 3


def _result_code(result):
    if result == "SUCCESS":
        return 0

    if result == "UNSTABLE":
        return 2

    if result in ("FAILURE", "ABORTED", "NOT_BUILT"):
        return 3

    return 3


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Jenkins 白名单构建调度工具"
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # Tool Check
    toolcheck = sub.add_parser(
        "toolcheck",
        help="检查 Jenkins 连通性、认证和白名单 Job"
    )
    toolcheck.add_argument(
        "--job",
        choices=sorted(WHITELIST),
        default=None,
        help="指定检查单个 Job；默认检查全部白名单 Job"
    )
    toolcheck.set_defaults(func=cmd_toolcheck)

    # Trigger
    trigger = sub.add_parser(
        "trigger",
        help="触发白名单 Jenkins Job"
    )

    trigger.add_argument(
        "--job",
        required=True,
        choices=sorted(WHITELIST)
    )
    trigger.add_argument("--task", required=True)
    trigger.add_argument("--repo-url", required=True)
    trigger.add_argument("--branch", required=True)
    trigger.add_argument("--commit", default="")
    trigger.add_argument("--scope", default="build")
    trigger.add_argument("--workflow", default="")
    trigger.add_argument("--wait", action="store_true")
    trigger.set_defaults(func=cmd_trigger)

    # Status
    status = sub.add_parser("status", help="查询构建状态")
    status.add_argument("--job", required=True, choices=sorted(WHITELIST))
    status.add_argument("--build", required=True)
    status.set_defaults(func=cmd_status)

    # Report
    report = sub.add_parser("report", help="查询测试报告")
    report.add_argument("--job", required=True, choices=sorted(WHITELIST))
    report.add_argument("--build", required=True)
    report.set_defaults(func=cmd_report)

    # Logs
    logs = sub.add_parser("logs", help="查询控制台日志")
    logs.add_argument("--job", required=True, choices=sorted(WHITELIST))
    logs.add_argument("--build", required=True)
    logs.add_argument("--tail", type=int, default=100)
    logs.set_defaults(func=cmd_logs)

    args = parser.parse_args()

    try:
        sys.exit(args.func(args))
    except KeyboardInterrupt:
        print("\n操作已中断")
        sys.exit(3)
    except SystemExit:
        raise
    except Exception as exc:
        # 不输出请求头、认证信息或环境变量
        print(f"脚本执行异常：{type(exc).__name__}: {exc}")
        sys.exit(3)


if __name__ == "__main__":
    main()
