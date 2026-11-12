# 数据洞察分析工作台

面向多源数据接入、交互式查询分析、可视化看板搭建、分析报告生成与数据服务编排的数据洞察分析工作台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 交互查询 | `query` | 查询语句 | 语句编号、查询表达式、目标数据集 |
| 可视化图表 | `chart` | 图表配置 | 图表编号、图表名称、图表类型 |
| 数据源接入 | `source` | 接入配置 | 配置编号、连接类型、接入地址 |
| 聚合计算 | `aggregate` | 聚合方案 | 方案编号、聚合函数、目标字段 |
| 数据筛选 | `filter` | 筛选规则 | 规则编号、目标数据集、筛选字段 |
| 报告生成 | `reportgen` | 报告模板 | 模板编号、模板名称、包含图表 |
| 异常检测 | `anomaly` | 检测规则 | 规则编号、监控指标、基线均值 |
| 多维下钻 | `drill` | 下钻路径 | 路径编号、起点维度、下钻层数 |
| 对比分析 | `compare` | 对比方案 | 方案编号、基准数据集、对照数据集 |
| 分析流水线 | `pipeline` | 流水线节点 | 节点编号、节点类型、输入源 |
| 数据集管理 | `datastore` | 数据集定义 | 数据集编号、数据集名称、来源表名 |
| 趋势预测 | `forecast` | 预测模型 | 模型编号、模型类型、训练数据集 |
| 数据分片 | `segment` | 分片规则 | 规则编号、目标数据集、分片字段 |
| 调度管理 | `scheduler` | 调度配置 | 配置编号、关联任务、调度表达式 |
| 通知分发 | `notify` | 通知规则 | 规则编号、触发条件、通知渠道 |
| 查询缓存 | `cache` | 缓存策略 | 策略编号、目标查询、缓存键规则 |
| 数据标签 | `tag` | 标签定义 | 标签编号、标签名称、计算表达式 |
| 数据分享 | `share` | 分享链接 | 链接编号、目标数据集、访问密码 |

## 聚合计算：分组口径试算器

聚合计算页是一个可比较试算器，流程与口径如下。

### 绑定与配置

- 先绑定数据集管理里的**字段身份**（`field_id`，如 `DATA-0001.amount`）。
  字段显示名只是快照，重命名不会让已有方案错绑。
  字段目录：`GET /api/datastore/catalog/fields`。
- 改为**求和、计数、均值**各自配置空值策略（`include` 参与 / `exclude` 排除）、
  输出精度（0–6 位）与时间窗口（按月 / 自定义区间 / 不设窗口）。
- 分组键取分组字段原值，空值显示为 `(空)`；三种指标可以各自绑定不同字段与窗口。

### 计算口径（实现方约定）

- 空值策略按指标生效：参与 = 求和分子按 0（总额不变）、均值分母仍包含该行
  （均值被拉低）、计数计 1 条；排除 = 该行不进分子与分母。
  每个空值行在贡献分解里都带一句“为什么参与/被排除”的说明，可追溯。
- **舍入位置在汇总之后、只舍入一次**（`ROUND_HALF_UP`）。逐行舍入再加总的
  数字只作为对照展示，不参与结论。求和用精度足够的 `Decimal` 精确累加，
  因此输入顺序变化不会改变金额舍入结论。
- **窗口左闭右开**：相邻窗口共用边界时，边界采样归起点更大的窗口。
  窗口重叠按声明顺序取第一个命中窗口，一条采样只归入一组；
  窗口外与时间缺失的采样进入“未归集清单”，不会被静默塞进任何一组。

### 算例

`GET /api/aggregate/{id}/cases` 按当前方案字段身份返回三份可比较算例：

| 算例 | 观察点 |
| --- | --- |
| 全空组 | 参与策略下计 0/计入 1 条；排除策略下求和与均值无有效贡献 |
| 正负抵消 | +100 与 -100 抵消为 0，叠加两个 0.005 看汇总舍入与逐行舍入的差异 |
| 跨月边界 | 1 月最后一秒归 1 月、2 月第一秒归 2 月、3 月采样进入未归集 |

### 发布与版本

- 发布（`POST /api/aggregate/{id}/publish`）会封存当时的字段身份、字段名快照、
  空值策略、精度、窗口条件、样本与完整试算证据；发布版不可再改。
- **重复确认同版不再开一轮生效**：口径与样本摘要一致时直接返回已有发布版。
- **规则冲突以发布版为准**：草稿修改只落在草稿上，不会渗入任何发布版，
  也不会进入跨模块目录 `GET /api/aggregate/published`（只列发布版）。

### 跨模块消费

- 图表绑定发布版：`POST /api/chart/aggregate/bind`（不接受草稿）。
- 图表侧证据：`GET /api/chart/aggregate/evidence?chart_id=...`，返回绑定版本的
  口径、窗口、舍入口径、分组贡献与未归集清单。
- 切换新版需显式确认：`POST /api/chart/aggregate/upgrade`，上一版证据转为
  “历史证据”继续保留；同一版重复确认不会再开一轮生效。
- 聚合页同样内置了“发布版 + 图表绑定”面板，可直接在页面完成上述操作。

### 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/aggregate` | 方案列表（含草稿修订与当前生效版） |
| GET | `/api/aggregate/{id}` | 方案明细：草稿口径、样本、版本摘要 |
| PUT | `/api/aggregate/{id}/draft` | 保存草稿并立即试算 |
| POST | `/api/aggregate/{id}/trial` | 临时试算（不落库、不产生版本） |
| GET | `/api/aggregate/{id}/cases` | 三份可比较算例及试算 |
| POST | `/api/aggregate/{id}/publish` | 封存发布版（幂等） |
| GET | `/api/aggregate/{id}/versions` | 版本摘要 |
| GET | `/api/aggregate/{id}/versions/{v}` | 发布版封存证据 |
| GET | `/api/aggregate/published` | 跨模块已发布口径目录 |
| POST | `/api/aggregate/{id}/actions` | 提交校验 / 启用 / 停用（发布动作走封存） |
| GET/POST | `/api/chart/aggregate/evidence` `bind` `upgrade` `unbind` | 图表侧消费发布版 |

接口级自检：先启动后端，再运行
`backend/.venv/bin/python backend/tests/aggregate_check.py`（脚本用 HTTP 调真实服务）。

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据分析与数据应用
