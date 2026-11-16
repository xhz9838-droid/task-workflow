# Jenkins 操作脚本。只允许触发白名单 Job（ai-test-runner），禁止触发现有部署 Job。
# 凭据从项目根 .env（gitignored）读取，不写入日志。
#
# 用法：
#   python -I scripts/jenkins_run.py trigger --job ai-test-runner --task 3413 --repo-url ... --branch ... --scope unit [--wait]
#   python -I scripts/jenkins_run.py status  --job ai-test-runner --build 1
#   python -I scripts/jenkins_run.py report --job ai-test-runner --build 1
#   python -I scripts/jenkins_run.py logs   --job ai-test-runner --build 1 --tail 100
#   python -I scripts/jenkins_run.py toolcheck  （—dry-run 先验证连通性与白名单 Job 存在）
import argparse
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHITELIST = {"ai-test-runner"}

def _load_env():
    envfile = os.path.join(ROOT, ".env")
    if os.path.exists(envfile):
        with open(envfile, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    for k in ("JENKINS_URL", "JENKINS_USER", "JENKINS_TOKEN"):
        if not os.environ.get(k):
            raise SystemExit(f"缺少环境变量 {k}（请在 {envfile} 中设置）")


def _url(path):
    base = os.environ["JENKINS_URL"].rstrip("/")
    return f"{base}{path}"


def _auth():
    from base64 import b64encode
    u = os.environ["JENKINS_USER"]
    t = os.environ["JENKINS_TOKEN"]
    return "Basic " + b64encode(f"{u}:{t}".encode()).decode()


def _req(path, method="GET", body=None, accept="application/json", timeout=30):
    headers = {"Authorization": _auth(), "Accept": accept}
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body).encode()
    req = urllib.request.Request(_url(path), data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        ct = resp.headers.get("Content-Type", "")
        raw = resp.read()
        if "json" in ct:
            return json.loads(raw)
        return raw.decode(errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return {"error": e.code, "body": body[:2000]}
    except urllib.error.URLError as e:
        return {"error": -1, "body": str(e.reason)}


def _crumb():
    """Jenkins CSRF crumb（若启用）。"""
    r = _req("/crumbIssuer/api/json")
    if isinstance(r, dict) and "crumb" in r:
        return r["crumb"], r.get("crumbRequestField", "Jenkins-Crumb")
    return None, None


def _verify_job(job):
    if job not in WHITELIST:
        raise SystemExit(f"白名单外 Job（{job}）禁止触发。仅允许: {', '.join(sorted(WHITELIST))}")
    r = _req(f"/job/{job}/api/json?tree=name")
    if isinstance(r, dict) and r.get("name") == job:
        return True
    raise SystemExit(f"Jenkins 中未找到 Job: {job}（HTTP {r.get('error','?')}）")


def cmd_toolcheck(args):
    """验证 Jenkins 可达性、认证与白名单 Job 存在性（不触发构建）。"""
    _load_env()
    r = _req("/api/json?tree=nodeDescription,quietingDown")
    if isinstance(r, dict) and "nodeDescription" in r:
        print("✅ Jenkins 可达：", r.get("nodeDescription", ""))
    else:
        print("❌ Jenkins /api/json 返回异常：", r)
        return 3
    me = _req("/whoAmI/api/json")
    if isinstance(me, dict) and me.get("authenticated"):
        print(f"✅ 认证通过（{me.get('name','?')})）")
    else:
        print("❌ 认证失败：", me)
        return 3
    # 检查白名单 Job
    try:
        _verify_job(args.job)
        print(f"✅ 白名单 Job {args.job} 存在")
    except SystemExit as e:
        print(f"❌ {e}")
        return 3
    # 尝试取 crumb（仅打印是否启用，不保存）
    c, _ = _crumb()
    print(f"   CSRF crumb: {'已启用' if c else '未启用'}")
    return 0


def cmd_trigger(args):
    _load_env(); _verify_job(args.job)
    params = {"REPO_URL": args.repo_url, "GIT_BRANCH": args.branch,
              "GIT_COMMIT": args.commit or "", "ZENTAO_TASK_ID": str(args.task),
              "WORKFLOW_ID": args.workflow or "", "TEST_SCOPE": args.scope}
    # 造带参数的 build URL
    qs = "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in params.items())
    path = f"/job/{args.job}/buildWithParameters?{qs}"
    crumb_val, crumb_header = _crumb()
    headers = {"Authorization": _auth()}
    if crumb_val:
        headers[crumb_header] = crumb_val
    import urllib.parse
    req = urllib.request.Request(_url(path), data=b"", headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        # 302 → queue URL 在 Location
        loc = resp.headers.get("Location", "")
        qid_match = re.search(r"/queue/item/(\d+)", loc)
        qid = qid_match.group(1) if qid_match else "?"
        print(f"已触发 {args.job}（queue item: {qid}）")
        if args.wait:
            return _wait_queue(args, qid)
        return 0
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:1000]
        print(f"触发失败 HTTP {e.code}：{body}")
        return 3


def cmd_status(args):
    _load_env()
    path = f"/job/{args.job}/{args.build}/api/json?tree=number,result,timestamp,duration,building,url"
    r = _req(path)
    if isinstance(r, dict):
        b = r.get("building", True)
        ts = datetime.datetime.fromtimestamp((r.get("timestamp") or 0) / 1000)
        print(f"#{r.get('number')}  building={b}  result={r.get('result','-')}  "
              f"started={ts.isoformat(' ','seconds')}  url={r.get('url','')}")
        return 0 if not b else 1
    print("状态查询失败：", r)
    return 3


def cmd_report(args):
    _load_env()
    tr = _req(f"/job/{args.job}/{args.build}/testReport/api/json?tree=failCount,skipCount,totalCount,passCount,suites[name,cases[name,status,duration]]")
    if isinstance(tr, dict):
        print(json.dumps(tr, ensure_ascii=False, indent=1))
        return 0
    print("测试报告查询失败：", tr)
    return 3


def cmd_logs(args):
    _load_env()
    url = f"/job/{args.job}/{args.build}/consoleText"
    raw = _req(url, accept="text/plain")
    if isinstance(raw, str):
        lines = raw.splitlines()
        tail = int(args.tail or 100)
        for line in lines[-tail:]:
            print(line)
        return 0
    print("日志获取失败：", raw)
    return 3


def _wait_queue(args, qid):
    """轮询 queue 直到获取 build number，然后轮询 build 直至完成。"""
    for _ in range(60):
        r = _req(f"/queue/item/{qid}/api/json?tree=executable[number,url],why")
        if isinstance(r, dict) and r.get("executable"):
            bn = r["executable"]["number"]
            print(f"Build #{bn} started: {r['executable'].get('url','')}")
            return _wait_build(args, bn)
        if isinstance(r, dict) and r.get("why"):
            print(f"排队中：{r['why'][:120]}")
        time.sleep(3)
    print("超时：queue 60 轮未启动")
    return 3


def _wait_build(args, bn):
    for i in range(120):
        r = _req(f"/job/{args.job}/{bn}/api/json?tree=number,result,timestamp,duration,building,url")
        if isinstance(r, dict) and not r.get("building"):
            print(f"#{bn} 完成：{r.get('result')} 耗时 {int(r.get('duration',0)/1000)}s")
            return 0 if r.get("result") == "SUCCESS" else (2 if r.get("result") == "UNSTABLE" else 3)
        time.sleep(5)
    print("超时：build 120 轮未完成")
    return 3


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    tc = sub.add_parser("toolcheck")
    tc.add_argument("--job", default="ai-test-runner")
    tc.set_defaults(func=cmd_toolcheck)
    tr = sub.add_parser("trigger")
    tr.add_argument("--job", default="ai-test-runner")
    tr.add_argument("--task", required=True); tr.add_argument("--repo-url", required=True)
    tr.add_argument("--branch", default="dev"); tr.add_argument("--commit", default="")
    tr.add_argument("--scope", default="unit"); tr.add_argument("--workflow", default="")
    tr.add_argument("--wait", action="store_true")
    tr.set_defaults(func=cmd_trigger)
    st = sub.add_parser("status"); st.add_argument("--job", default="ai-test-runner"); st.add_argument("--build", required=True); st.set_defaults(func=cmd_status)
    rp = sub.add_parser("report"); rp.add_argument("--job", default="ai-test-runner"); rp.add_argument("--build", required=True); rp.set_defaults(func=cmd_report)
    lg = sub.add_parser("logs"); lg.add_argument("--job", default="ai-test-runner"); lg.add_argument("--build", required=True); lg.add_argument("--tail", default=100); lg.set_defaults(func=cmd_logs)
    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()