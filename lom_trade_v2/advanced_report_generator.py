#!/usr/bin/env python3
"""
LOM Trade System v2 — 高级报告生成器
"""

from sentiment_scanner import SentimentScanner
from sector_rotation import SectorRotation
from sector_stock_picker import SectorStockPicker
from factor_exposure import FactorExposureAnalyzer
from executive_summary import ExecutiveSummary
import pandas as pd
from datetime import datetime


class AdvancedReportGenerator:
    """高级投资分析报告生成器"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path
        self.sentiment = SentimentScanner(db_path)
        self.rotation = SectorRotation(db_path)
        self.picker = SectorStockPicker(db_path)
        self.factor = FactorExposureAnalyzer(db_path)
        self.summary = ExecutiveSummary(db_path)
    
    def generate_report(self, date=None, output_path='./reports'):
        """
        生成完整投资分析报告
        """
        if date is None:
            date = self.sentiment._get_latest_date()
        
        import os
        os.makedirs(output_path, exist_ok=True)
        
        # 1. 市场情绪扫描
        sentiment_result = self.sentiment.scan_market_sentiment(date)
        
        # 2. 板块轮动分析
        rotation_df = self.rotation.analyze_sector_rotation(date)
        
        # 3. 热点板块
        hot_sectors = self.rotation.get_hot_sectors(date, top_n=10)
        
        # 4. 热点板块内选股
        stock_picks = self.picker.pick_stocks_in_sectors(hot_sectors, date, top_n=20)
        
        # 5. 生成 Executive Summary
        exec_summary = self.summary.generate_summary(date, stock_picks)

        # 6. 因子暴露分析
        if stock_picks is not None and len(stock_picks) > 0:
            factor_df = self.factor.calculate_factor_exposure(
                stock_picks['stock_code'].tolist()[:10], date
            )
        else:
            factor_df = None

        # 7. 生成完整报告
        report = self._format_report(date, sentiment_result, rotation_df, stock_picks, factor_df, exec_summary)
        
        # 6. 保存
        report_file = os.path.join(output_path, f"daily_report_v2_{date}.md")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"Report saved: {report_file}")
        return report_file
    
    def _format_report(self, date, sentiment, rotation_df, stock_picks, factor_df=None, exec_summary=None):
        """格式化报告"""
        
        # Executive Summary 放在最前面
        report = exec_summary + "\n\n" if exec_summary else ""

        report += f"""# 📊 每日深度投资分析报告

**报告日期**: {date}  
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**分析层次**: 市场情绪 → 板块轮动 → 热点选股 → 个股深度 → 因子暴露  
**数据来源**: AData + akshare（A股全市场）

---

## 一、市场情绪扫描

"""
        
        if sentiment:
            report += f"""
**情绪评分**: {sentiment['score']}/100 （{sentiment['sentiment']}）

| 指标 | 数值 |
|------|------|
| 统计股票数 | {sentiment['total_stocks']} 只 |
| 上涨家数 | {sentiment['up_count']} ({sentiment['up_ratio']}%) |
| 下跌家数 | {sentiment['down_count']} |
| 涨停数 | {sentiment['limit_up']} |
| 跌停数 | {sentiment['limit_down']} |
| 今日成交额 | ¥{sentiment['today_amount']} 亿 |
| 5日均成交额 | ¥{sentiment['avg_amount']} 亿 |
| 成交额比值 | {sentiment['amount_ratio']} |
| 北向资金净流入 | ¥{sentiment['north_inflow']} 亿 |

**情绪解读**:
- 市场情绪处于 **{sentiment['sentiment']}** 区间
- {'资金活跃' if sentiment['amount_ratio'] > 1.0 else '资金相对平淡'}
- {'外资流入积极' if sentiment['north_inflow'] > 0 else '外资流出谨慎'}
"""
        else:
            report += "市场情绪数据暂不可用。\n"
        
        report += """

---

## 二、板块轮动分析

"""
        
        if rotation_df is not None and len(rotation_df) > 0:
            report += """
| 板块名称 | 今日排名 | 主力净流入(亿) | 涨跌幅 | 轮动阶段 | 趋势 | 推荐操作 |
|---------|---------|---------------|--------|---------|------|---------|
"""
            for _, row in rotation_df.head(20).iterrows():
                inflow = row['main_inflow'] / 1e8 if row['main_inflow'] else 0
                report += f"| {row['sector_name']} | {row['today_rank']} | ¥{inflow:.2f} | {row['change_pct']:+.2f}% | {row['stage']} | {row['trend']} | {row['action']} |\n"
            
            # 轮动结论
            hot_count = len(rotation_df[rotation_df['stage'].isin(['启动', '扩散', '高潮'])])
            report += f"""

**轮动结论**:
- 当前有 **{hot_count}** 个板块处于活跃状态（启动/扩散/高潮）
- 热点板块主要集中在：**{', '.join(rotation_df.head(5)['sector_name'].tolist())}**
- 建议关注处于 **启动/扩散** 阶段的板块，规避 **退潮** 阶段板块
"""
        else:
            report += "板块资金流向数据暂不可用。\n"
        
        report += """

---

## 三、热点板块个股推荐

