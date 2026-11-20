# 青禾 · 磨坊出粉率分布复核

为青禾制粉厂的 3 条生产线提供原粮批次、检验记录、分布诊断和复核签核，质量分析员每天把原粮检验变成可追溯的交班结论。

## 真实业务场景

青禾质量组原来把供应商批次写进 `原粮到货-1115.xlsx`，检验员录入不同工作簿，分析员手算四分位数，负责人在群里确认。问题是样本与批次容易错位、计算口径随人员变化、签核意见无法回到当时的数据。本项目承接原粮入厂检验，输出带冻结样本和 SHA-256 的复核 CSV，供产线负责人安排复测。

- 批次台账：供应商、产线、吨数、日期、样本数，唯一业务编号。
- 检验录入：出粉率、水分、检验员，范围校验和重复编号阻断。
- 分布诊断：按产线冻结快照，Redis 排队由独立 Python worker 计算，显示完整样本直方图、分位数、IQR 异常点和分组均值。
- 复核报告：负责人签核意见，分析员与观察员可下载含原始样本的 CSV。
- 外发复核：按到货月冻结各批出粉率均值，申请公布所选批次均值的加总值；与本月已发布等式联立做差分攻击防护，可解出任一单批均值即拒发并内部留痕涉及批次。
- JWT 三角色、写操作审计、每分钟请求限流、可恢复的错误提示。

## 账号与权限

密码均为 `Demo123!`。

| 角色 | 账号 | 权限 | 典型动作 |
|---|---|---|---|
| admin | admin@demo.local | 全部业务读写与签核、审计读取 | 核对异常点并签核 |
| analyst | analyst@demo.local | 录入、提交计算、读取和导出；不可签核 | 新增样本并发起复核 |
| viewer | viewer@demo.local | 只读与导出；后端拒绝业务写入与任务提交 | 下载交班报告 |

## 快速启动

