#!/usr/bin/env python3
"""
LOM Trade System v2 — 热点板块内选股 + 基本面筛选
"""

import sqlite3
import pandas as pd
import numpy as np


class SectorStockPicker:
    """热点板块内选股器"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path
    
    def pick_stocks_in_sectors(self, hot_sectors, date=None, top_n=20):
        """
        在热点板块内选股
        结合技术指标 + 基本面筛选
        """
        if date is None:
            date = self._get_latest_date()
        
        conn = sqlite3.connect(self.db_path)
        
        # 1. 获取所有股票的技术指标数据
        tech_df = pd.read_sql(f"""
            SELECT * FROM stock_history 
            WHERE trade_date = '{date}'
        """, conn)
        
        # 2. 获取股票-板块映射
        map_df = pd.read_sql("""
            SELECT stock_code, sector_name FROM stock_sector_map
        """, conn)
        
        conn.close()
        
        if len(tech_df) == 0 or len(hot_sectors) == 0:
            return pd.DataFrame()
        
        # 3. 筛选热点板块内的股票
        sector_stocks = map_df[map_df['sector_name'].isin(hot_sectors)]['stock_code'].unique()
        candidates = tech_df[tech_df['stock_code'].isin(sector_stocks)].copy()
        
        if len(candidates) == 0:
            return pd.DataFrame()
        
        # 4. 技术指标筛选（保持合理条件）
        mask = (
            (candidates['change_pct'] > 0) &  # 当日上涨
            (candidates['close'] > candidates.get('ma20', candidates['close'] * 0.9)) &  # 站上或接近MA20
            (candidates.get('vol_ratio', 1.0) > 1.0) &  # 有放量
            (candidates.get('rsi', 50) < 80) &  # RSI不过热
            (candidates.get('macd_hist', 0) > -0.5)  # MACD不过度 negative
        )
        filtered = candidates[mask].copy()
        
        if len(filtered) == 0:
            # 放宽条件再试一次
            mask_loose = (
                (candidates['change_pct'] > -2) &  # 不暴跌
                (candidates.get('vol_ratio', 1.0) > 0.8)  # 有交易活跃度
            )
            filtered = candidates[mask_loose].copy()
        
        # 5. 基本面筛选
        filtered = self._apply_fundamental_filter(filtered)
        
        # 6. 综合评分
        filtered['tech_score'] = self._calc_tech_score(filtered)
        filtered['fund_score'] = self._calc_fund_score(filtered)
        filtered['total_score'] = filtered['tech_score'] * 0.6 + filtered['fund_score'] * 0.4
        
        # 7. 排序取Top N
        result = filtered.sort_values('total_score', ascending=False).head(top_n)
        
        # 8. 计算买卖区间
        result['buy_low'] = result['close'] * 0.98
        result['buy_high'] = result['close'] * 1.02
        result['stop_loss'] = result['close'] - 2 * result.get('atr14', result['close'] * 0.02)
        result['target'] = result['close'] + 3 * result.get('atr14', result['close'] * 0.02)
        result['risk_reward'] = np.where(
            (result['buy_high'] - result['stop_loss']) > 0,
            (result['target'] - result['buy_high']) / (result['buy_high'] - result['stop_loss']),
            0
        )
        
        return result
    
    def _apply_fundamental_filter(self, df):
        """基本面筛选"""
        conn = sqlite3.connect(self.db_path)
        
        # 获取最新财务数据
        codes = df['stock_code'].tolist()
        if len(codes) == 0:
            conn.close()
            return df
        
        placeholders = ','.join(['?' for _ in codes])
        fin_df = pd.read_sql(f"""
            SELECT stock_code, roe, net_profit, debt_ratio, revenue_yoy
            FROM stock_finance 
            WHERE stock_code IN ({placeholders})
            AND report_period = (
                SELECT MAX(report_period) FROM stock_finance 
                WHERE stock_code IN ({placeholders})
            )
        """, conn, params=codes + codes)
        
        conn.close()
        
        if len(fin_df) == 0:
            # 没有财务数据，给默认分数
            df['roe'] = 0
            df['debt_ratio'] = 100
            df['revenue_yoy'] = 0
            df['net_profit'] = 0
            return df
        
        # 合并财务数据
        df = df.merge(fin_df, on='stock_code', how='left')
        
        # 基本面筛选条件（宽松）
        # - ROE > 0（盈利）
        # - 净利润 > 0（不亏损）
        # - 资产负债率 < 100（不要求过低）
        basic_mask = (
            (df['roe'].fillna(0) > 0) |
            (df['net_profit'].fillna(0) > 0)
        )
        
        return df  # 不剔除，只给低分
    
    def _calc_tech_score(self, df):
        """技术面评分（0-100）"""
        score = 50.0
        
        # 涨跌幅加分
        score += df['change_pct'].clip(-5, 10) * 2
        
        # 量比加分
        vol_bonus = (df.get('vol_ratio', 1.0) - 1.0).clip(0, 3) * 10
        score += vol_bonus
        
        # RSI适中加分（40-60最佳）
        rsi = df.get('rsi', 50)
        rsi_bonus = 20 - abs(rsi - 50) * 0.5
        score += rsi_bonus
        
        # MACD加分
        macd = df.get('macd_hist', 0)
        score += macd.clip(-1, 2) * 10
        
        return score.clip(0, 100)
    
    def _calc_fund_score(self, df):
        """基本面评分（0-100）"""
        score = 50.0
        
        # ROE加分
        roe = df.get('roe', 0).fillna(0)
        score += roe.clip(0, 30) * 2
        
        # 净利润加分
        profit = df.get('net_profit', 0).fillna(0)
        score += np.where(profit > 0, 10, -10)
        
        # 负债率扣分（过高）
        debt = df.get('debt_ratio', 100).fillna(100)
        score -= (debt - 50).clip(0, 50) * 0.5
        
        # 营收增长加分
        revenue = df.get('revenue_yoy', 0).fillna(0)
        score += revenue.clip(-20, 50) * 0.3
        
        return score.clip(0, 100)
    
    def _get_latest_date(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM stock_history")
        date = cursor.fetchone()[0]
        conn.close()
        return date


if __name__ == '__main__':
    picker = SectorStockPicker()
    # 测试需要热点板块列表
    print("SectorStockPicker loaded")
