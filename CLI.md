# astock_system 命令行说明

在不打开 Streamlit 页面的情况下，可用项目根目录下的 **`cli.py`** 执行与界面相同的下载与同步逻辑。

## 前置条件

1. **工作目录**：在 `astock_system` 目录下执行（或把该目录加入 `PYTHONPATH`），以便正确加载 `config.py` 与 `core`。
2. **数据库**：默认与 `config.py` 中 `POSTGRESQL_CONFIG` 一致；也可用环境变量或 `--db-*` 覆盖（见下文）。
3. **依赖**：与运行 `streamlit run app.py` 相同的环境（已安装 `adata`、`psycopg2` 等）。

```bash
cd /home/lom/trade/adata/astock_system
```

## 查看帮助

```bash
python cli.py --help
python cli.py incremental --help
python cli.py financial --help
python cli.py index --help
python cli.py concept --help
```

## 子命令一览

| 子命令 | 作用 | 对应 Streamlit 页面 |
|--------|------|---------------------|
| `incremental` | 按每只股票最后交易日增量拉取日 K | 增量更新 |
| `financial` | 批量下载财务核心指标 | 财务数据 |
| `index` | 下载默认常用指数日线（可追加指数） | 指数行情 |
| `concept` | 同步同花顺概念板块，可选成分股 | 概念板块 |

进度日志输出在 **stderr**；每步结束会在 **stdout** 打印结果字典（`updated` / `success` / `concepts` 等）。

---

## 1. 增量更新（日 K）

更新数据库里**已有日线记录**的股票，从各自最后交易日续拉到今日。

```bash
# 全部「已下载」股票
python cli.py incremental

# 仅指定代码（逗号或换行分隔）
python cli.py incremental --codes "000001,600519,300750"

# 从文件读取代码列表
python cli.py incremental --codes-file ./my_codes.txt
```

---

## 2. 财务数据

```bash
# 全市场（股票来自 stock_basic，耗时长）
python cli.py financial --scope all

# 指定股票
python cli.py financial --scope codes --codes "000001,600000,000858"

# 某一行业（需库中已有行业信息）
python cli.py financial --scope industry --industry "银行"

# 自定义请求间隔（秒），默认见 config.DOWNLOAD_DELAY
python cli.py financial --scope codes --codes "000001" --delay 1.0

# 强制单线程（与旧版一致）
python cli.py financial --scope codes --codes "000001" --workers 1
```

说明：财务接口每次仍拉取该股**全部报告期**，数据库按 `(stock_code, report_date)` **UPSERT**；并非只请求「新报告期」。

---

## 3. 指数行情

默认包含：`000001` 上证、`399001` 深证、`399006` 创业板、`000300` 沪深300、`000905` 中证500、`000852` 中证1000、`000688` 科创50。

默认行为：**增量**——若库中已有该指数，则从最后交易日的下一天续拉到今日；入库按交易日 **UPSERT**。

```bash
# 自 2015-01-01 起下载默认指数（有历史则增量）
python cli.py index --start-date 2015-01-01

# 强制全量：忽略库中最新日期，从起始日重新请求
python cli.py index --start-date 2015-01-01 --full-refresh

# 额外指数：逗号分隔，每项「代码:名称」
python cli.py index --extra "000016:上证50,399005:中小板指"

# 单线程下载指数
python cli.py index --workers 1
```

并发线程数默认见 `config.DOWNLOAD_PARALLEL_WORKERS`。

---

## 4. 概念板块

```bash
# 只同步概念列表（不同步成分股）
python cli.py concept --no-constituents

# 同步列表 + 成分股；--limit 0 表示全部概念（耗时长、易被限流）
python cli.py concept --limit 0

# 与页面类似：只同步前 100 个概念的成分股
python cli.py concept --limit 100
```

---

## 一次跑多项（shell 串联）

按顺序执行示例（任一步失败不会自动中止后续命令，如需严格模式可自行加 `set -e`）：

```bash
cd /home/lom/trade/adata/astock_system

python cli.py incremental
python cli.py financial --scope all
python cli.py index --start-date 2015-01-01
python cli.py concept --limit 100
```

或使用 `&&`（前一步进程退出码非 0 时停止）：

```bash
python cli.py incremental && \
python cli.py financial --scope all && \
python cli.py index && \
python cli.py concept --limit 100
```

---

## 数据库连接：环境变量

未传 `--db-*` 时，`cli.py` 会读取下列环境变量（未设置则仍用 `config.py` 默认值）。可与标准 PostgreSQL 变量对齐：

| 变量 | 说明 |
|------|------|
| `PGHOST` / `ASTOCK_PG_HOST` | 主机 |
| `PGPORT` / `ASTOCK_PG_PORT` | 端口 |
| `PGDATABASE` / `ASTOCK_PG_DATABASE` | 库名 |
| `PGUSER` / `ASTOCK_PG_USER` | 用户 |
| `PGPASSWORD` / `ASTOCK_PG_PASSWORD` | 密码 |

示例：

```bash
export PGHOST=127.0.0.1
export PGPORT=5432
export PGDATABASE=stock_db
export PGUSER=stock_user
export PGPASSWORD=your_secret
python cli.py incremental
```

也可在命令行单独覆盖：

```bash
python cli.py incremental --db-host 127.0.0.1 --db-port 5432 \
  --db-name stock_db --db-user stock_user --db-password your_secret
```

---

## 定时任务（cron）示例

每天收盘后跑一次增量与指数（请按本机路径与 conda 修改）：

```cron
30 16 * * 1-5 cd /home/lom/trade/adata/astock_system && /root/miniconda3/bin/python cli.py incremental >> /tmp/astock_incremental.log 2>&1
```

---

## 与 Streamlit 的关系

- `cli.py` 直接调用 `StockDownloader` 与 `PostgreSQLStockDB`，逻辑与 `app.py` 各页面中的按钮一致。
- 若 `config.py` 中 `DB_TYPE` 不是 `postgresql`，当前 CLI 仍使用 `PostgreSQLStockDB`；请保持与日常使用的库类型一致，或仅在 PostgreSQL 部署下使用本脚本。
