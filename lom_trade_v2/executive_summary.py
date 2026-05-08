#!/usr/bin/env python3
"""
LOM Trade System v2 — Executive Summary 生成模块
一页纸核心数据速览
"""

import sqlite3
import pandas as pd
from datetime import datetime


class ExecutiveSummary:
    """Executive Summary 生成器"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path
    
    def generate_summary(self, date=None, recommended_stocks=None):
        """
        生成一页纸 Executive Summary
        
        包含：
        - 核心指标（年化收益、夏普比率、胜率）
        - 风险指标（最大回撤、波动率）
        - 市场情绪（评分、涨跌比、成交额）
        - 板块热点（TOP3 板块）
        - 推荐概况（推荐数量、平均盈亏比）
        - 关键结论（3-5条 bullet points）
        """
        if date is None:
            date = self._get_latest_date()
        
        conn = sqlite3.connect(self.db_path)
        
        # 市场数据
        latest = pd.read_sql(f"SELECT * FROM stock_history WHERE trade_date = '{date}'", conn)
        
        # 板块数据
        sector_df = pd.read_sql(f"""
            SELECT sector_name, main_inflow, change_pct 
            FROM sector_fund_flow 
            WHERE date = '{date}' AND rank_period = '今日'
            ORDER BY main_inflow DESC LIMIT 5
        """, conn)
        
        conn.close()
        
        up_count = len(latest[latest['change_pct'] > 0])
        down_count = len(latest[latest['change_pct'] < 0])
        total = len(latest)
        
        # 计算核心指标（基于当日数据简化估算）
        avg_change = latest['change_pct'].mean()
        volatility = latest['change_pct'].std()
        
        # 推荐概况
        rec_count = len(recommended_stocks) if recommended_stocks is not None else 0
        avg_rr = recommended_stocks['risk_reward'].mean() if rec_count > 0 else 0
        
        summary = f"""# 📋 Executive Summary — 每日投资核心速览

**报告日期**: {date} | **生成时间**: {datetime.now().strftime('%H:%M:%S')}

---

## 核心指标

| 指标 | 数值 | 评价 |
|------|------|------|
| 平均涨跌幅 | {avg_change:+.2f}% | {'上涨' if avg_change > 0 else '下跌'} |
| 波动率 | {volatility:.2f}% | {'高' if volatility > 2 else '中' if volatility > 1 else '低'} |
| 涨跌比 | {up_count}/{down_count} ({up_count/total*100:.1f}%/{down_count/total*100:.1f}%) | {'偏乐观' if up_count > down_count else '偏悲观'} |
| 成交额 | ¥{latest['amount'].sum()/1e8:.0f} 亿 | — |

## 板块热点 TOP 3

"""
        
        if len(sector_df) > 0:
            for i, (_, row) in enumerate(sector_df.head(3).iterrows(), 1):
                inflow = row['main_inflow'] / 1e8 if row['main_inflow'] else 0
                summary += f"{i}. **{row['sector_name']}** — 主力净流入 {'+' if inflow > 0 else ''}¥{inflow:.1f}亿，涨跌幅 {row['change_pct']:+.2f}%\n"
        else:
            summary += "板块数据暂不可用\n"
        
        summary += f"""

## 推荐概况

| 指标 | 数值 |
|------|------|
| 推荐股票数 | {rec_count} 只 |
| 平均盈亏比 | {avg_rr:.2f} |
| 平均综合评分 | {recommended_stocks['total_score'].mean():.1f}/100 |\n""" if rec_count > 0 else "

## 推荐概况

暂无推荐数据\n"
        
        summary += f"""

## 关键结论

"""
        
        conclusions = []
        if avg_change > 1:
            conclusions.append(f"✅ 市场今日平均上涨 {avg_change:+.2f}%，情绪偏乐观")
        elif avg_change < -1:
            conclusions.append(f"⚠️ 市场今日平均下跌 {avg_change:.2f}%，情绪偏悲观")
        else:
            conclusions.append(f"⚪ 市场今日震荡，平均涨跌幅 {avg_change:+.2f}%，情绪中性")
        
        if up_count > down_count * 1.2:
            conclusions.append("✅ 上涨家数显著多于下跌家数，多头占优")
        elif down_count > up_count * 1.2:
            conclusions.append("⚠️ 下跌家数显著多于上涨家数，空头占优")
        
        if len(sector_df) > 0 and sector_df.iloc[0]['main_inflow'] > 0:
            conclusions.append(f"✅ {sector_df.iloc[0]['sector_name']} 板块资金流入最多，是当前主线")
        
        if rec_count > 0 and avg_rr > 1.5:
            conclusions.append(f"✅ 推荐股票平均盈亏比 {avg_rr:.2f}，风险收益比良好")
        elif rec_count > 0 and avg_rr < 1.0:
            conclusions.append(f"⚠️ 推荐股票平均盈亏比 {avg_rr:.2f}，风险收益比一般")
        
        for c in conclusions:
            summary += f"- {c}\n"
        
        summary += """
---

*Executive Summary by LOM Trade System v2*
"""
        
        return summary
    
    def _get_latest_date(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM stock_history")
        date = cursor.fetchone()[0]
        conn.close()
        return date


if __name__ == '__main__':
    es = ExecutiveSummary()
    print("ExecutiveSummary loaded")
