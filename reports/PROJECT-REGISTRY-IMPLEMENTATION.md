# 项目注册与自动发现机制 — 实施报告（P07）

> 2026-11-17 · 任务：Project Registry & Discovery · 基线 0d6e8a7（task-workflow-31 的 WORKFLOW_HOME 交付）

## 一、实现能力

| 能力 | 实现 |
|---|---|
| 项目注册（12 步引导） | `/workflow-register-project` Skill + `project_register.py`（plan/apply 两段式 + 指纹确认 + dry-run） |
| 任务→项目自动发现 | `zt.py project --task`（只读归属提取）→ `project_resolver.match`（可靠性分级裁决） |
| 统一项目解析（单点映射） | `project_resolver.py`：注册表 / 匹配分级 / 用户路径 / 项目上下文 |
| 仓库识别与校验 | `repo_check.py`：技术栈识别（6 类）+ Git 8 项只读校验 + BLOCKED/mismatch 语义 |
| 用户级路径映射 | `config/users/{id}.yaml → project_paths`（优先于 `${ENV}` 路径；只增不覆盖） |
| 禅道项目列表（注册第 1 步） | `zt.py projects`（只读 GET /projects，实测 16 项） |
| 任意目录启动衔接 | 全部经 `_home.resolve_workflow_home` 定位工作流根（复用 31 交付） |

## 二、文件变更清单

**新增**：
| 文件 | 职责 |
|---|---|
| `scripts/project_resolver.py` | 统一项目解析（匹配分级/上下文/用户路径；复用 `_args.match_project` 谓词） |
| `scripts/project_register.py` | 注册 CLI（plan/apply、查重、校验、原子写、指纹确认） |
| `scripts/repo_check.py` | 技术栈识别 + Git 只读校验 |
| `.claude/skills/workflow-register-project/SKILL.md` | 新 Skill（12 步引导 + 故障排查） |
| `docs/project-registry.md` | 使用文档（注册/使用/故障排查/配置规范/安全） |
| `tests/test_project_resolver.py` | 解析测试 15 项 |
| `tests/test_repo_check.py` | 仓库测试 18 项 |
| `tests/test_project_register.py` | 注册测试 13 项 |
| `tests/test_zt_project.py` | zt.py 新子命令 Mock 测试 4 项 |
| `tests/test_registry_integration.py` | 集成测试 7 项 |
| `reports/PROJECT-REGISTRY-ANALYSIS.md` | P01 现状盘点 |

**修改**（增量于 0d6e8a7，未覆盖并行会话内容）：
| 文件 | 变更 |
|---|---|
| `scripts/zt.py` | 新增只读子命令 `projects` / `project --task`（不写禅道） |
| `.claude/skills/zentao-dev-workflow/SKILL.md` | 参数解析/启动前必检/执行流程接入 resolver（保留 31 的第 0 步与 _args 解析） |
| `config/projects/project.example.yaml` | 新增 `zentao: {project_id, product_ids}` 结构化归属 + remote_url/路径规范注释 |
| `config/users/user.example.yaml` | 新增 `project_paths` 模板（注释态） |

**不动**：`_config.py`（`resolve_repo` 无代码消费方，路径统一经 resolver）、`execution/` 历史、
`agent-manager/`、HITL、7 个 Subagents、DAG 语义、jenkins_run。

## 三、新增配置结构

```yaml
# config/projects/{key}.yaml（可进 Git，无个人路径/凭据）
project:
  zentao:                  # 结构化归属（自动发现锚点）
    project_id: 125        # 精确匹配
    product_ids: [7]       # 辅助匹配
  repositories:
    - key: backend         # ← 现有 key 字段（任务建议的 name 同义）
      remote_url: "..."    # 新增可选（Git 核验）
# 兼容：zentao_project（旧列表字段）与 repositories[].path: "${ENV}" 均保留

# config/users/{id}.yaml（不进 Git）
project_paths:
  smart-sanitation:
    backend: D:/WorkSpace/ss/backend
```

字段映射（任务建议 → 现有规范）：`name→key`、`type→technology`、`required→enabled`（语义等价不引入新词）、
`agents.enabled[]→agents{} map`（保留，`enabled_agents()` 依赖）、`workflow.build.adapter→integrations.ci`（已有）。

## 四、新增 CLI

```bash
# 注册（两段式，指纹确认）
python -I scripts/project_register.py plan --project-key K --name N \
  --zentao-project-id 125 [--product-ids 7,8] \
  --repo backend=D:/path:backend[:remote] ... --user <uid> [--out plan.json]
python -I scripts/project_register.py apply --plan plan.json --confirm <fingerprint> [--dry-run]

# 解析（统一入口）
python -I scripts/project_resolver.py match --task-json <file|-> [--user <uid>] [--json]
python -I scripts/project_resolver.py context --project <key> --user <uid> [--json]

# 禅道只读
python -I scripts/zt.py projects                 # 可访问项目列表
python -I scripts/zt.py project --task 5001      # 任务→项目归属（仅本人任务）
```

退出码约定：0 成功 / 2 用法 / 3 配置或校验失败 / 4 须人工确认（ambiguous/needs_confirm）。

## 五、Skill 使用方式

- `/workflow-register-project`：12 步引导注册（禅道项目选择→project_key→多仓库路径→计划与校验展示→**用户确认**→原子写→注册报告）。
- `/zentao-dev-workflow #5001`：任务号自动发现（唯一可靠命中→直接跑；名称命中→确认；多候选→询问；无命中→提示注册，不创建 execution）。
- `/zentao-dev-workflow <key> 5001`：显式指定，进入同一解析链。

