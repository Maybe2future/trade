#!/usr/bin/env python3
"""
LOM Trade System v2 — 市场情绪扫描模块
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta


class SentimentScanner:
    """市场情绪扫描器"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path
    
    def scan_market_sentiment(self, date=None):
        """
        扫描市场情绪
        返回情绪评分（0-100，50=中性）和详细指标
        """
        if date is None:
            date = self._get_latest_date()
        
        conn = sqlite3.connect(self.db_path)
        
        # 1. 涨跌家数统计
        latest = pd.read_sql(
            f"SELECT * FROM stock_history WHERE trade_date = '{date}'", 
            conn
        )
        
        if len(latest) == 0:
            conn.close()
            return None
        
        up_count = len(latest[latest['change_pct'] > 0])
        down_count = len(latest[latest['change_pct'] < 0])
        flat_count = len(latest[latest['change_pct'] == 0])
        total = len(latest)
        
        # 2. 涨跌停统计（按涨跌幅判断）
        limit_up = len(latest[latest['change_pct'] >= 9.9])  # 近似涨停
        limit_down = len(latest[latest['change_pct'] <= -9.9])  # 近似跌停
        
        # 3. 成交额变化（今日 vs 5日均值）
        avg_amount = self._get_avg_amount(conn, date)
        today_amount = latest['amount'].sum()
        amount_ratio = today_amount / avg_amount if avg_amount > 0 else 1.0
        
        # 4. 北向资金
        north_df = pd.read_sql(
            f"SELECT * FROM north_fund_flow WHERE date = '{date}'", 
            conn
        )
        north_inflow = north_df['net_inflow'].iloc[0] if len(north_df) > 0 else 0
        
        conn.close()
        
        # 情绪评分算法
        # 基础分 50，根据多个指标调整
        score = 50.0
        
        # 涨跌比影响（-20 ~ +20）
        if total > 0:
            up_ratio = up_count / total
            score += (up_ratio - 0.5) * 40
        
        # 涨跌停影响（-10 ~ +10）
        if total > 0:
            limit_up_ratio = limit_up / total * 100
            limit_down_ratio = limit_down / total * 100
            score += (limit_up_ratio - limit_down_ratio) * 0.5
        
        # 成交额影响（-5 ~ +5）
        if amount_ratio > 1.2:
            score += 5
        elif amount_ratio < 0.8:
            score -= 5
        
        # 北向资金影响（-5 ~ +5）
        if north_inflow > 50e8:  # 净流入50亿以上
            score += 5
        elif north_inflow < -50e8:  # 净流出50亿以上
            score -= 5
        
        score = max(0, min(100, score))
        
        # 情绪判断
        if score >= 75:
            sentiment = "乐观"
            color = "🟢"
        elif score >= 60:
            sentiment = "偏乐观"
            color = "🟡"
        elif score >= 45:
            sentiment = "中性"
            color = "⚪"
        elif score >= 30:
            sentiment = "偏悲观"
            color = "🟠"
        else:
            sentiment = "悲观"
            color = "🔴"
        
        return {
            'date': date,
            'score': round(score, 1),
            'sentiment': sentiment,
            'color': color,
            'up_count': up_count,
            'down_count': down_count,
            'flat_count': flat_count,
            'up_ratio': round(up_count/total*100, 1) if total > 0 else 0,
            'limit_up': limit_up,
            'limit_down': limit_down,
            'today_amount': round(today_amount/1e8, 2),  # 亿元
            'avg_amount': round(avg_amount/1e8, 2),
            'amount_ratio': round(amount_ratio, 2),
            'north_inflow': round(north_inflow/1e8, 2),  # 亿元
            'total_stocks': total
        }
    
    def _get_latest_date(self):
        """获取数据库最新日期"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM stock_history")
        date = cursor.fetchone()[0]
        conn.close()
        return date
    
    def _get_avg_amount(self, conn, date, days=5):
        """获取近N日平均成交额"""
        try:
            df = pd.read_sql(f"""
                SELECT trade_date, SUM(amount) as total_amount 
                FROM stock_history 
                WHERE trade_date <= '{date}' 
                GROUP BY trade_date 
                ORDER BY trade_date DESC 
                LIMIT {days}
            """, conn)
            return df['total_amount'].mean()
        except:
            return 0


if __name__ == '__main__':
    scanner = SentimentScanner()
    result = scanner.scan_market_sentiment()
    print(result)
