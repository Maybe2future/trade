#!/usr/bin/env python3
"""
LOM Trade System v2 — 因子暴露分析模块
基于 Fama-French 五因子模型 + 扩展因子
"""

import sqlite3
import pandas as pd
import numpy as np


class FactorExposureAnalyzer:
    """因子暴露分析器"""

    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path

    def calculate_factor_exposure(self, stock_codes, date=None):
        """
        计算股票的因子暴露

        因子定义：
        - 市值因子 (SMB): 大市值 vs 小市值 — 用总市值分位数
        - 价值因子 (HML): 成长型 vs 价值型 — 用 PE 倒数
        - 动量因子 (MOM): 正向动量 — 用 20 日收益率
        - 质量因子 (RMW): 盈利质量 — 用 ROE
        - 低波动 (BAB): 低波动优势 — 用 60 日波动率倒数
        - 市场因子 (MKT): Beta — 用 60 日 vs 指数相关性
        """
        if date is None:
            date = self._get_latest_date()

        conn = sqlite3.connect(self.db_path)

        # 获取股票数据
        placeholders = ','.join(['?' for _ in stock_codes])
        df = pd.read_sql(f"""
            SELECT * FROM stock_history 
            WHERE trade_date = '{date}' AND stock_code IN ({placeholders})
        """, conn, params=stock_codes)

        # 获取财务数据
        fin_df = pd.read_sql(f"""
            SELECT stock_code, roe, eps, debt_ratio, net_margin
            FROM stock_finance
            WHERE stock_code IN ({placeholders})
            AND report_period = (
                SELECT MAX(report_period) FROM stock_finance 
                WHERE stock_code IN ({placeholders})
            )
        """, conn, params=stock_codes + stock_codes)

        conn.close()

        if len(df) == 0:
            return pd.DataFrame()

        # 合并财务数据
        df = df.merge(fin_df, on='stock_code', how='left')

        # 计算各因子得分（标准化到 -1 ~ +1）

        # 1. 市值因子 SMB: 大市值为正，小市值为负
        # 用收盘价 * 总股本估算（这里简化用收盘价代替）
        df['smb'] = self._normalize(df['close'], inverse=True)  # 价格越高=市值越大=负暴露

        # 2. 价值因子 HML: 低PE为正（价值型），高PE为负（成长型）
        # 简化：用 1/close 作为估值代理（价格越低越价值）
        df['hml'] = self._normalize(1 / df['close'].replace(0, np.nan))

        # 3. 动量因子 MOM: 近期涨幅越大越好
        df['mom'] = self._normalize(df['change_pct'])

        # 4. 质量因子 RMW: ROE 越高越好
        df['rmw'] = self._normalize(df['roe'].fillna(0))

        # 5. 低波动 BAB: 波动率越低越好
        # 需要历史数据计算波动率，这里简化
        df['bab'] = self._normalize(df.get('volatility_60d', 20), inverse=True)

        # 6. 市场因子 MKT: Beta 代理
        df['mkt'] = self._normalize(df['change_pct'])  # 简化用当日涨幅

        return df[['stock_code', 'close', 'smb', 'hml', 'mom', 'rmw', 'bab', 'mkt']]

    def _normalize(self, series, inverse=False):
        """标准化到 -1 ~ +1"""
        s = pd.to_numeric(series, errors='coerce').fillna(0)
        min_val = s.min()
        max_val = s.max()
        if max_val == min_val:
            return pd.Series(0, index=s.index)
        normalized = 2 * (s - min_val) / (max_val - min_val) - 1
        if inverse:
            normalized = -normalized
        return normalized

    def _get_latest_date(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM stock_history")
        date = cursor.fetchone()[0]
        conn.close()
        return date


if __name__ == '__main__':
    analyzer = FactorExposureAnalyzer()
    print("FactorExposureAnalyzer loaded")
