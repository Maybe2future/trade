# -*- coding: utf-8 -*-
"""
A股数据下载引擎
- 空数据预警
- 后复权 (adjust_type=1)
- 分批容错 + 自动重试
- 增量更新
- CSV 导出
"""

import adata
import akshare as ak
import pandas as pd
import time
import os
import traceback
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from core.qveris_client import QVerisClient
from core.tencent_provider import TencentProvider
from config import (
    DOWNLOAD_DELAY, BATCH_SIZE, RETRY_COUNT,
    RETRY_WAIT_BASE, DEFAULT_YEARS, DOWNLOAD_PARALLEL_WORKERS,
)

logger = logging.getLogger(__name__)


class StockDownloader:
    """股票数据下载器"""

    def __init__(self, db):
        self.db = db
        self.progress_callback = None
        self.stop_flag = threading.Event()
        self.qveris = QVerisClient()
        self.tencent = TencentProvider()
        # 并发下载时 Streamlit 回调与进度条非线程安全，串行化 UI 更新
        self._progress_lock = threading.Lock()

    # ---------- progress ----------
    def set_progress_callback(self, callback):
        self.progress_callback = callback

    def _progress(self, msg, progress=None):
        with self._progress_lock:
            if self.progress_callback:
                self.progress_callback(msg, progress)
        logger.info(msg)

    @staticmethod
    def _effective_parallel_workers(override=None):
        """解析并发线程数；None 或非法时使用 config。"""
        try:
            w = int(override) if override is not None else int(DOWNLOAD_PARALLEL_WORKERS)
        except (TypeError, ValueError):
            w = 1
        return max(1, w)

    def _sleep_before_retry(self, attempt, prefix=''):
        wait = RETRY_WAIT_BASE * (2 ** (attempt - 1))
        if prefix:
            self._progress(f"⚠ {prefix} 第{attempt}次失败，{wait:.0f}s 后重试...")
        time.sleep(wait)

    def _lookup_stock_name(self, stock_code):
        try:
            df = self.db.get_stock_basic(stock_code)
            if df is not None and not df.empty:
                return str(df.iloc[0].get('short_name') or stock_code)
        except Exception:
            pass
        return str(stock_code)

    @staticmethod
    def _to_numeric_series(df, col):
        if col not in df.columns:
            return None
        return pd.to_numeric(
            df[col].astype(str).str.replace(',', '').str.replace('-', '', regex=False),
            errors='coerce',
        )

    def _fetch_stock_history_qveris(self, stock_code, start_date, end_date):
        if not self.qveris.enabled:
            return pd.DataFrame()

        stock_name = self._lookup_stock_name(stock_code)
        query = f"{stock_name}({stock_code}) {start_date} 到 {end_date} 日行情 后复权"
        df = self.qveris.execute_df('mcp_gildata.stockdailyquote.v1', query)
        if df.empty:
            return df

        column_map = {
            '交易日': 'trade_date',
            '今开盘(元)': 'open',
            '今开盘': 'open',
            '最高价(元)': 'high',
            '最高价': 'high',
            '最低价(元)': 'low',
            '最低价': 'low',
            '收盘价(元)': 'close',
            '收盘价': 'close',
            '昨收盘(元)': 'pre_close',
            '昨收盘': 'pre_close',
            '涨跌幅(%)': 'change_pct',
            '涨跌(元)': 'change_amount',
            '涨跌': 'change_amount',
            '成交量(万股)': 'volume',
            '成交额(亿元)': 'amount',
            '股票代码': 'stock_code',
        }
        df = df.rename(columns=column_map)
        if 'volume' in df.columns:
            df['volume'] = self._to_numeric_series(df, 'volume') * 10000
        if 'amount' in df.columns:
            df['amount'] = self._to_numeric_series(df, 'amount') * 1e8
        for col in ['open', 'high', 'low', 'close', 'pre_close', 'change_pct', 'change_amount']:
            if col in df.columns:
                df[col] = self._to_numeric_series(df, col)
        return df

    def _fetch_index_qveris(self, index_code, index_name, start_date, end_date):
        if not self.qveris.enabled:
            return pd.DataFrame()

        query = f"{index_name}({index_code}) {start_date} 到 {end_date} 日线行情"
        df = self.qveris.execute_df('mcp_gildata.indexdailyquote.v1', query)
        if df.empty:
            return df

        column_map = {
            '交易日': 'trade_date',
            '今开盘(点)': 'open',
            '最高价(点)': 'high',
            '最低价(点)': 'low',
            '收盘价(点)': 'close',
            '昨收盘(点)': 'pre_close',
            '涨跌幅(%)': 'change_pct',
            '成交量(万股)': 'volume',
            '成交额(亿元)': 'amount',
            '指数代码': 'index_code',
            '指数名称': 'index_name',
        }
        df = df.rename(columns=column_map)
        if 'index_code' in df.columns:
            df = df[df['index_code'] == index_code]
        if 'volume' in df.columns:
            df['volume'] = self._to_numeric_series(df, 'volume') * 10000
        if 'amount' in df.columns:
            df['amount'] = self._to_numeric_series(df, 'amount') * 1e8
        for col in ['open', 'high', 'low', 'close', 'pre_close', 'change_pct']:
            if col in df.columns:
                df[col] = self._to_numeric_series(df, col)
        return df

    def _fetch_concept_stocks_qveris(self, concept_code):
        if not self.qveris.enabled:
            return pd.DataFrame()

        query = f"{concept_code} 概念成分股"
        df = self.qveris.execute_df('mcp_gildata.conceptconstituentstocks.v1', query)
        if df.empty:
            return df
        return df.rename(columns={
            '概念代码': 'concept_code',
            '概念名称': 'concept_name',
            '股票代码': 'stock_code',
            '股票名称': 'stock_name',
        })

    def _fetch_realtime_quotes_qveris(self, stock_codes):
        if not self.qveris.enabled or not stock_codes:
            return pd.DataFrame()
        names = [self._lookup_stock_name(code) for code in stock_codes[:30]]
        query = '、'.join(names) + ' 实时行情'
        df = self.qveris.execute_df('mcp_gildata.asharelivequote.v1', query)
        if df.empty:
            return df
        return df.rename(columns={
            '股票代码': 'stock_code',
            '股票名称': 'short_name',
            '现价(元)': 'price',
            '最新价(元)': 'price',
            '涨跌(元)': 'change',
            '涨跌幅(%)': 'change_pct',
            '成交量(万股)': 'volume',
            '成交额(亿元)': 'amount',
            '今开盘(元)': 'open',
            '最高价(元)': 'high',
            '最低价(元)': 'low',
        })

    def _fetch_stock_history_akshare(self, stock_code, start_date, end_date):
        """
        备用日线源：ak.stock_zh_a_hist
        返回统一后的 DataFrame。
        """
        df = ak.stock_zh_a_hist(
            symbol=stock_code,
            period='daily',
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust='hfq',
        )
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={
            '日期': 'trade_date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'change_pct',
            '涨跌额': 'change_amount',
            '换手率': 'turnover_ratio',
        })
        if 'pre_close' not in df.columns and 'close' in df.columns:
            df['pre_close'] = pd.to_numeric(df['close'], errors='coerce').shift(1)
        return df

    def _fetch_stock_history_tencent(self, stock_code, start_date, end_date):
        return self.tencent.fetch_daily_history(
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date,
            count=640,
            is_index=False,
        )

    # ==========================================================
    # A. 股票池同步
    # ==========================================================
    def fetch_all_stocks(self) -> pd.DataFrame:
        """
        获取全市场（沪深京）股票列表并写入 stock_basic。
        返回 DataFrame。
        """
        self._progress("正在获取全市场股票列表 (ak.stock_info_a_code_name) ...")
        try:
            df = ak.stock_info_a_code_name()
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                self._progress("⚠ 股票列表返回为空，请检查网络或 akshare 版本")
                return pd.DataFrame()

            # rename code -> stock_code, name -> short_name
            df = df.rename(columns={'code': 'stock_code', 'name': 'short_name'})
            
            self._progress(f"✓ 获取基本信息成功: {len(df)} 只股票，正在抓取行业信息...")
            
            import threading
            from concurrent.futures import ThreadPoolExecutor
            
            # Fetch industries
            df_ind = ak.stock_board_industry_name_em()
            boards = df_ind['板块名称'].tolist() if df_ind is not None and not df_ind.empty else []
            
            code_to_ind = {}
            def fetch_board(board):
                try:
                    cons = ak.stock_board_industry_cons_em(symbol=board)
                    for _, row in cons.iterrows():
                        code = str(row['代码']).zfill(6)
                        code_to_ind[code] = board
                except Exception:
                    pass
                    
            if boards:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    executor.map(fetch_board, boards)
                    
            df['industry'] = df['stock_code'].map(code_to_ind)

            self._progress(f"✓ 行业映射完成。")

            # 写入数据库
            saved = self.db.save_stock_basic(df)
            self._progress(f"✓ 已同步至 stock_basic 表: {saved} 条")

            # 记录同步日志
            self.db.log_sync(
                task_type='sync_stock_list',
                success_count=saved,
                total_records=saved,
                status='success',
                message=f'同步 {saved} 只股票',
            )
            return df
        except Exception as e:
            self._progress(f"✗ 获取股票列表失败: {e}")
            self.db.log_sync(
                task_type='sync_stock_list',
                status='failed',
                message=str(e),
            )
            return pd.DataFrame()

    # ==========================================================
    # B. 单只股票下载（后复权）
    # ==========================================================
    def download_stock_history(self, stock_code, start_date,
                               end_date=None, k_type=1,
                               csv_path=None):
        """
        下载单只股票后复权日线数据。
        csv_path: 非空则同时保存 CSV。
        返回 (success, records, message)
        """
        if self.stop_flag.is_set():
            return False, 0, "用户取消"

        end_date = end_date or datetime.now().strftime('%Y-%m-%d')

        for attempt in range(1, RETRY_COUNT + 1):
            try:
                df = adata.stock.market.get_market(
                    stock_code=stock_code,
                    k_type=k_type,
                    start_date=start_date,
                    end_date=end_date,
                    adjust_type=1,  # 后复权
                )

                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    self._progress(f"⚠ {stock_code} AData 返回空数据，尝试腾讯免费源")
                    try:
                        df = self._fetch_stock_history_tencent(stock_code, start_date, end_date)
                    except Exception as fallback_e:
                        self._progress(f"  腾讯免费源失败: {fallback_e}")
                        df = pd.DataFrame()

                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    self._progress(f"⚠ {stock_code} 腾讯免费源返回空数据，尝试 AkShare 备用源")
                    try:
                        df = self._fetch_stock_history_akshare(stock_code, start_date, end_date)
                    except Exception as fallback_e:
                        self._progress(f"  AkShare 备用源失败: {fallback_e}")
                        df = pd.DataFrame()

                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    self._progress(f"⚠ {stock_code} AkShare 返回空数据，尝试 QVeris 备用源")
                    try:
                        df = self._fetch_stock_history_qveris(stock_code, start_date, end_date)
                    except Exception as fallback_e:
                        self._progress(f"  QVeris 备用源失败: {fallback_e}")
                        df = pd.DataFrame()

                # ---- 空数据检查 ----
                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    reason = (f"代码 {stock_code} 在 {start_date}~{end_date} "
                              f"返回空数据（可能原因：API变更/无交易/新股未上市）")
                    self._progress(f"⚠ {reason}")
                    self.db.log_sync(
                        task_type='download_history',
                        stock_code=stock_code,
                        date_range_start=start_date,
                        date_range_end=end_date,
                        status='empty',
                        message=reason,
                    )
                    return False, 0, reason

                # 过滤日期
                if 'trade_date' in df.columns:
                    df = df[df['trade_date'] <= end_date]

                # 写入数据库
                saved = self.db.save_daily_hfq(df, stock_code)

                # CSV 导出
                if csv_path:
                    os.makedirs(csv_path, exist_ok=True)
                    fpath = os.path.join(csv_path, f"{stock_code}.csv")
                    df.to_csv(fpath, index=False, encoding='utf-8-sig')

                # 验证
                info = self.db.verify_stock_data(stock_code)
                verify_msg = (f"代码 {stock_code} 已入库 {info['count']} 条记录，"
                              f"覆盖范围 {info['min_date']}~{info['max_date']}")

                self.db.log_sync(
                    task_type='download_history',
                    stock_code=stock_code,
                    date_range_start=start_date,
                    date_range_end=end_date,
                    success_count=1,
                    total_records=saved,
                    status='success',
                    message=verify_msg,
                )
                return True, saved, verify_msg

            except Exception as e:
                if attempt < RETRY_COUNT:
                    self._progress(f"⚠ {stock_code} 第{attempt}次失败: {e}")
                    self._sleep_before_retry(attempt)
                else:
                    error_msg = f"{stock_code} 下载失败（已重试{RETRY_COUNT}次）: {e}"
                    self._progress(f"✗ {error_msg}")
                    self.db.log_sync(
                        task_type='download_history',
                        stock_code=stock_code,
                        date_range_start=start_date,
                        date_range_end=end_date,
                        fail_count=1,
                        status='failed',
                        message=error_msg,
                    )
                    return False, 0, error_msg

        return False, 0, "未知错误"

    # ==========================================================
    # C. 批量下载（分批容错）
    # ==========================================================
    def download_batch(self, stock_codes, start_date, end_date=None,
                       delay=None, csv_path=None):
        """
        批量下载，按 BATCH_SIZE 分批。
        返回 {'total', 'success', 'failed', 'records', 'errors': [...]}
        """
        delay = delay if delay is not None else DOWNLOAD_DELAY
        total = len(stock_codes)
        success_count = 0
        failed_count = 0
        total_records = 0
        errors = []

        self._progress(f"开始批量下载 {total} 只股票 "
                       f"(批次大小={BATCH_SIZE}, 间隔={delay}s)...")

        for i, code in enumerate(stock_codes, 1):
            if self.stop_flag.is_set():
                self._progress("⛔ 下载已取消")
                break

            pct = i / total
            self._progress(f"[{i}/{total}] 正在下载 {code} ...", pct)

            ok, records, msg = self.download_stock_history(
                code, start_date, end_date, csv_path=csv_path,
            )

            if ok:
                success_count += 1
                total_records += records
                self._progress(f"✓ {code}: {records} 条")
            else:
                failed_count += 1
                errors.append({'stock_code': code, 'message': msg})
                self._progress(f"✗ {code}: {msg}")

            # 批间暂停
            if i % BATCH_SIZE == 0 and i < total:
                pause = delay * 5
                self._progress(
                    f"--- 已完成 {i}/{total}，暂停 {pause:.0f}s ---")
                time.sleep(pause)
            elif delay > 0:
                time.sleep(delay)

        result = {
            'total': total,
            'success': success_count,
            'failed': failed_count,
            'records': total_records,
            'errors': errors,
        }

        self._progress(
            f"批量下载完成: 成功 {success_count}, 失败 {failed_count}, "
            f"总计 {total_records} 条记录")

        # 汇总日志
        self.db.log_sync(
            task_type='batch_download',
            date_range_start=start_date,
            date_range_end=end_date or datetime.now().strftime('%Y-%m-%d'),
            success_count=success_count,
            fail_count=failed_count,
            total_records=total_records,
            status='success' if failed_count == 0 else 'partial',
            message=f"总{total} 成功{success_count} 失败{failed_count}",
        )

        return result

    # ==========================================================
    # D. 增量更新
    # ==========================================================
    def update_incremental(self, stock_codes=None):
        """
        增量更新：仅抓取每只股票最后交易日+1 到今天的数据。
        """
        if stock_codes is None:
            stock_codes = self.db.get_downloaded_stocks()

        if not stock_codes:
            self._progress("没有需要更新的股票")
            return {'updated': 0, 'skipped': 0, 'failed': 0}

        today = datetime.now().strftime('%Y-%m-%d')
        self._progress(f"增量更新 {len(stock_codes)} 只股票 → {today}")

        updated = 0
        skipped = 0
        failed = 0

        for i, code in enumerate(stock_codes, 1):
            if self.stop_flag.is_set():
                break

            pct = i / len(stock_codes)
            last_date = self.db.get_last_trade_date(code)

            if last_date and last_date >= today:
                skipped += 1
                continue

            # 从最后日期开始下载（包含当天以处理盘中更新）
            start = last_date if last_date else '2015-01-01'

            self._progress(f"[{i}/{len(stock_codes)}] {code}: {start} → {today}", pct)

            ok, records, msg = self.download_stock_history(code, start, today)

            if ok and records > 0:
                updated += 1
            elif ok:
                skipped += 1
            else:
                failed += 1

            time.sleep(DOWNLOAD_DELAY)

        result = {'updated': updated, 'skipped': skipped, 'failed': failed}
        self._progress(
            f"增量更新完成: 更新 {updated}, 跳过 {skipped}, 失败 {failed}")

        self.db.log_sync(
            task_type='incremental_update',
            success_count=updated,
            fail_count=failed,
            status='success' if failed == 0 else 'partial',
            message=f"更新{updated} 跳过{skipped} 失败{failed}",
        )
        return result

    # 兼容旧调用
    def update_daily(self, stock_codes=None):
        return self.update_incremental(stock_codes)

    # ==========================================================
    # 按年分批（超长周期）
    # ==========================================================
    def download_by_year(self, stock_codes, years=None, delay=None,
                         csv_path=None):
        years = years or DEFAULT_YEARS
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years * 365)
        return self.download_batch(
            stock_codes,
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d'),
            delay=delay,
            csv_path=csv_path,
        )

    # ==========================================================
    # 概念板块
    # ==========================================================
    def fetch_concept_list(self):
        self._progress("正在获取概念板块列表...")
        # 注意：同花顺接口同时返回 index_code(8 开头指数) 与 concept_code(3 开头概念)，
        # 不能把 index_code 重命名为 concept_code，否则会出现两列同名，pandas 取列得到 DataFrame 而非 Series。
        rename_map = {
            'code': 'concept_code',
            '概念代码': 'concept_code',
            '板块代码': 'concept_code',
            'name': 'concept_name',
            '概念名称': 'concept_name',
            '板块名称': 'concept_name',
        }
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                df = adata.stock.info.all_concept_code_ths()
                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    raise ValueError('概念板块返回空数据')
                df = df.rename(columns=rename_map)
                self._progress(f"✓ 获取概念板块: {len(df)} 个")
                return df
            except Exception as e:
                self._progress(f"⚠ 获取概念板块第{attempt}次失败: {e}")
                if attempt < RETRY_COUNT:
                    self._sleep_before_retry(attempt)
        self._progress("✗ 获取概念板块失败")
        return pd.DataFrame()

    @staticmethod
    def _sanitize_concept_field(v):
        """
        从 DataFrame 单元格 / itertuples 取值时过滤 NaN。
        注意：float('nan') 在 Python 里是「真值」，不能写 `x or y` 否则会卡在 nan。
        """
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except TypeError:
            pass
        s = str(v).strip()
        if not s or s.lower() == 'nan':
            return None
        return s

    def _ths_concept_constituent_attempts(self, concept_code=None, concept_name=None,
                                          index_code=None):
        """
        构造同花顺成分股请求的参数列表（按顺序尝试）。
        仅当 6 位数字且以 3/非 8 开头等合理时走 concept_code；8 开头走 index_code；
        否则走 name，避免把中文名误传给 concept_code 参数。
        """
        code = self._sanitize_concept_field(concept_code)
        name = self._sanitize_concept_field(concept_name)
        idx = self._sanitize_concept_field(index_code)
        attempts = []

        if code and code.isdigit() and len(code) == 6:
            if code.startswith('8'):
                attempts.append({'index_code': code})
            else:
                attempts.append({'concept_code': code})
        if name:
            attempts.append({'name': name})
        if code and not (code.isdigit() and len(code) == 6):
            attempts.append({'name': code})
        if idx and idx.isdigit():
            kw = {'index_code': idx}
            if kw not in attempts:
                attempts.append(kw)

        # 去重（dict 不可哈希，用 frozenset items）
        seen = set()
        out = []
        for kw in attempts:
            sig = tuple(sorted(kw.items()))
            if sig not in seen:
                seen.add(sig)
                out.append(kw)
        return out

    def fetch_concept_stocks(self, concept_code=None, concept_name=None,
                             index_code=None):
        """
        拉取概念成分股。可传概念代码、名称或指数代码（同花顺 8 开头）。
        """
        code = self._sanitize_concept_field(concept_code)
        name = self._sanitize_concept_field(concept_name)
        idx = self._sanitize_concept_field(index_code)
        label = code or name or idx or '?'
        self._progress(f"正在获取概念 {label} 的成分股...")

        attempts = self._ths_concept_constituent_attempts(code, name, idx)

        if attempts:
            for attempt in range(1, RETRY_COUNT + 1):
                for kw in attempts:
                    try:
                        df = adata.stock.info.concept_constituent_ths(
                            wait_time=1, **kw)
                        if isinstance(df, pd.DataFrame) and len(df) > 0:
                            df = df.rename(columns={
                                'code': 'stock_code',
                                '代码': 'stock_code',
                                'name': 'stock_name',
                                '名称': 'stock_name',
                            })
                            self._progress(f"✓ 成分股: {len(df)} 只")
                            return df
                    except Exception as e:
                        self._progress(f"  THS {kw} 第{attempt}次失败: {e}")
                if attempt < RETRY_COUNT:
                    self._sleep_before_retry(attempt)
        else:
            self._progress("  跳过 THS：无有效概念代码/名称/指数代码")

        qkey = code if code and code.isdigit() else (name or code or idx)
        if not qkey:
            return pd.DataFrame()
        try:
            df = self._fetch_concept_stocks_qveris(qkey)
            if isinstance(df, pd.DataFrame) and not df.empty:
                self._progress(f"✓ QVeris 成分股: {len(df)} 只")
                return df
        except Exception as e:
            self._progress(f"  QVeris 方式失败: {e}")

        return pd.DataFrame()

    def sync_concept_boards(self, sync_constituents=False, limit=None):
        """
        同步概念板块列表，可选同步成分股。
        返回 {'concepts', 'constituents', 'failed_constituents'}。
        """
        df = self.fetch_concept_list()
        if df.empty:
            self.db.log_sync(
                task_type='sync_concept_board',
                status='failed',
                message='概念板块列表为空',
            )
            return {'concepts': 0, 'constituents': 0, 'failed_constituents': 0}

        saved = self.db.save_concept_boards(df)
        total_constituents = 0
        failed_constituents = 0

        # 成分股同步用入库后的列表：库内 concept_code 已 fillna 名称，且无 NaN；
        # 若用原始 merge 结果，itertuples 里 float('nan') 会令 `nan or name` 仍为 nan。
        if sync_constituents:
            work_df = self.db.get_concept_boards(
                limit=int(limit) if limit else None)
            if work_df.empty:
                self._progress("⚠ 概念表为空，跳过成分股同步")
            total = len(work_df)
            for i, row in enumerate(work_df.itertuples(index=False), 1):
                cc = self._sanitize_concept_field(getattr(row, 'concept_code', None))
                cn = self._sanitize_concept_field(getattr(row, 'concept_name', None))
                pct = i / total if total else None
                disp = cc or cn or '?'
                self._progress(f"[{i}/{total}] 同步概念成分股: {disp}", pct)
                cons_df = self.fetch_concept_stocks(
                    concept_code=cc, concept_name=cn)
                if cons_df.empty:
                    failed_constituents += 1
                    continue
                # 与 concept_board 主键一致（cc 可能为数字代码，也可能入库时是名称）
                db_key = cc if cc is not None else cn
                total_constituents += self.db.replace_concept_constituents(
                    db_key, cons_df)
                time.sleep(DOWNLOAD_DELAY)

        self.db.log_sync(
            task_type='sync_concept_board',
            success_count=saved,
            fail_count=failed_constituents,
            total_records=total_constituents,
            status='success' if failed_constituents == 0 else 'partial',
            message=f"概念{saved}个, 成分股{total_constituents}条",
        )
        return {
            'concepts': saved,
            'constituents': total_constituents,
            'failed_constituents': failed_constituents,
        }

    # ==========================================================
    # 实时行情
    # ==========================================================
    def fetch_realtime_quotes(self, stock_codes):
        try:
            self._progress(f"获取 {len(stock_codes)} 只实时行情...")
            df = adata.stock.market.list_market_current(code_list=stock_codes)
            if df is not None and not df.empty:
                self._progress(f"✓ 实时行情: {len(df)} 只")
                return df
        except Exception as e:
            self._progress(f"✗ 实时行情失败: {e}")

        try:
            df = self.tencent.fetch_realtime_quotes(stock_codes)
            if df is not None and not df.empty:
                self._progress(f"✓ 腾讯免费实时行情: {len(df)} 只")
                return df
        except Exception as e:
            self._progress(f"✗ 腾讯免费实时行情失败: {e}")

        try:
            df = self._fetch_realtime_quotes_qveris(stock_codes)
            if df is not None and not df.empty:
                self._progress(f"✓ QVeris 实时行情: {len(df)} 只")
                return df
        except Exception as e:
            self._progress(f"✗ QVeris 实时行情失败: {e}")

        return pd.DataFrame()

    def download_realtime_quotes(self, stock_codes):
        """
        获取并保存实时行情。
        返回 {'total', 'saved', 'failed', 'message'}。
        """
        if not stock_codes:
            return {'total': 0, 'saved': 0, 'failed': 0, 'message': '未传入股票代码'}

        df = self.fetch_realtime_quotes(stock_codes)
        if df.empty:
            self.db.log_sync(
                task_type='download_realtime',
                fail_count=len(stock_codes),
                status='failed',
                message='实时行情为空',
            )
            return {
                'total': len(stock_codes),
                'saved': 0,
                'failed': len(stock_codes),
                'message': '实时行情为空',
            }

        saved = self.db.save_realtime_quotes(df)
        msg = f"实时行情已保存 {saved} 条"
        self.db.log_sync(
            task_type='download_realtime',
            success_count=saved,
            total_records=saved,
            status='success',
            message=msg,
        )
        return {
            'total': len(stock_codes),
            'saved': saved,
            'failed': max(len(stock_codes) - saved, 0),
            'message': msg,
        }

    # ==========================================================
    # 数据完整性检查
    # ==========================================================
    def check_data_integrity(self, stock_codes):
        results = []
        for code in stock_codes:
            info = self.db.verify_stock_data(code)
            info['status'] = '正常' if info['count'] > 0 else '无数据'
            results.append(info)
        return pd.DataFrame(results)

    # ==========================================================
    # 财务数据下载
    # ==========================================================
    def download_financial(self, stock_code):
        """
        下载单只股票的核心财务指标 (ak.stock_financial_abstract_ths)
        返回 (success, records, message)
        """
        if self.stop_flag.is_set():
            return False, 0, "用户取消"

        for attempt in range(1, RETRY_COUNT + 1):
            try:
                df = ak.stock_financial_abstract_ths(symbol=stock_code)

                if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                    reason = f"代码 {stock_code} 财务数据返回为空"
                    self._progress(f"⚠ {reason}")
                    self.db.log_sync(
                        task_type='download_financial',
                        stock_code=stock_code,
                        status='empty',
                        message=reason,
                    )
                    return False, 0, reason

                rename_cols = {
                    '报告期': 'report_date',
                    '净利润': 'net_profit_attr_sh',
                    '净利润同比增长率': 'net_profit_yoy_gr',
                    '营业总收入': 'total_rev',
                    '营业总收入同比增长率': 'total_rev_yoy_gr',
                    '基本每股收益': 'basic_eps',
                    '每股净资产': 'net_asset_ps',
                    '每股经营现金流': 'oper_cf_ps',
                    '销售毛利率': 'gross_margin',
                    '销售净利率': 'net_margin',
                    '净资产收益率': 'roe_wtd',
                    '资产负债率': 'asset_liab_ratio',
                    '流动比率': 'curr_ratio',
                    '速动比率': 'quick_ratio'
                }
                df = df.rename(columns=rename_cols)
                
                def parse_val(val):
                    if pd.isna(val) or val == 'False' or val is False:
                        return None
                    if isinstance(val, str):
                        v = val.strip()
                        if not v or v == '--': return None
                        if v.endswith('亿'): return float(v[:-1]) * 1e8
                        if v.endswith('万'): return float(v[:-1]) * 1e4
                        if v.endswith('%'): return float(v[:-1])
                    try: return float(val)
                    except: return None

                for col in rename_cols.values():
                    if col != 'report_date' and col in df.columns:
                        df[col] = df[col].apply(parse_val)

                def get_report_type(date_val):
                    try:
                        d = pd.to_datetime(date_val)
                        if d.month == 12: return '年报'
                        elif d.month == 9: return '三季报'
                        elif d.month == 6: return '中报'
                        elif d.month == 3: return '一季报'
                        return None
                    except: return None
                        
                if 'report_date' in df.columns:
                    df['report_type'] = df['report_date'].apply(get_report_type)

                saved = self.db.save_financial(df, stock_code)
                msg = f"代码 {stock_code} 财务数据已入库 {saved} 条"

                self.db.log_sync(
                    task_type='download_financial',
                    stock_code=stock_code,
                    success_count=1,
                    total_records=saved,
                    status='success',
                    message=msg,
                )
                return True, saved, msg

            except Exception as e:
                if attempt < RETRY_COUNT:
                    wait = RETRY_WAIT_BASE * (2 ** (attempt - 1))
                    self._progress(
                        f"⚠ {stock_code} 财务数据第{attempt}次失败: {e}，"
                        f"{wait:.0f}s 后重试...")
                    time.sleep(wait)
                else:
                    error_msg = f"{stock_code} 财务数据下载失败: {e}"
                    self._progress(f"✗ {error_msg}")
                    self.db.log_sync(
                        task_type='download_financial',
                        stock_code=stock_code,
                        fail_count=1,
                        status='failed',
                        message=error_msg,
                    )
                    return False, 0, error_msg

        return False, 0, "未知错误"

    def download_financial_batch(self, stock_codes, delay=None,
                                 parallel_workers=None):
        """
        批量下载财务数据。
        parallel_workers：覆盖 config.DOWNLOAD_PARALLEL_WORKERS；1 为串行。
        财务接口每次仍拉该股全部报告期，入库为 UPSERT（按 report_date 更新），非「只拉新报告期」。
        返回 {'total', 'success', 'failed', 'records', 'errors': [...]}
        """
        delay = delay if delay is not None else DOWNLOAD_DELAY
        workers = self._effective_parallel_workers(parallel_workers)
        total = len(stock_codes)
        success_count = 0
        failed_count = 0
        total_records = 0
        errors = []
        lock = threading.Lock()
        done = [0]

        self._progress(
            f"开始批量下载财务数据 {total} 只股票（并发 {workers}）..."
        )

        def run_one(code: str):
            if self.stop_flag.is_set():
                return code, False, 0, "已取消"
            ok, records, msg = self.download_financial(code)
            if delay > 0:
                time.sleep(delay)
            return code, ok, records, msg

        if workers <= 1:
            for i, code in enumerate(stock_codes, 1):
                if self.stop_flag.is_set():
                    self._progress("⛔ 下载已取消")
                    break
                pct = i / total
                self._progress(f"[{i}/{total}] 财务数据: {code} ...", pct)
                ok, records, msg = self.download_financial(code)
                if ok:
                    success_count += 1
                    total_records += records
                else:
                    failed_count += 1
                    errors.append({'stock_code': code, 'message': msg})
                if i % BATCH_SIZE == 0 and i < total:
                    pause = delay * 5
                    self._progress(f"--- 已完成 {i}/{total}，暂停 {pause:.0f}s ---")
                    time.sleep(pause)
                elif delay > 0:
                    time.sleep(delay)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(run_one, c): c for c in stock_codes}
                for fut in as_completed(futures):
                    if self.stop_flag.is_set():
                        break
                    code = futures[fut]
                    try:
                        rcode, ok, records, msg = fut.result()
                        code = rcode
                    except Exception as e:
                        ok, records, msg = False, 0, str(e)
                    with lock:
                        done[0] += 1
                        i = done[0]
                        if ok:
                            success_count += 1
                            total_records += records
                        else:
                            failed_count += 1
                            errors.append({'stock_code': code, 'message': msg})
                        self._progress(
                            f"[{i}/{total}] 财务数据: {code} "
                            f"{'✓' if ok else '✗'} {msg}",
                            i / total if total else None,
                        )
                        if i % BATCH_SIZE == 0 and i < total:
                            pause = delay * 5
                            self._progress(
                                f"--- 已完成 {i}/{total}，暂停 {pause:.0f}s ---"
                            )
                            time.sleep(pause)

        result = {
            'total': total,
            'success': success_count,
            'failed': failed_count,
            'records': total_records,
            'errors': errors,
        }

        self._progress(
            f"财务数据下载完成: 成功 {success_count}, 失败 {failed_count}, "
            f"总计 {total_records} 条记录")

        self.db.log_sync(
            task_type='batch_financial',
            success_count=success_count,
            fail_count=failed_count,
            total_records=total_records,
            status='success' if failed_count == 0 else 'partial',
            message=f"总{total} 成功{success_count} 失败{failed_count}",
        )
        return result

    # ==========================================================
    # 指数数据下载
    # ==========================================================

    # 常用A股指数代码与名称
    DEFAULT_INDICES = {
        '000001': '上证指数',
        '399001': '深证成指',
        '399006': '创业板指',
        '000300': '沪深300',
        '000905': '中证500',
        '000852': '中证1000',
        '000688': '科创50',
    }

    @staticmethod
    def _index_tencent_bar_count(start_date: str) -> int:
        """
        腾讯 K 线接口按「根数」向前取日线；根据起始日估算条数（略大于交易日数）。
        过小会导致 2015 年起的数据截断；过大若接口拒收再靠下限保护。
        """
        try:
            s = datetime.strptime((start_date or '2015-01-01')[:10], '%Y-%m-%d')
        except ValueError:
            s = datetime(2015, 1, 1)
        calendar_days = max(0, (datetime.now() - s).days)
        # 自然日 * 0.75 近似交易日，再加缓冲
        est = int(calendar_days * 0.75) + 80
        return max(256, min(est, 4000))

    def download_index(self, index_code, start_date='2015-01-01',
                       index_name=None, incremental=True):
        """
        下载单个指数日线：优先 AkShare；若抛错/空数据则依次尝试腾讯、QVeris。
        incremental=True（默认）：若库中已有该指数，则从「最后交易日+1」起只拉增量；
        incremental=False：始终从 start_date 全量请求（入库仍为 UPSERT，可修正历史）。
        返回 (success, records, message)
        """
        if self.stop_flag.is_set():
            return False, 0, "用户取消"

        if index_name is None:
            index_name = self.DEFAULT_INDICES.get(index_code, index_code)

        end_str = datetime.now().strftime('%Y-%m-%d')
        user_start = (start_date or '2015-01-01')[:10]
        eff_start = user_start

        # 增量：用库中最新交易日缩小请求区间，减少流量、降低被限流概率
        if incremental:
            try:
                last = self.db.get_last_index_date(index_code)
            except Exception:
                last = None
            if last:
                try:
                    nxt = (
                        datetime.strptime(str(last)[:10], '%Y-%m-%d')
                        + timedelta(days=1)
                    ).strftime('%Y-%m-%d')
                    eff_start = max(user_start, nxt)
                    self._progress(
                        f"指数 {index_code} 增量起始 {eff_start}（库中最新 {last}）"
                    )
                except ValueError:
                    pass

        if eff_start > end_str:
            self._progress(
                f"✓ 指数 {index_code}({index_name}) 已最新，无需下载（截至 {end_str}）"
            )
            return True, 0, "已是最新"

        start_date_ak = eff_start.replace('-', '')
        tencent_count = self._index_tencent_bar_count(eff_start)

        rename_cols = {
            '日期': 'trade_date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'change_pct',
            '涨跌额': 'change_amount',
        }

        for attempt in range(1, RETRY_COUNT + 1):
            df = pd.DataFrame()

            # 1) AkShare：服务端常主动断连，异常时视为失败并降级，不要整轮只重试 AkShare
            try:
                df = ak.index_zh_a_hist(
                    symbol=index_code,
                    period="daily",
                    start_date=start_date_ak,
                )
            except Exception as e:
                self._progress(
                    f"⚠ 指数 {index_code} AkShare 异常（将改用腾讯/QVeris）: {e}"
                )
                df = pd.DataFrame()

            if df is None:
                df = pd.DataFrame()

            if df.empty:
                self._progress(f"⚠ 指数 {index_code} AkShare 无数据，尝试腾讯免费源")
                df = self.tencent.fetch_daily_history(
                    stock_code=index_code,
                    start_date=eff_start,
                    end_date=end_str,
                    count=tencent_count,
                    is_index=True,
                )

            if df is None or df.empty:
                self._progress(f"⚠ 指数 {index_code} 腾讯源无数据，尝试 QVeris 备用源")
                df = self._fetch_index_qveris(
                    index_code=index_code,
                    index_name=index_name,
                    start_date=eff_start,
                    end_date=end_str,
                )

            if df is None:
                df = pd.DataFrame()

            try:
                if df.empty:
                    reason = f"指数 {index_code}({index_name}) 三源均无数据"
                    if attempt < RETRY_COUNT:
                        wait = RETRY_WAIT_BASE * (2 ** (attempt - 1))
                        self._progress(
                            f"⚠ {reason}，{wait:.0f}s 后重试 ({attempt}/{RETRY_COUNT})..."
                        )
                        time.sleep(wait)
                        continue

                    self._progress(f"⚠ {reason}")
                    self.db.log_sync(
                        task_type='download_index',
                        stock_code=index_code,
                        status='empty',
                        message=reason,
                    )
                    return False, 0, reason

                df = df.rename(columns=rename_cols)

                saved = self.db.save_index_daily(df, index_code, index_name)
                msg = f"指数 {index_code}({index_name}) 已入库 {saved} 条"

                self.db.log_sync(
                    task_type='download_index',
                    stock_code=index_code,
                    success_count=1,
                    total_records=saved,
                    status='success',
                    message=msg,
                )
                return True, saved, msg

            except Exception as e:
                if attempt < RETRY_COUNT:
                    wait = RETRY_WAIT_BASE * (2 ** (attempt - 1))
                    self._progress(
                        f"⚠ 指数 {index_code} 第{attempt}次处理失败: {e}，"
                        f"{wait:.0f}s 后重试..."
                    )
                    time.sleep(wait)
                else:
                    error_msg = f"指数 {index_code} 下载失败: {e}"
                    self._progress(f"✗ {error_msg}")
                    self.db.log_sync(
                        task_type='download_index',
                        stock_code=index_code,
                        fail_count=1,
                        status='failed',
                        message=error_msg,
                    )
                    return False, 0, error_msg

        return False, 0, "未知错误"

    def download_all_indices(self, start_date='2015-01-01',
                             extra_indices=None, incremental=True,
                             parallel_workers=None):
        """
        下载所有常用指数行情。
        incremental：见 download_index。
        parallel_workers：覆盖 config；1 为逐个下载。
        """
        indices = dict(self.DEFAULT_INDICES)
        if extra_indices:
            indices.update(extra_indices)

        total = len(indices)
        success_count = 0
        failed_count = 0
        workers = self._effective_parallel_workers(parallel_workers)
        items = list(indices.items())
        lock = threading.Lock()
        done = [0]

        self._progress(
            f"开始下载 {total} 个指数行情（并发 {workers}，增量={incremental}）..."
        )

        def run_index(pair):
            code, name = pair
            if self.stop_flag.is_set():
                return code, name, False, 0, "取消"
            ok, records, msg = self.download_index(
                code, start_date, name, incremental=incremental)
            time.sleep(DOWNLOAD_DELAY)
            return code, name, ok, records, msg

        if workers <= 1:
            for i, (code, name) in enumerate(items, 1):
                if self.stop_flag.is_set():
                    break
                pct = i / total
                self._progress(f"[{i}/{total}] 指数: {code} ({name}) ...", pct)
                ok, records, msg = self.download_index(
                    code, start_date, name, incremental=incremental)
                if ok:
                    success_count += 1
                else:
                    failed_count += 1
                time.sleep(DOWNLOAD_DELAY)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(run_index, p): p for p in items}
                for fut in as_completed(futs):
                    if self.stop_flag.is_set():
                        break
                    pair = futs[fut]
                    try:
                        code, name, ok, records, msg = fut.result()
                    except Exception as e:
                        code, name = pair[0], pair[1]
                        ok, records, msg = False, 0, str(e)
                    with lock:
                        done[0] += 1
                        i = done[0]
                        if ok:
                            success_count += 1
                        else:
                            failed_count += 1
                        self._progress(
                            f"[{i}/{total}] 指数: {code} ({name}) "
                            f"{'✓' if ok else '✗'} {msg}",
                            i / total if total else None,
                        )

        self._progress(
            f"指数下载完成: 成功 {success_count}, 失败 {failed_count}")

        self.db.log_sync(
            task_type='batch_index',
            success_count=success_count,
            fail_count=failed_count,
            status='success' if failed_count == 0 else 'partial',
            message=f"总{total} 成功{success_count} 失败{failed_count}",
        )
        return {'total': total, 'success': success_count, 'failed': failed_count}

    # ---------- stop ----------
    def stop(self):
        self.stop_flag.set()
        self._progress("正在停止下载...")

    def reset_stop(self):
        self.stop_flag.clear()
