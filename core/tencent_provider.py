# -*- coding: utf-8 -*-
"""
腾讯免费行情接口封装

优先使用 HTTP 端点，规避当前环境下部分 HTTPS 站点的 SSL EOF 问题。
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta

import pandas as pd

# 腾讯 fqkline 单次 count 超过约 2000 会返回 param error（data 变为 list）
TENCENT_FQKLINE_MAX_BARS = 2000


class TencentProvider:
    @staticmethod
    def _prefix_stock_code(stock_code: str, is_index=False):
        stock_code = str(stock_code).zfill(6)
        if is_index:
            if stock_code.startswith('399'):
                return f'sz{stock_code}'
            return f'sh{stock_code}'
        if stock_code.startswith(('5', '6', '9')):
            return f'sh{stock_code}'
        if stock_code.startswith(('0', '2', '3')):
            return f'sz{stock_code}'
        return stock_code

    def fetch_realtime_quotes(self, stock_codes):
        if not stock_codes:
            return pd.DataFrame()

        prefixed = [self._prefix_stock_code(code) for code in stock_codes]
        url = f"http://qt.gtimg.cn/q={','.join(prefixed)}"
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                text = resp.read().decode('gbk', errors='ignore')
        except Exception:
            return pd.DataFrame()

        rows = []
        for item in text.split(';'):
            parts = item.split('~')
            if len(parts) < 38:
                continue
            rows.append({
                'stock_code': parts[2],
                'short_name': parts[1],
                'price': parts[3],
                'change': parts[31],
                'change_pct': parts[32],
                'open': parts[5],
                'high': parts[33],
                'low': parts[34],
                'volume': str(int(float(parts[36])) * 100) if parts[36] else None,
                'amount': str(float(parts[37]) * 10000) if parts[37] else None,
            })

        return pd.DataFrame(rows)

    @staticmethod
    def _normalize_end_date_for_tencent(end_date: str) -> tuple[str, str]:
        """
        腾讯 fqkline 接口：param 里 end 若为 YYYYMMDD 常返回 param error，需使用 YYYY-MM-DD。
        返回 (URL 中的 end 段, 用于本地过滤的 YYYY-MM-DD)；无结束日则 ('', '')。
        """
        raw = (end_date or '').strip()
        if not raw:
            return '', ''
        if len(raw) == 10 and raw[4] == '-' and raw[7] == '-':
            return raw, raw
        if len(raw) == 8 and raw.isdigit():
            ymd = f'{raw[0:4]}-{raw[4:6]}-{raw[6:8]}'
            return ymd, ymd
        return raw[:10], raw[:10]

    def _fetch_fqkline_chunk(
        self,
        code: str,
        end_param: str,
        count: int,
    ) -> pd.DataFrame:
        """单次请求腾讯日 K；count 必须 ≤ TENCENT_FQKLINE_MAX_BARS。"""
        count = max(1, min(int(count), TENCENT_FQKLINE_MAX_BARS))
        url = (
            'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
            f'?param={code},day,,{end_param},{count},qfq'
        )
        try:
            with urllib.request.urlopen(url, timeout=25) as resp:
                payload = json.loads(resp.read().decode('utf-8', errors='ignore'))
        except Exception:
            return pd.DataFrame()

        data_obj = payload.get('data')
        if not isinstance(data_obj, dict):
            return pd.DataFrame()
        data = data_obj.get(code, {})
        # 指数多为 day；股票前复权多为 qfqday
        rows = data.get('qfqday') or data.get('day') or []
        if not rows:
            return pd.DataFrame()

        norm_rows = []
        for r in rows:
            if isinstance(r, (list, tuple)) and len(r) >= 6:
                norm_rows.append(list(r[:6]))

        df = pd.DataFrame(
            norm_rows, columns=['trade_date', 'open', 'close', 'high', 'low', 'volume']
        )
        for col in ['open', 'close', 'high', 'low', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    def fetch_daily_history(self, stock_code, start_date='', end_date='', count=640, is_index=False):
        """
        拉取日 K。若 count 较大，自动按 TENCENT_FQKLINE_MAX_BARS 分块向更早日期续拉，
        直到凑够根数或早于 start_date / 无新数据。
        """
        code = self._prefix_stock_code(stock_code, is_index=is_index)
        end_param, end_filter = self._normalize_end_date_for_tencent(end_date)
        target_bars = max(1, int(count))
        parts: list[pd.DataFrame] = []
        fetched = 0
        # 第一段的结束锚点：空字符串表示「最新」
        anchor = end_param
        max_rounds = 30
        last_oldest = None

        for _ in range(max_rounds):
            need = min(target_bars - fetched, TENCENT_FQKLINE_MAX_BARS)
            if need <= 0:
                break
            chunk = self._fetch_fqkline_chunk(code, anchor, need)
            if chunk.empty:
                break
            oldest = str(chunk['trade_date'].min())
            # 防止接口重复返回同一段导致死循环
            if last_oldest is not None and oldest == last_oldest:
                break
            last_oldest = oldest
            parts.append(chunk)
            fetched += len(chunk)
            if fetched >= target_bars:
                break
            # 下一段：以本段最早交易日的前一天为锚，向更久历史延伸
            try:
                d0 = datetime.strptime(oldest[:10], '%Y-%m-%d')
                anchor = (d0 - timedelta(days=1)).strftime('%Y-%m-%d')
            except ValueError:
                break
            if start_date and oldest[:10] <= start_date[:10]:
                break
            time.sleep(0.15)

        if not parts:
            return pd.DataFrame()

        df = pd.concat(parts, ignore_index=True)
        df = df.drop_duplicates(subset=['trade_date'], keep='first')
        df = df.sort_values('trade_date').reset_index(drop=True)

        if start_date:
            df = df[df['trade_date'] >= start_date]
        if end_filter:
            df = df[df['trade_date'] <= end_filter]

        if df.empty:
            return df

        df['pre_close'] = df['close'].shift(1)
        df['change_amount'] = df['close'] - df['pre_close']
        df['change_pct'] = (df['change_amount'] / df['pre_close'] * 100).round(4)
        return df