```sh
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

访问 [前端](http://localhost:18200)、[后端 API 文档](http://localhost:19200/docs)。PostgreSQL 映射端口 17700；Redis 不暴露宿主端口。网络固定为 `10.253.101.0/24`，可通过 `NETWORK_SUBNET` 修改以避开本机大量 Compose 栈的默认网段池限制。

```sh
docker compose down -v --remove-orphans
```

此命令会清除此项目演示数据。普通重启使用 `docker compose stop` / `docker compose start` 保留命名卷。

## 技术与环境变量

| 部分 | 技术 |
|---|---|
| 前端 | 原生 ES modules / HTML / CSS，Nginx 1.27 |
| API | Python 3.11、FastAPI 0.115.6、SQLAlchemy 2.0.36 |
| 数据库 | PostgreSQL 16 |
| 队列 | Redis 7、独立 Python worker 与心跳健康检查 |
| 认证 | PyJWT 2.10.1、PBKDF2-SHA256 密码哈希 |

`.env.example` 包含项目名、三个端口、数据库密码、JWT 密钥、演示 seed 开关、网络网段。演示密码和 JWT 密钥仅用于本地可复现运行，部署时自行替换。命名卷分别保存数据库、Redis AOF 和 worker 结果文件。恰好五个服务均配置健康检查，worker 等待 API seed 完成。

## 数据与计算口径

固定随机种子 `3101` 生成 40 批原粮、每批 15 条检验，共 600 条样本。首批是 `QH-1115-A`，检验员林洁。`seed_demo` 按批次和样本自然键检查后插入；重复执行不增加行数，也不覆盖已有用户数据。启动 `SEED_DEMO=true` 自动 seed，失败记录日志不阻塞进程。

出粉率范围 `(0,100]`，水分 `[0,30]`，NaN 与 Infinity 被拒绝。数据均为模拟数值，没有外部生产数据依赖。复核按提交时快照计算，后续录入不会改变既有报告。

- 至少 5 个有效样本，否则返回 422，不提交任务。
- 将出粉率排序，对 `p=0.25/0.5/0.75` 使用位置 `(n−1)p` 的相邻值线性插值得到 Q1、中位数、Q3。
- `IQR=Q3−Q1`，异常点为严格小于 `Q1−1.5×IQR` 或严格大于 `Q3+1.5×IQR` 的记录。边界上的点保留为非异常。常量样本 IQR=0，等于常量的样本不标异常。
- 标准差使用样本标准差 `n−1`。直方图区间固定为 0–100、步长 5 个百分点，最后一桶包含 100；展示区域自动覆盖全部非空桶并留一个相邻空桶，完整 0–100 桶计数保存在 API 结果中。
- 分组按原粮产线计算 n、均值、最小、最大。异常点不从总体统计中移除。
- 结果带样本快照 SHA-256，同一冻结输入可复现。统计异常只是核对线索，不自动判废。

后台 worker 从 Redis 消费复核 id，更新 queued→running→completed/failed，写结果至共享 artifacts 卷。重启时会扫描未完成任务并重新排队。负责人仅能签核 completed 状态，签核后不可重复签核。CSV 导出包含状态、口径值、签核意见和所有冻结样本。

## 外发复核与差分攻击防护

单份出粉率数据只给汇总、看不出单批，但同一到货月的多份加总联立后可能反推单批均值。外发复核按以下口径处理：

- **冻结口径**：某到货月首次受理申请时，为该月每个有检验记录的批次冻结出粉率均值（`FrozenBatchMean`，按批次唯一，含样本数与快照 SHA-256）。冻结后新增检验不改写既有均值；申请公布的是所选批次冻结均值的加总值。
- **可解性判单**：把本申请的求和方程与本月所有**已发布**方程组成线性方程组。变量 $x_j$ 可被唯一解出，当且仅当单位向量 $e_j$ 落在系数矩阵的行空间（等价于追加 $e_j$ 不改变秩）。判定用 `fractions.Fraction` 精确高斯消元（`src/utils/linear.py`），不使用浮点秩，避免奇异系统误判。
- **拒发与留痕**：只要联立后能解出任一单批均值就整单拒发（仅含一个批次的申请必然拒发），涉及的批号与原因只对 admin 返回，非 admin 仅看到统一拒发提示，发布前任何数值都不对外暴露。
- **并发与发布账**：判单在独立 worker 异步执行，状态 pending→judging→rejected/published/failed。所有判单经 Redis 全局发布锁串行化，落账用 `ledger_key` 唯一约束（`disclosure:{月}:app-{申请id}`）+ Redis 幂等集合双保险。落账失败时外部拿不到数值；重试沿原申请行、原账键进行，绝不会多发一份。worker 重启会把 pending/judging 的申请重新入队，重复投递由幂等账吸收。
- **页面与导出**：「外发复核」页可勾选同到货月批次提交申请，并查看待判、判单中、拒发、已发布、落账失败状态；失败可沿原单重试。外发导出 CSV 仅含已发布申请的加总值与所含批号，拒发/待判/失败单及内部原因均不出现。
- 到货月按 `received_date` 的 `YYYY-MM` 划分，不同月份的方程互不联立。

## 本地无依赖测试

仓库未引入新的第三方依赖。在没有 Docker/数据库的环境下，可直接用标准库跑逻辑与服务测试（`local-tests/` 自带最小 in-memory stub，运行时用 `-I` 隔离）：

```sh
python3 -I local-tests/test_disclosure_logic.py        # 差分攻击/冻结/幂等场景
python3 -I local-tests/test_disclosure_service.py      # 真实服务模块端到端
python3 -I local-tests/test_disclosure_concurrency.py  # 发布锁、重试与不重复落账
```

## 一天的工作剧本

1. 08:50 观察员登录查看 `QH-1115-A`，核对 15 个已有样本。
2. 09:00 分析员登记 `QH-1115-NEW`，供应商丰垦粮业，到货 28 吨。
3. 09:10 检验员林洁新增 `QH-1115-A-S16`，出粉率 73.20%、水分 12.80%。
4. 09:20 录入重复编号应报冲突；出粉率 101% 被范围校验拒绝。
5. 09:30 在分布诊断中选择一线并建立「11月15日产线出粉率复核」。
6. 09:40 独立 worker 完成计算，分析员核对 IQR 边界和异常样本。
7. 10:00 负责人切换 admin，记录复测安排并签核。
8. 10:20 观察员下载 `mill-yield-review-<id>.csv`，交给产线班长。

## 目录与本地开发

`backend/src` 按 routes/controllers/services/models/schemas/middlewares/utils/constants/config 分职责；`backend/scripts` 是幂等 seed；`backend/migrations` 记录初始 schema 约定，实际表结构由 SQLAlchemy `create_all` 应用。`frontend/src` 按 api/stores/types/components/common/hooks/pages/router/utils/constants 分模块。

本地 Python 开发：安装 `backend/requirements.txt`，配置 `DATABASE_URL` / `REDIS_URL` / `JWT_SECRET`，在 backend 目录执行 `uvicorn src.main:app --reload` 与 `python -m src.worker`。静态前端通过 Nginx `/api/` 代理后端无前缀路由，不需要 Node 构建。

共享枚举：`backend/src/constants/enums.py` 与 `frontend/src/constants/enums.js` 中分别定义角色 Role、复核状态 ReviewStatus、产线 LINES；UI 角色标签、后端鉴权及状态迁移遵守这些值。

## 范围与已知差异

小型项目仅支持逐条录入，不提供 Excel 导入和外部检验仪器同步。原始检验记录采用追加留痕模式，没有删除/覆盖接口；错误记录须重新录入并在复核意见说明。签核是本地数据库留痕，不是电子签章。图形自动覆盖全部实际样本区间，完整 0–100 桶和所有样本在 API / CSV 中保留。演示时区在报告中显式标记 UTC。前端 Google Fonts 离线时回退宋体。

测试脚本、1440×900 页面截图与实测证据在源码外的 `test-artifacts/gb-3101/`。License：MIT。