## 六、ZenTao 自动识别原理

1. `zt.py project --task`：`task_detail`（whoami 归属校验，仅本人任务）→ 提取
   `project`（禅道项目 ID）/ `projectName`（/projects 列表回查，仅辅助）/ `product_ids`（尽力提取）。
2. `project_resolver.match`：对每个启用项目分级——
   - `exact`：任务 project ID ∈ 配置 `zentao.project_id`/`zentao_project`（ID 对等）→ 可靠
   - `product`：产品 ID 交集 → 可靠（辅助证据）
   - `text`：仅 key/name 文本命中（**复用 `_args.match_project` 谓词**）→ 不可靠，须用户确认
3. 裁决：唯一 exact/product → resolved；仅唯一 text → needs_confirm；多候选 → ambiguous；
   无 → unregistered（提示注册入口）；命中但禁用 → disabled。**任何不确定均不猜测。**

## 七、多仓库路径映射

- 项目配置声明仓库清单（key/role/technology/remote_url）；个人绝对路径只写 `config/users/{id}.yaml → project_paths`。
- 解析优先级：`project_paths[user][project][repo]` > `repositories[].path`（`${ENV}` 展开，旧项目零改动）。
- 同一项目不同用户不同路径；一项目多仓库（jeebootx 真实配置 4 仓库验证兼容）。

## 八、自动化测试结果（2026-11-17）

| 套件 | 数量 | 结果 |
|---|---|---|
| tests/（含 31 的 WORKFLOW_HOME 43 项 + 本任务 58 项） | 101 | ✅ PASS |
| agent-manager/human_decision/tests（HITL 回归） | 56 | ✅ PASS |
| agent-manager/tests（Agent Manager 回归） | 20 | ✅ PASS |
| **合计** | **177** | **PASS / 0 FAIL** |

覆盖（本任务 58 项）：注册正常/重复 key/重复禅道 ID/多对一拒绝/dry-run 零写入/指纹确认/拒绝覆盖用户配置/坏输入；
解析唯一/无/多匹配/project_id/product_id/禁用/仅名称须确认/用户路径优先级/多用户隔离/当前用户解析；
仓库 8 项校验（缺路径/非目录/非 Git/根不一致/remote 不一致/脏工作区/角色/多仓库/Windows 路径形态）/技术栈 6 类；
zt.py Mock（列表/归属/名称缺失不阻断/非本人拒绝）；集成（任意目录/未识别零创建/多项目隔离/全链路注册→发现→校验）。
外部禅道接口测试全部 Mock；真实禅道仅做**只读**冒烟（projects 16 项、jeebootx/demo-react 上下文）。

## 九、原有工作流兼容性

- jeebootx / demo-react：**零改动**通过真实上下文构建与 `validate`（验收 9/10 证据）
- 旧式 `${ENV}` 路径机制、`zentao_project` 旧字段、`agents{}` map、`integrations` 均保留
- 执行状态目录 `execution/{project_key}/{task_id}/` 语义不变；DAG/HITL/回写边界不变
- `_args.match_project`（31）为匹配谓词单点，本任务仅包装分级未改其逻辑

## 十、安全验证结果

- 禅道全程只读（projects/project/detail）；未执行任何写操作、未建项目、未动任务状态
- 注册仅写 `config/projects/{key}.yaml`（新建）与 `config/users/{id}.yaml`（仅新增 project_paths 键）；
  已有配置/映射一律拒绝覆盖（测试证实）
- 写入原子化（临时文件→os.replace），失败不留半成品；指纹不一致拒绝执行
- 仓库校验只读（rev-parse/remote get-url/status --porcelain）；无 clone/checkout/改 remote/push
- 凭据扫描：新增/修改文件无 token/密码/连接串；`.gitignore` 已含 `.zentao_token.json` 防护
- 未识别项目不创建 execution（测试证实）；未动 `execution/` 历史与并行会话文件

## 十一、Git Commit

见验收报告（`reports/PROJECT-REGISTRY-ACCEPTANCE.md`）末尾 Commit ID（本报告定稿后提交）。

## 十二、尚未解决的问题

1. **真实项目注册演示未执行**：等用户指定接入项目（此前 Bug #3264 等候选待选）后执行一次真实注册即得实证；机制本身已由 tmp 全链路测试覆盖。
2. **product_id 辅助匹配的真实数据**：现有禅道任务详情未暴露稳定 product 字段（尽力提取），多产品项目的真实辅助命中案例待真实任务积累。
3. **`python -m pytest agent-manager` 与根 tests/ 合跑收集冲突**（既有问题，31 亦记录）：
   `human_decision/notifier.py` 遮蔽 `agent-manager/notifier.py` 同名导入——影响合跑收集，不影响分套件运行（177 全绿）。建议后续统一命名或包化。
4. **SKILL.md 的执行流程第 0 步与 resolver 串联**已文档化；工作流级 E2E（真实任务 #5001 全流程）属真实任务阶段（用户已定调"后续跑真实任务测试整个流程"）。
5. `resolve_repo`（_config）未并入 project_paths 优先级——无代码消费方，路径统一经 `project_resolver.repo_paths_for`；若后续外部脚本直用 resolve_repo 需注意。