"""
        
        if stock_picks is not None and len(stock_picks) > 0:
            report += f"""
基于 **{len(hot_sectors)}** 个热点板块，扫描了相关个股，综合技术面和基本面筛选出以下推荐：

| 排名 | 股票代码 | 收盘价 | 涨跌幅 | 综合评分 | 推荐买入区间 | 止损价 | 目标价 | 盈亏比 |
|------|---------|--------|--------|---------|-------------|--------|--------|--------|
"""
            for i, (_, row) in enumerate(stock_picks.head(20).iterrows(), 1):
                rr = row['risk_reward']
                rr_str = f"{rr:.2f}" if pd.notna(rr) else "N/A"
                report += f"| {i} | {row['stock_code']} | ¥{row['close']:.2f} | {row['change_pct']:+.2f}% | {row['total_score']:.1f} | ¥{row['buy_low']:.2f}~¥{row['buy_high']:.2f} | ¥{row['stop_loss']:.2f} | ¥{row['target']:.2f} | {rr_str} |\n"
            
            report += """

---

## 四、重点个股深度分析

"""
            for i, (_, row) in enumerate(stock_picks.head(10).iterrows(), 1):
                loss_pct = (row['stop_loss']/row['buy_high'] - 1)*100 if row['buy_high'] > 0 else 0
                gain_pct = (row['target']/row['buy_high'] - 1)*100 if row['buy_high'] > 0 else 0
                
                report += f"""### {i}. {row['stock_code']}

| 维度 | 指标 | 数值 |
|------|------|------|
| **价格** | 当前价格 | ¥{row['close']:.2f} |
| | 推荐买入 | ¥{row['buy_low']:.2f} ~ ¥{row['buy_high']:.2f} |
| | 止损价格 | ¥{row['stop_loss']:.2f}（亏损约 {loss_pct:.1f}%） |
| | 目标价格 | ¥{row['target']:.2f}（盈利约 {gain_pct:.1f}%） |
| **技术** | 涨跌幅 | {row['change_pct']:+.2f}% |
| | RSI(14) | {row.get('rsi', 'N/A'):.1f if pd.notna(row.get('rsi')) else 'N/A'} |
| | 量比 | {row.get('vol_ratio', 'N/A'):.2f if pd.notna(row.get('vol_ratio')) else 'N/A'} |
| | MACD柱状图 | {row.get('macd_hist', 'N/A'):.3f if pd.notna(row.get('macd_hist')) else 'N/A'} |
| **基本面** | ROE | {row.get('roe', 'N/A'):.1f if pd.notna(row.get('roe')) else 'N/A'}% |
| | 资产负债率 | {row.get('debt_ratio', 'N/A'):.1f if pd.notna(row.get('debt_ratio')) else 'N/A'}% |
| | 营收同比 | {row.get('revenue_yoy', 'N/A'):.1f if pd.notna(row.get('revenue_yoy')) else 'N/A'}% |
| **评分** | 技术面 | {row.get('tech_score', 0):.1f}/100 |
| | 基本面 | {row.get('fund_score', 0):.1f}/100 |
| | 综合 | {row.get('total_score', 0):.1f}/100 |

**买入原因**:
"""
                reasons = []
                if row.get('rsi', 50) < 35:
                    reasons.append("RSI处于超卖区间，存在反弹机会")
                if row.get('macd_hist', 0) > 0:
                    reasons.append("MACD柱状图向上，短期动量积极")
                if row.get('vol_ratio', 1) > 1.5:
                    reasons.append("成交量放大，资金关注度高")
                if row.get('roe', 0) > 10:
                    reasons.append(f"ROE {row['roe']:.1f}%，盈利能力较强")
                if row.get('change_pct', 0) > 3:
                    reasons.append("当日涨幅明显，资金推动力强")
                
                if not reasons:
                    reasons.append("综合技术面和基本面评分较高")
                
                for r in reasons:
                    report += f"- {r}\n"
                
                report += "\n---\n\n"
        else:
            report += "个股推荐数据暂不可用。\n"
        
        report += """
## 五、策略说明与风险提示

### 选股策略
| 策略 | 核心逻辑 | 适用场景 |
|------|---------|---------|
| 趋势突破 | 均线多头 + MACD向上 + 放量 | 市场趋势明确 |
| 超跌反弹 | RSI超卖 + 接近布林带下轨 | 下跌后的反弹 |
| 量价配合 | 量比放大 + 涨幅明显 + 站上MA20 | 突破确认 |
| 基本面筛选 | ROE>0 + 净利润>0 + 负债率合理 | 中长期安全 |

### 风险提示
⚠️ **本报告仅供学习研究使用，不构成任何投资建议。**

1. 所有推荐均为算法自动生成，不代表真实走势
2. 股市有风险，投资需谨慎
3. 建议结合自身风险承受能力做出投资决策
4. 报告基于历史数据，未来表现可能不同
5. 板块轮动分析受数据时效性影响，非交易日可能不准确

---

*报告由 LOM Trade System v2 自动生成*  
*数据来源: AData SDK + akshare + 本地数据库*
"""
        
        return report


if __name__ == '__main__':
    gen = AdvancedReportGenerator()
    report_file = gen.generate_report()
    print(f"Generated: {report_file}")
