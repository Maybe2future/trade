# -*- coding: utf-8 -*-
"""
PostgreSQL 数据库层 — 连接池 + 批量 UPSERT
覆盖股票基础信息、日线、财务、指数、概念板块、实时行情和同步日志。
"""

import pandas as pd
from sqlalchemy import create_engine, text, pool
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


class PostgreSQLStockDB:
    """股票数据库管理类（支持 PostgreSQL 和 SQLite）"""

    def __init__(self, connection_string=None, pool_size=5,
                 max_overflow=10, pool_recycle=3600):
        if connection_string is None:
            from config import get_database_url
            connection_string = get_database_url()

        self.connection_string = connection_string
        self.is_sqlite = 'sqlite' in connection_string.lower()
        self.engine = create_engine(
            connection_string,
            pool_size=pool_size if not self.is_sqlite else 0,
            max_overflow=max_overflow if not self.is_sqlite else 0,
            pool_recycle=pool_recycle if not self.is_sqlite else -1,
            pool_pre_ping=True,
            echo=False,
        )
        db_type = "SQLite" if self.is_sqlite else "PostgreSQL"
        logger.info("%s 连接已创建", db_type)

    @staticmethod
    def _records_with_none(df: pd.DataFrame):
        """将 DataFrame 转为适合数据库绑定的 records。"""
        records = df.where(df.notna(), None).to_dict('records')
        for row in records:
            for key, value in list(row.items()):
                if isinstance(value, pd.Timestamp):
                    row[key] = value.to_pydatetime()
        return records

    # ------------------------------------------------------------------
    #  DDL — 表结构初始化
    # ------------------------------------------------------------------
    def init_tables(self):
        """创建核心表结构"""
        serial_pk = "INTEGER PRIMARY KEY AUTOINCREMENT" if self.is_sqlite else "SERIAL PRIMARY KEY"
        with self.engine.begin() as conn:
            # ---- stock_basic ----
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS stock_basic (
                    stock_code   VARCHAR(20) PRIMARY KEY,
                    short_name   VARCHAR(100),
                    exchange     VARCHAR(10),
                    list_date    DATE,
                    industry     VARCHAR(200),
                    sector       VARCHAR(200),
                    update_time  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))

            # ---- stock_daily_hfq ----
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS stock_daily_hfq (
                    stock_code      VARCHAR(20)   NOT NULL,
                    trade_date      DATE          NOT NULL,
                    open            NUMERIC(12,4),
                    close           NUMERIC(12,4),
                    high            NUMERIC(12,4),
                    low             NUMERIC(12,4),
                    volume          BIGINT,
                    amount          NUMERIC(20,4),
                    change_pct      NUMERIC(8,4),
                    change_amount   NUMERIC(12,4),
                    turnover_ratio  NUMERIC(8,4),
                    pre_close       NUMERIC(12,4),
                    update_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stock_code, trade_date)
                )
            '''))

            # ---- sync_log ----
            conn.execute(text(f'''
                CREATE TABLE IF NOT EXISTS sync_log (
                    id              {serial_pk},
                    task_type       VARCHAR(50),
                    stock_code      VARCHAR(20),
                    date_range_start DATE,
                    date_range_end   DATE,
                    success_count   INTEGER DEFAULT 0,
                    fail_count      INTEGER DEFAULT 0,
                    total_records   INTEGER DEFAULT 0,
                    status          VARCHAR(20),
                    message         TEXT,
                    last_update_date DATE,
                    create_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))

            # ---- stock_financial (核心财务指标) ----
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS stock_financial (
                    stock_code       VARCHAR(20)   NOT NULL,
                    report_date      DATE          NOT NULL,
                    report_type      VARCHAR(20),
                    notice_date      DATE,
                    basic_eps        NUMERIC(16,4),
                    diluted_eps      NUMERIC(16,4),
                    net_asset_ps     NUMERIC(16,4),
                    oper_cf_ps       NUMERIC(16,4),
                    total_rev        NUMERIC(20,2),
                    gross_profit     NUMERIC(20,2),
                    net_profit_attr_sh  NUMERIC(20,2),
                    total_rev_yoy_gr    NUMERIC(12,4),
                    net_profit_yoy_gr   NUMERIC(12,4),
                    roe_wtd          NUMERIC(12,4),
                    roa_wtd          NUMERIC(12,4),
                    gross_margin     NUMERIC(12,4),
                    net_margin       NUMERIC(12,4),
                    asset_liab_ratio NUMERIC(12,4),
                    curr_ratio       NUMERIC(12,4),
                    quick_ratio      NUMERIC(12,4),
                    total_asset_turn_rate NUMERIC(12,4),
                    update_time      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stock_code, report_date)
                )
            '''))

            # ---- index_daily (指数日线行情) ----
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS index_daily (
                    index_code      VARCHAR(20)   NOT NULL,
                    index_name      VARCHAR(100),
                    trade_date      DATE          NOT NULL,
                    open            NUMERIC(12,4),
                    close           NUMERIC(12,4),
                    high            NUMERIC(12,4),
                    low             NUMERIC(12,4),
                    volume          BIGINT,
                    amount          NUMERIC(20,4),
                    change_pct      NUMERIC(8,4),
                    update_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (index_code, trade_date)
                )
            '''))

            # ---- concept_board (概念板块) ----
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS concept_board (
                    concept_code    VARCHAR(50) PRIMARY KEY,
                    concept_name    VARCHAR(200),
                    source          VARCHAR(50) DEFAULT 'ths',
                    update_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))

            # ---- concept_constituent (概念成分股) ----
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS concept_constituent (
                    concept_code    VARCHAR(50) NOT NULL,
                    stock_code      VARCHAR(20) NOT NULL,
                    stock_name      VARCHAR(100),
                    source          VARCHAR(50) DEFAULT 'ths',
                    update_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (concept_code, stock_code)
                )
            '''))

            # ---- stock_realtime (实时行情快照) ----
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS stock_realtime (
                    stock_code      VARCHAR(20) NOT NULL,
                    short_name      VARCHAR(100),
                    trade_date      DATE        NOT NULL,
                    trade_time      VARCHAR(20) NOT NULL,
                    open            NUMERIC(12,4),
                    close           NUMERIC(12,4),
                    high            NUMERIC(12,4),
                    low             NUMERIC(12,4),
                    volume          BIGINT,
                    amount          NUMERIC(20,4),
                    change_pct      NUMERIC(8,4),
                    change_amount   NUMERIC(12,4),
                    update_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stock_code, trade_date, trade_time)
                )
            '''))

            # ---- 索引 ----
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_daily_code_date
                ON stock_daily_hfq(stock_code, trade_date DESC)
            '''))
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_daily_date
                ON stock_daily_hfq(trade_date DESC)
            '''))
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_financial_code_date
                ON stock_financial(stock_code, report_date DESC)
            '''))
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_index_daily_code_date
                ON index_daily(index_code, trade_date DESC)
            '''))
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_concept_constituent_stock
                ON concept_constituent(stock_code)
            '''))
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_realtime_code_date
                ON stock_realtime(stock_code, trade_date DESC, trade_time DESC)
            '''))

        logger.info(
            "数据库表初始化完成: stock_basic, stock_daily_hfq, stock_financial, "
            "index_daily, concept_board, concept_constituent, stock_realtime, sync_log"
        )

    # ------------------------------------------------------------------
    #  stock_basic 操作
    # ------------------------------------------------------------------
    def save_stock_basic(self, df: pd.DataFrame):
        """批量 UPSERT 股票基本信息"""
        if df.empty:
            return 0

        df = df.copy()
        df['update_time'] = datetime.now()

        # 确保必需列存在
        for col in ('industry', 'sector'):
            if col not in df.columns:
                df[col] = None

        sql = text('''
            INSERT INTO stock_basic
                (stock_code, short_name, exchange, list_date, industry, sector, update_time)
            VALUES
                (:stock_code, :short_name, :exchange, :list_date,
                 :industry, :sector, :update_time)
            ON CONFLICT (stock_code) DO UPDATE SET
                short_name  = EXCLUDED.short_name,
                exchange    = EXCLUDED.exchange,
                list_date   = EXCLUDED.list_date,
                industry    = COALESCE(EXCLUDED.industry, stock_basic.industry),
                sector      = COALESCE(EXCLUDED.sector, stock_basic.sector),
                update_time = EXCLUDED.update_time
        ''')

        rows = []
        for _, r in df.iterrows():
            update_time = r.get('update_time')
            if isinstance(update_time, pd.Timestamp):
                update_time = update_time.to_pydatetime()
            rows.append({
                'stock_code': str(r.get('stock_code', '')),
                'short_name': str(r.get('short_name', '')),
                'exchange': str(r.get('exchange', '')),
                'list_date': r.get('list_date') if pd.notna(r.get('list_date')) else None,
                'industry': r.get('industry'),
                'sector': r.get('sector'),
                'update_time': update_time,
            })

        with self.engine.begin() as conn:
            conn.execute(sql, rows)

        logger.info("stock_basic: UPSERT %d 条", len(rows))
        return len(rows)

    def get_stock_basic(self, stock_code=None):
        """获取股票基本信息"""
        if stock_code:
            sql = text("SELECT * FROM stock_basic WHERE stock_code = :code")
            with self.engine.connect() as conn:
                result = conn.execute(sql, {'code': stock_code})
                return pd.DataFrame(result.fetchall(), columns=list(result.keys()))
        else:
            return pd.read_sql(text("SELECT * FROM stock_basic ORDER BY stock_code"),
                               self.engine)

    def get_stock_basic_by_industry(self, industry: str):
        """按行业筛选"""
        sql = text("SELECT * FROM stock_basic WHERE industry LIKE :ind ORDER BY stock_code")
        with self.engine.connect() as conn:
            result = conn.execute(sql, {'ind': f'%{industry}%'})
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    def get_industries(self):
        """获取所有不重复行业"""
        sql = text("SELECT DISTINCT industry FROM stock_basic WHERE industry IS NOT NULL ORDER BY industry")
        with self.engine.connect() as conn:
            result = conn.execute(sql)
            return [r[0] for r in result.fetchall()]

    # ---- 兼容旧调用 ----
    def save_stock_info(self, df):
        return self.save_stock_basic(df)

    def get_stock_info(self, stock_code=None):
        return self.get_stock_basic(stock_code)

    # ------------------------------------------------------------------
    #  stock_daily_hfq 操作
    # ------------------------------------------------------------------
    def save_daily_hfq(self, df: pd.DataFrame, stock_code: str):
        """批量 UPSERT 日线后复权数据"""
        if df.empty:
            return 0

        df = df.copy()
        df['stock_code'] = stock_code
        df['update_time'] = datetime.now()

        # 列名映射
        if 'change' in df.columns and 'change_amount' not in df.columns:
            df = df.rename(columns={'change': 'change_amount'})
        if 'trade_time' in df.columns:
            df = df.drop(columns=['trade_time'], errors='ignore')

        needed = ['stock_code', 'trade_date', 'open', 'close', 'high', 'low',
                  'volume', 'amount', 'change_pct', 'change_amount',
                  'turnover_ratio', 'pre_close', 'update_time']
        available = [c for c in needed if c in df.columns]
        df = df[available]

        # 动态构建 SQL，只包含实际存在的列
        rows = self._records_with_none(df)
        # 确保所有行都有相同的键（缺失的设为 None）
        for row in rows:
            for col in available:
                if col not in row:
                    row[col] = None

        cols = available
        placeholders = ', '.join([f':{c}' for c in cols])
        col_list = ', '.join(cols)
        update_set = ', '.join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ('stock_code', 'trade_date')])

        sql = text(f'''
            INSERT INTO stock_daily_hfq ({col_list})
            VALUES ({placeholders})
            ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                {update_set}
        ''')

        with self.engine.begin() as conn:
            conn.execute(sql, rows)

        return len(rows)

    # 兼容旧调用
    def save_history_data(self, df, stock_code):
        return self.save_daily_hfq(df, stock_code)

    def get_daily_hfq(self, stock_code, start_date=None, end_date=None,
                      limit=None):
        """查询日线后复权数据"""
        query = "SELECT * FROM stock_daily_hfq WHERE stock_code = :code"
        params = {'code': stock_code}

        if start_date:
            query += " AND trade_date >= :start"
            params['start'] = start_date
        if end_date:
            query += " AND trade_date <= :end"
            params['end'] = end_date

        query += " ORDER BY trade_date DESC"

        if limit:
            query += f" LIMIT {int(limit)}"

        with self.engine.connect() as conn:
            result = conn.execute(text(query), params)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    # 兼容旧调用
    def get_history_data(self, stock_code, start_date=None, end_date=None):
        return self.get_daily_hfq(stock_code, start_date, end_date)

    # ------------------------------------------------------------------
    #  数据验证
    # ------------------------------------------------------------------
    def verify_stock_data(self, stock_code: str) -> dict:
        """
        验证某只股票的入库情况。
        返回 {'stock_code': ..., 'count': N, 'min_date': ..., 'max_date': ...}
        """
        sql = text("""
            SELECT COUNT(*) AS cnt,
                   MIN(trade_date) AS min_date,
                   MAX(trade_date) AS max_date
            FROM stock_daily_hfq
            WHERE stock_code = :code
        """)
        with self.engine.connect() as conn:
            row = conn.execute(sql, {'code': stock_code}).fetchone()
        return {
            'stock_code': stock_code,
            'count': row[0] if row else 0,
            'min_date': str(row[1]) if row and row[1] else None,
            'max_date': str(row[2]) if row and row[2] else None,
        }

    def get_last_trade_date(self, stock_code: str):
        """返回某只股票在库中的最新交易日期（字符串），无数据返回 None"""
        sql = text("SELECT MAX(trade_date) FROM stock_daily_hfq WHERE stock_code = :code")
        with self.engine.connect() as conn:
            val = conn.execute(sql, {'code': stock_code}).scalar()
            return str(val) if val else None

    def get_data_date_range(self, stock_code):
        """兼容旧调用"""
        info = self.verify_stock_data(stock_code)
        return info['min_date'], info['max_date']

    def get_downloaded_stocks(self):
        """获取已有日线数据的股票代码列表"""
        sql = text("SELECT DISTINCT stock_code FROM stock_daily_hfq ORDER BY stock_code")
        with self.engine.connect() as conn:
            return [r[0] for r in conn.execute(sql).fetchall()]

    # ------------------------------------------------------------------
    #  stock_realtime 操作
    # ------------------------------------------------------------------
    def save_realtime_quotes(self, df: pd.DataFrame):
        """保存实时行情快照。"""
        if df.empty:
            return 0

        df = df.copy()
        now = datetime.now()
        df['update_time'] = now
        df['trade_date'] = now.date()
        df['trade_time'] = now.strftime('%H:%M:%S')

        rename_map = {
            'code': 'stock_code',
            'name': 'short_name',
            'price': 'close',
            'last_price': 'close',
            '涨跌幅': 'change_pct',
            '涨跌额': 'change_amount',
            '成交量': 'volume',
            '成交额': 'amount',
            '今开': 'open',
            '最高': 'high',
            '最低': 'low',
        }
        df = df.rename(columns=rename_map)

        db_cols = [
            'stock_code', 'short_name', 'trade_date', 'trade_time',
            'open', 'close', 'high', 'low', 'volume', 'amount',
            'change_pct', 'change_amount', 'update_time',
        ]
        available = [c for c in db_cols if c in df.columns]
        df = df[available]

        rows = self._records_with_none(df)
        for row in rows:
            for col in db_cols:
                if col not in row:
                    row[col] = None

        sql = text('''
            INSERT INTO stock_realtime
                (stock_code, short_name, trade_date, trade_time,
                 open, close, high, low, volume, amount,
                 change_pct, change_amount, update_time)
            VALUES
                (:stock_code, :short_name, :trade_date, :trade_time,
                 :open, :close, :high, :low, :volume, :amount,
                 :change_pct, :change_amount, :update_time)
            ON CONFLICT (stock_code, trade_date, trade_time) DO UPDATE SET
                short_name    = COALESCE(EXCLUDED.short_name, stock_realtime.short_name),
                open          = EXCLUDED.open,
                close         = EXCLUDED.close,
                high          = EXCLUDED.high,
                low           = EXCLUDED.low,
                volume        = EXCLUDED.volume,
                amount        = EXCLUDED.amount,
                change_pct    = EXCLUDED.change_pct,
                change_amount = EXCLUDED.change_amount,
                update_time   = EXCLUDED.update_time
        ''')

        with self.engine.begin() as conn:
            conn.execute(sql, rows)
        return len(rows)

    def get_realtime_quotes(self, stock_codes=None, limit=200):
        """查询实时行情快照。"""
        query = "SELECT * FROM stock_realtime"
        params = {}

        if stock_codes:
            placeholders = []
            for i, code in enumerate(stock_codes):
                key = f"code_{i}"
                placeholders.append(f":{key}")
                params[key] = code
            query += f" WHERE stock_code IN ({', '.join(placeholders)})"

        query += " ORDER BY trade_date DESC, trade_time DESC, stock_code"
        if limit:
            query += f" LIMIT {int(limit)}"

        with self.engine.connect() as conn:
            result = conn.execute(text(query), params)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    def get_latest_realtime_snapshot(self, limit=200):
        """按股票返回最新一笔实时行情。"""
        query = text(f'''
            SELECT *
            FROM (
                SELECT sr.*,
                       ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY trade_date DESC, trade_time DESC
                       ) AS rn
                FROM stock_realtime sr
            ) t
            WHERE rn = 1
            ORDER BY stock_code
            LIMIT {int(limit)}
        ''')
        with self.engine.connect() as conn:
            result = conn.execute(query)
            df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
        return df.drop(columns=['rn'], errors='ignore')

    def get_realtime_stats(self):
        """实时行情统计。"""
        stats = {}
        with self.engine.connect() as conn:
            stats['total_records'] = conn.execute(
                text("SELECT COUNT(*) FROM stock_realtime")
            ).scalar() or 0
            stats['total_stocks'] = conn.execute(
                text("SELECT COUNT(DISTINCT stock_code) FROM stock_realtime")
            ).scalar() or 0
            row = conn.execute(text(
                "SELECT MAX(trade_date), MAX(trade_time) FROM stock_realtime"
            )).fetchone()
            stats['last_snapshot'] = (
                f"{row[0]} {row[1]}" if row and row[0] and row[1] else '无数据'
            )
        return stats

    # ------------------------------------------------------------------
    #  sync_log 操作
    # ------------------------------------------------------------------
    def log_sync(self, task_type, stock_code=None,
                 date_range_start=None, date_range_end=None,
                 success_count=0, fail_count=0, total_records=0,
                 status='success', message=''):
        """写入同步日志"""
        sql = text('''
            INSERT INTO sync_log
                (task_type, stock_code, date_range_start, date_range_end,
                 success_count, fail_count, total_records,
                 status, message, last_update_date)
            VALUES
                (:task_type, :stock_code, :start, :end,
                 :succ, :fail, :total,
                 :status, :message, CURRENT_DATE)
        ''')
        with self.engine.begin() as conn:
            conn.execute(sql, {
                'task_type': task_type,
                'stock_code': stock_code,
                'start': date_range_start,
                'end': date_range_end,
                'succ': success_count,
                'fail': fail_count,
                'total': total_records,
                'status': status,
                'message': message,
            })

    # 兼容旧调用
    def log_download(self, stock_code, download_type, start_date, end_date,
                     records_count, status, message=''):
        self.log_sync(
            task_type=download_type,
            stock_code=stock_code,
            date_range_start=start_date,
            date_range_end=end_date,
            total_records=records_count,
            success_count=1 if status == 'success' else 0,
            fail_count=0 if status == 'success' else 1,
            status=status,
            message=message,
        )

    def get_sync_logs(self, limit=200):
        """获取同步日志"""
        sql = text(f"SELECT * FROM sync_log ORDER BY create_time DESC LIMIT {int(limit)}")
        with self.engine.connect() as conn:
            result = conn.execute(sql)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    # 兼容旧调用
    def get_download_logs(self, limit=100):
        return self.get_sync_logs(limit)

    # ------------------------------------------------------------------
    #  统计
    # ------------------------------------------------------------------
    def get_statistics(self):
        """全局统计信息"""
        stats = {}
        with self.engine.connect() as conn:
            stats['total_stocks'] = conn.execute(
                text("SELECT COUNT(*) FROM stock_basic")).scalar() or 0

            stats['downloaded_stocks'] = conn.execute(
                text("SELECT COUNT(DISTINCT stock_code) FROM stock_daily_hfq")).scalar() or 0

            stats['total_history_records'] = conn.execute(
                text("SELECT COUNT(*) FROM stock_daily_hfq")).scalar() or 0
            stats['total_realtime_records'] = conn.execute(
                text("SELECT COUNT(*) FROM stock_realtime")).scalar() or 0
            stats['total_financial_records'] = conn.execute(
                text("SELECT COUNT(*) FROM stock_financial")).scalar() or 0
            stats['total_index_records'] = conn.execute(
                text("SELECT COUNT(*) FROM index_daily")).scalar() or 0
            stats['total_concepts'] = conn.execute(
                text("SELECT COUNT(*) FROM concept_board")).scalar() or 0

            if not self.is_sqlite:
                try:
                    stats['database_size'] = conn.execute(
                        text("SELECT pg_size_pretty(pg_total_relation_size('stock_daily_hfq'))")
                    ).scalar()
                except Exception:
                    stats['database_size'] = 'N/A'
            else:
                stats['database_size'] = 'N/A (SQLite)'

            row = conn.execute(text(
                "SELECT MIN(trade_date), MAX(trade_date) FROM stock_daily_hfq"
            )).fetchone()
            if row and row[0]:
                stats['date_range'] = f"{row[0]} ~ {row[1]}"
                stats['last_update'] = str(row[1])
            else:
                stats['date_range'] = '无数据'
                stats['last_update'] = '无'

        return stats

    # ------------------------------------------------------------------
    #  导出
    # ------------------------------------------------------------------
    def export_to_csv(self, stock_code, filepath):
        df = self.get_daily_hfq(stock_code)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        return len(df)

    # ------------------------------------------------------------------
    #  stock_financial 操作
    # ------------------------------------------------------------------
    def save_financial(self, df: pd.DataFrame, stock_code: str):
        """批量 UPSERT 核心财务指标"""
        if df.empty:
            return 0

        df = df.copy()
        df['stock_code'] = stock_code
        df['update_time'] = datetime.now()

        # 只保留表中存在的列
        db_cols = [
            'stock_code', 'report_date', 'report_type', 'notice_date',
            'basic_eps', 'diluted_eps', 'net_asset_ps', 'oper_cf_ps',
            'total_rev', 'gross_profit', 'net_profit_attr_sh',
            'total_rev_yoy_gr', 'net_profit_yoy_gr',
            'roe_wtd', 'roa_wtd', 'gross_margin', 'net_margin',
            'asset_liab_ratio', 'curr_ratio', 'quick_ratio',
            'total_asset_turn_rate', 'update_time',
        ]
        available = [c for c in db_cols if c in df.columns]
        df = df[available]

        sql = text('''
            INSERT INTO stock_financial
                (stock_code, report_date, report_type, notice_date,
                 basic_eps, diluted_eps, net_asset_ps, oper_cf_ps,
                 total_rev, gross_profit, net_profit_attr_sh,
                 total_rev_yoy_gr, net_profit_yoy_gr,
                 roe_wtd, roa_wtd, gross_margin, net_margin,
                 asset_liab_ratio, curr_ratio, quick_ratio,
                 total_asset_turn_rate, update_time)
            VALUES
                (:stock_code, :report_date, :report_type, :notice_date,
                 :basic_eps, :diluted_eps, :net_asset_ps, :oper_cf_ps,
                 :total_rev, :gross_profit, :net_profit_attr_sh,
                 :total_rev_yoy_gr, :net_profit_yoy_gr,
                 :roe_wtd, :roa_wtd, :gross_margin, :net_margin,
                 :asset_liab_ratio, :curr_ratio, :quick_ratio,
                 :total_asset_turn_rate, :update_time)
            ON CONFLICT (stock_code, report_date) DO UPDATE SET
                report_type      = EXCLUDED.report_type,
                notice_date      = EXCLUDED.notice_date,
                basic_eps        = EXCLUDED.basic_eps,
                diluted_eps      = EXCLUDED.diluted_eps,
                net_asset_ps     = EXCLUDED.net_asset_ps,
                oper_cf_ps       = EXCLUDED.oper_cf_ps,
                total_rev        = EXCLUDED.total_rev,
                gross_profit     = EXCLUDED.gross_profit,
                net_profit_attr_sh = EXCLUDED.net_profit_attr_sh,
                total_rev_yoy_gr = EXCLUDED.total_rev_yoy_gr,
                net_profit_yoy_gr = EXCLUDED.net_profit_yoy_gr,
                roe_wtd          = EXCLUDED.roe_wtd,
                roa_wtd          = EXCLUDED.roa_wtd,
                gross_margin     = EXCLUDED.gross_margin,
                net_margin       = EXCLUDED.net_margin,
                asset_liab_ratio = EXCLUDED.asset_liab_ratio,
                curr_ratio       = EXCLUDED.curr_ratio,
                quick_ratio      = EXCLUDED.quick_ratio,
                total_asset_turn_rate = EXCLUDED.total_asset_turn_rate,
                update_time      = EXCLUDED.update_time
        ''')

        rows = self._records_with_none(df)
        # 确保每行都有所有必需的键
        for row in rows:
            for col in db_cols:
                if col not in row:
                    row[col] = None

        with self.engine.begin() as conn:
            conn.execute(sql, rows)

        logger.info("stock_financial: UPSERT %d 条 (stock_code=%s)", len(rows), stock_code)
        return len(rows)

    def get_financial(self, stock_code, report_type=None, limit=None):
        """查询核心财务指标"""
        query = "SELECT * FROM stock_financial WHERE stock_code = :code"
        params = {'code': stock_code}

        if report_type:
            query += " AND report_type = :rtype"
            params['rtype'] = report_type

        query += " ORDER BY report_date DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

        with self.engine.connect() as conn:
            result = conn.execute(text(query), params)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    def get_financial_stats(self):
        """财务数据统计"""
        stats = {}
        with self.engine.connect() as conn:
            stats['total_stocks'] = conn.execute(
                text("SELECT COUNT(DISTINCT stock_code) FROM stock_financial")
            ).scalar() or 0
            stats['total_records'] = conn.execute(
                text("SELECT COUNT(*) FROM stock_financial")
            ).scalar() or 0
            row = conn.execute(text(
                "SELECT MIN(report_date), MAX(report_date) FROM stock_financial"
            )).fetchone()
            if row and row[0]:
                stats['date_range'] = f"{row[0]} ~ {row[1]}"
            else:
                stats['date_range'] = '无数据'
        return stats

    # ------------------------------------------------------------------
    #  concept_board 操作
    # ------------------------------------------------------------------
    def save_concept_boards(self, df: pd.DataFrame, source='ths'):
        """批量保存概念板块列表。"""
        if df.empty:
            return 0

        df = df.copy()
        rename_map = {
            'code': 'concept_code',
            '概念代码': 'concept_code',
            '板块代码': 'concept_code',
            'name': 'concept_name',
            '概念名称': 'concept_name',
            '板块名称': 'concept_name',
        }
        df = df.rename(columns=rename_map)

        if 'concept_code' not in df.columns:
            if 'concept_name' in df.columns:
                df['concept_code'] = df['concept_name']
            else:
                raise ValueError('概念板块数据缺少 concept_code/concept_name 字段')
        if 'concept_name' not in df.columns:
            df['concept_name'] = df['concept_code']

        # 若上游误产生重复列名，df['concept_code'] 会是 DataFrame，没有 .str；统一压成单列 Series
        def _as_series(frame: pd.DataFrame, col: str) -> pd.Series:
            x = frame[col]
            if isinstance(x, pd.DataFrame):
                return x.bfill(axis=1).iloc[:, 0]
            return x

        code_s = _as_series(df, 'concept_code')
        name_s = _as_series(df, 'concept_name')
        df = pd.DataFrame({
            'concept_code': code_s.fillna(name_s).astype(str).str.strip(),
            'concept_name': name_s.astype(str).str.strip(),
        })
        df = df[(df['concept_code'] != '') & (df['concept_name'] != '')]
        df = df.drop_duplicates(subset=['concept_code'])
        df['source'] = source
        df['update_time'] = datetime.now()

        sql = text('''
            INSERT INTO concept_board
                (concept_code, concept_name, source, update_time)
            VALUES
                (:concept_code, :concept_name, :source, :update_time)
            ON CONFLICT (concept_code) DO UPDATE SET
                concept_name = EXCLUDED.concept_name,
                source = EXCLUDED.source,
                update_time = EXCLUDED.update_time
        ''')
        rows = self._records_with_none(df)
        with self.engine.begin() as conn:
            conn.execute(sql, rows)
        return len(rows)

    def replace_concept_constituents(self, concept_code: str, df: pd.DataFrame,
                                     source='ths'):
        """覆盖更新某个概念板块的成分股。"""
        if df.empty:
            return 0

        df = df.copy()
        rename_map = {
            'code': 'stock_code',
            '代码': 'stock_code',
            '证券代码': 'stock_code',
            'name': 'stock_name',
            '名称': 'stock_name',
            '证券简称': 'stock_name',
        }
        df = df.rename(columns=rename_map)
        if 'stock_code' not in df.columns:
            raise ValueError('概念成分股数据缺少 stock_code 字段')
        if 'stock_name' not in df.columns:
            df['stock_name'] = None

        df = df[['stock_code', 'stock_name']].copy()
        df['stock_code'] = df['stock_code'].astype(str).str.zfill(6)
        df['concept_code'] = concept_code
        df['source'] = source
        df['update_time'] = datetime.now()

        rows = self._records_with_none(df)
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM concept_constituent WHERE concept_code = :concept_code"),
                {'concept_code': concept_code}
            )
            conn.execute(text('''
                INSERT INTO concept_constituent
                    (concept_code, stock_code, stock_name, source, update_time)
                VALUES
                    (:concept_code, :stock_code, :stock_name, :source, :update_time)
                ON CONFLICT (concept_code, stock_code) DO UPDATE SET
                    stock_name = EXCLUDED.stock_name,
                    source = EXCLUDED.source,
                    update_time = EXCLUDED.update_time
            '''), rows)
        return len(rows)

    def get_concept_boards(self, limit=None):
        query = "SELECT * FROM concept_board ORDER BY concept_name"
        if limit:
            query += f" LIMIT {int(limit)}"
        with self.engine.connect() as conn:
            result = conn.execute(text(query))
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    def get_concept_constituents(self, concept_code):
        with self.engine.connect() as conn:
            result = conn.execute(text('''
                SELECT *
                FROM concept_constituent
                WHERE concept_code = :concept_code
                ORDER BY stock_code
            '''), {'concept_code': concept_code})
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    def get_concept_stats(self):
        stats = {}
        with self.engine.connect() as conn:
            stats['total_concepts'] = conn.execute(
                text("SELECT COUNT(*) FROM concept_board")
            ).scalar() or 0
            stats['total_constituents'] = conn.execute(
                text("SELECT COUNT(*) FROM concept_constituent")
            ).scalar() or 0
            row = conn.execute(text(
                "SELECT MAX(update_time) FROM concept_board"
            )).fetchone()
            stats['last_update'] = str(row[0]) if row and row[0] else '无数据'
        return stats

    # ------------------------------------------------------------------
    #  index_daily 操作
    # ------------------------------------------------------------------
    def save_index_daily(self, df: pd.DataFrame, index_code: str,
                         index_name: str = None):
        """批量 UPSERT 指数日线数据"""
        if df.empty:
            return 0

        df = df.copy()
        df['index_code'] = index_code
        if index_name:
            df['index_name'] = index_name
        elif 'index_name' not in df.columns:
            df['index_name'] = None
        df['update_time'] = datetime.now()

        # adata 的指数行情返回列名可能是 price 而不是 close
        if 'price' in df.columns and 'close' not in df.columns:
            df = df.rename(columns={'price': 'close'})

        db_cols = [
            'index_code', 'index_name', 'trade_date',
            'open', 'close', 'high', 'low',
            'volume', 'amount', 'change_pct', 'update_time',
        ]
        available = [c for c in db_cols if c in df.columns]
        df = df[available]

        sql = text('''
            INSERT INTO index_daily
                (index_code, index_name, trade_date,
                 open, close, high, low,
                 volume, amount, change_pct, update_time)
            VALUES
                (:index_code, :index_name, :trade_date,
                 :open, :close, :high, :low,
                 :volume, :amount, :change_pct, :update_time)
            ON CONFLICT (index_code, trade_date) DO UPDATE SET
                index_name  = COALESCE(EXCLUDED.index_name, index_daily.index_name),
                open        = EXCLUDED.open,
                close       = EXCLUDED.close,
                high        = EXCLUDED.high,
                low         = EXCLUDED.low,
                volume      = EXCLUDED.volume,
                amount      = EXCLUDED.amount,
                change_pct  = EXCLUDED.change_pct,
                update_time = EXCLUDED.update_time
        ''')

        rows = self._records_with_none(df)
        for row in rows:
            for col in db_cols:
                if col not in row:
                    row[col] = None

        with self.engine.begin() as conn:
            conn.execute(sql, rows)

        logger.info("index_daily: UPSERT %d 条 (index_code=%s)", len(rows), index_code)
        return len(rows)

    def get_index_daily(self, index_code, start_date=None, end_date=None,
                        limit=None):
        """查询指数日线"""
        query = "SELECT * FROM index_daily WHERE index_code = :code"
        params = {'code': index_code}

        if start_date:
            query += " AND trade_date >= :start"
            params['start'] = start_date
        if end_date:
            query += " AND trade_date <= :end"
            params['end'] = end_date

        query += " ORDER BY trade_date DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

        with self.engine.connect() as conn:
            result = conn.execute(text(query), params)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    def get_last_index_date(self, index_code: str):
        """返回指数最新交易日"""
        sql = text("SELECT MAX(trade_date) FROM index_daily WHERE index_code = :code")
        with self.engine.connect() as conn:
            val = conn.execute(sql, {'code': index_code}).scalar()
            return str(val) if val else None

    def get_index_stats(self):
        """指数数据统计"""
        stats = {}
        with self.engine.connect() as conn:
            stats['total_indices'] = conn.execute(
                text("SELECT COUNT(DISTINCT index_code) FROM index_daily")
            ).scalar() or 0
            stats['total_records'] = conn.execute(
                text("SELECT COUNT(*) FROM index_daily")
            ).scalar() or 0
            row = conn.execute(text(
                "SELECT MIN(trade_date), MAX(trade_date) FROM index_daily"
            )).fetchone()
            if row and row[0]:
                stats['date_range'] = f"{row[0]} ~ {row[1]}"
            else:
                stats['date_range'] = '无数据'
        return stats

    def get_downloaded_indices(self):
        """获取已有数据的指数列表"""
        sql = text("SELECT DISTINCT index_code FROM index_daily ORDER BY index_code")
        with self.engine.connect() as conn:
            return [r[0] for r in conn.execute(sql).fetchall()]

    # ------------------------------------------------------------------
    #  维护
    # ------------------------------------------------------------------
    def optimize(self):
        """ANALYZE 更新查询统计"""
        with self.engine.begin() as conn:
            for tbl in ['stock_daily_hfq', 'stock_basic', 'stock_financial',
                        'index_daily', 'concept_board', 'concept_constituent',
                        'stock_realtime']:
                try:
                    conn.execute(text(f"ANALYZE {tbl}"))
                except Exception:
                    pass
        logger.info("数据库 ANALYZE 完成")
