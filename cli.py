# -*- coding: utf-8 -*-
"""
命令行入口：不依赖 Streamlit，直接调用下载器与数据库。
用法见同目录 CLI.md。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

# 保证可从任意工作目录找到 config / core
_SYS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SYS_DIR not in sys.path:
    sys.path.insert(0, _SYS_DIR)

from config import (  # noqa: E402
    POOL_SIZE,
    MAX_OVERFLOW,
    POOL_RECYCLE,
    get_database_url,
)
from core.downloader import StockDownloader  # noqa: E402
from core.postgresql_db import PostgreSQLStockDB  # noqa: E402


def _parse_port_env():
    """从环境变量解析端口；非法或缺失时返回 None，交给 get_database_url 用默认。"""
    raw = os.environ.get("PGPORT") or os.environ.get("ASTOCK_PG_PORT")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _build_database_url(args: argparse.Namespace) -> str:
    """命令行 --db-* 优先，其次环境变量，最后 config.py。"""
    if any(
        [
            args.db_host,
            args.db_port is not None,
            args.db_name,
            args.db_user,
            args.db_password,
        ]
    ):
        return get_database_url(
            host=args.db_host,
            port=args.db_port,
            database=args.db_name,
            username=args.db_user,
            password=args.db_password,
        )
    return get_database_url(
        host=os.environ.get("PGHOST") or os.environ.get("ASTOCK_PG_HOST"),
        port=_parse_port_env(),
        database=os.environ.get("PGDATABASE") or os.environ.get("ASTOCK_PG_DATABASE"),
        username=os.environ.get("PGUSER") or os.environ.get("ASTOCK_PG_USER"),
        password=os.environ.get("PGPASSWORD") or os.environ.get("ASTOCK_PG_PASSWORD"),
    )


def _progress_printer(msg: str, progress: float | None = None) -> None:
    """把下载器进度打到 stderr，带时间戳。"""
    ts = datetime.now().strftime("%H:%M:%S")
    if progress is not None:
        print(f"[{ts}] [{progress * 100:.1f}%] {msg}", file=sys.stderr)
    else:
        print(f"[{ts}] {msg}", file=sys.stderr)


def _make_downloader(args: argparse.Namespace) -> StockDownloader:
    """创建数据库连接与 StockDownloader。"""
    url = _build_database_url(args)
    db = PostgreSQLStockDB(
        connection_string=url,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_recycle=POOL_RECYCLE,
    )
    dl = StockDownloader(db)
    dl.reset_stop()
    dl.set_progress_callback(_progress_printer)
    return dl


def _parse_stock_codes(text: str) -> list[str]:
    """支持逗号或换行分隔的股票代码列表。"""
    parts = text.replace("\n", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def _cmd_incremental(dl: StockDownloader, args: argparse.Namespace) -> int:
    """增量更新 K 线（与页面「增量更新」一致）。"""
    codes = None
    if args.codes:
        codes = _parse_stock_codes(args.codes)
    elif args.codes_file:
        with open(args.codes_file, encoding="utf-8") as f:
            codes = _parse_stock_codes(f.read())
    result = dl.update_incremental(stock_codes=codes)
    print(result)
    # 部分个股失败仍返回 0，便于 cron；看 stderr 日志与打印字典中的 failed
    return 0


def _cmd_financial(dl: StockDownloader, args: argparse.Namespace) -> int:
    """财务数据批量下载。"""
    db = dl.db
    stock_codes: list[str] = []

    if args.scope == "codes":
        if not args.codes:
            print("财务 --scope codes 需要 --codes", file=sys.stderr)
            return 2
        stock_codes = _parse_stock_codes(args.codes)
    elif args.scope == "industry":
        if not args.industry:
            print("财务 --scope industry 需要 --industry", file=sys.stderr)
            return 2
        ind_df = db.get_stock_basic_by_industry(args.industry)
        if ind_df is None or ind_df.empty:
            print(f"行业「{args.industry}」下无股票或未同步股票列表", file=sys.stderr)
            return 1
        stock_codes = ind_df["stock_code"].tolist()
    else:
        # 全量：stock_basic 全部代码
        basic = db.get_stock_basic()
        if basic is None or basic.empty:
            print("股票列表为空，请先同步股票基础信息", file=sys.stderr)
            return 1
        stock_codes = basic["stock_code"].tolist()

    delay = args.delay if args.delay is not None else None
    result = dl.download_financial_batch(
        stock_codes,
        delay=delay,
        parallel_workers=args.workers,
    )
    print(result)
    return 0


def _parse_extra_indices(s: str | None) -> dict[str, str] | None:
    """
    解析额外指数：格式与页面一致，逗号分隔，每项 code:name。
    例：000016:上证50,399005:中小板指
    """
    if not s or not s.strip():
        return None
    out: dict[str, str] = {}
    for item in s.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":", 1)
        if len(parts) != 2:
            print(f"忽略无效指数项（需 代码:名称）: {item}", file=sys.stderr)
            continue
        code, name = parts[0].strip(), parts[1].strip()
        if code and name:
            out[code] = name
    return out or None


def _cmd_index(dl: StockDownloader, args: argparse.Namespace) -> int:
    """下载默认 + 可选额外指数的日线行情。"""
    extra = _parse_extra_indices(args.extra)
    result = dl.download_all_indices(
        start_date=args.start_date,
        extra_indices=extra,
        incremental=not args.full_refresh,
        parallel_workers=args.workers,
    )
    print(result)
    return 0


def _cmd_concept(dl: StockDownloader, args: argparse.Namespace) -> int:
    """同步概念板块列表；可选同步成分股。"""
    limit = None if args.limit == 0 else int(args.limit)
    result = dl.sync_concept_boards(
        sync_constituents=not args.no_constituents,
        limit=limit,
    )
    print(result)
    # 部分成分股失败仍算 partial，命令行返回 0 便于定时任务继续
    return 0


def _add_db_args(p: argparse.ArgumentParser) -> None:
    """各子命令共用的数据库覆盖参数。"""
    p.add_argument("--db-host", default=None, help="PostgreSQL 主机，默认 config / 环境变量")
    p.add_argument("--db-port", type=int, default=None, help="端口")
    p.add_argument("--db-name", default=None, help="数据库名")
    p.add_argument("--db-user", default=None, help="用户名")
    p.add_argument("--db-password", default=None, help="密码")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="A 股数据系统命令行（增量 / 财务 / 指数 / 概念）",
    )
    # 数据库参数只在各子命令后传递，例如: cli.py incremental --db-host localhost
    sub = parser.add_subparsers(dest="command", required=True)

    # 增量更新
    p_inc = sub.add_parser("incremental", help="增量更新已下载股票的日 K")
    _add_db_args(p_inc)
    p_inc.add_argument(
        "--codes",
        default=None,
        help="仅更新这些代码，逗号或换行分隔；不传则更新库中全部已下载股票",
    )
    p_inc.add_argument(
        "--codes-file",
        default=None,
        help="从文件读取代码列表（逗号/换行分隔）",
    )

    # 财务
    p_fin = sub.add_parser("financial", help="批量下载财务核心指标")
    _add_db_args(p_fin)
    p_fin.add_argument(
        "--scope",
        choices=("codes", "industry", "all"),
        default="all",
        help="codes=指定代码 industry=某行业 all=全市场（耗时长）",
    )
    p_fin.add_argument("--codes", default=None, help="--scope codes 时使用")
    p_fin.add_argument("--industry", default=None, help="--scope industry 时使用")
    p_fin.add_argument(
        "--delay",
        type=float,
        default=None,
        help="单只间隔秒数，默认使用 config.DOWNLOAD_DELAY",
    )
    p_fin.add_argument(
        "--workers",
        type=int,
        default=None,
        help="并发线程数，默认 config.DOWNLOAD_PARALLEL_WORKERS；1 强制串行",
    )

    # 指数
    p_idx = sub.add_parser("index", help="下载默认常用指数 + 可选额外指数")
    _add_db_args(p_idx)
    p_idx.add_argument(
        "--start-date",
        default="2015-01-01",
        help="指数日线起始日期 YYYY-MM-DD",
    )
    p_idx.add_argument(
        "--full-refresh",
        action="store_true",
        help="强制全量：不从库里最新交易日续拉，从起始日重新请求",
    )
    p_idx.add_argument(
        "--workers",
        type=int,
        default=None,
        help="并发线程数，默认 config.DOWNLOAD_PARALLEL_WORKERS；1 强制串行",
    )
    p_idx.add_argument(
        "--extra",
        default=None,
        help='额外指数，逗号分隔，每项 "代码:名称"，如 000016:上证50,399005:中小板指',
    )

    # 概念
    p_con = sub.add_parser("concept", help="同步同花顺概念板块（可选成分股）")
    _add_db_args(p_con)
    p_con.add_argument(
        "--no-constituents",
        action="store_true",
        help="只更新概念列表，不同步成分股",
    )
    p_con.add_argument(
        "--limit",
        type=int,
        default=0,
        help="同步成分股时最多处理多少个概念，0 表示全部（慎用，耗时长）",
    )

    args = parser.parse_args(argv)

    try:
        dl = _make_downloader(args)
    except Exception as e:
        print(f"初始化数据库失败: {e}", file=sys.stderr)
        return 1

    if args.command == "incremental":
        return _cmd_incremental(dl, args)
    if args.command == "financial":
        return _cmd_financial(dl, args)
    if args.command == "index":
        return _cmd_index(dl, args)
    if args.command == "concept":
        return _cmd_concept(dl, args)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
