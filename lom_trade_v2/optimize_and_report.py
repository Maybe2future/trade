#!/usr/bin/env python3
"""
LOM Trade System — 完整数据增强 + 报告生成脚本
一次性完成：板块资金/财务数据/北向资金/板块映射/ATR计算/报告生成
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TradeSystemOptimizer:
    """完整优化器：数据增强 + 报告生成"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_tables()
    
    def _init_tables(self):
        """初始化所有需要的表"""
        cursor = self.conn.cursor()
        
        tables = {
            'sector_fund_flow': """
                CREATE TABLE IF NOT EXISTS sector_fund_flow (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL, sector_name TEXT NOT NULL, sector_type TEXT NOT NULL,
                    main_inflow REAL, main_inflow_pct REAL, change_pct REAL, turnover REAL,
                    rank_period TEXT NOT NULL,
                    UNIQUE(date, sector_name, rank_period)
                )""",
            'stock_finance': """
                CREATE TABLE IF NOT EXISTS stock_finance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL, report_period TEXT NOT NULL,
                    net_profit REAL, net_profit_yoy REAL, operating_revenue REAL, revenue_yoy REAL,
                    roe REAL, roe_diluted REAL, eps REAL, bps REAL, debt_ratio REAL, net_margin REAL,
                    UNIQUE(stock_code, report_period)
                )""",
            'north_fund_flow': """
                CREATE TABLE IF NOT EXISTS north_fund_flow (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    net_inflow REAL, sh_net_inflow REAL, sz_net_inflow REAL,
                    total_buy REAL, total_sell REAL
                )""",
            'stock_sector_map': """
                CREATE TABLE IF NOT EXISTS stock_sector_map (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL, sector_name TEXT NOT NULL, sector_type TEXT NOT NULL,
                    UNIQUE(stock_code, sector_name)
                )"""
        }
        
        for name, sql in tables.items():
            cursor.execute(sql)
            logger.info(f"Table {name} ready")
        
        self.conn.commit()
    
    def fetch_and_save_sector_flow(self, date_str):
        """下载并保存板块资金流向"""
        try:
            import akshare as ak
            
            for period in ['今日', '3日', '5日', '10日']:
                for sector_type_name, sector_type_val in [('industry', '行业资金流'), ('concept', '概念资金流')]:
                    try:
                        df = ak.stock_sector_fund_flow_rank(indicator=period, sector_type=sector_type_val)
                        if df is not None and len(df) > 0:
                            records = []
                            for _, row in df.iterrows():
                                records.append((
                                    date_str,
                                    str(row.get('板块名称', '')),
                                    sector_type_name,
                                    self._parse_num(row.get('主力净流入-净额', 0)),
                                    self._parse_num(row.get('主力净流入-净占比', 0)),
                                    self._parse_num(row.get('涨跌幅', 0)),
                                    self._parse_num(row.get('换手率', 0)),
                                    period
                                ))
                            
                            cursor = self.conn.cursor()
                            cursor.executemany("""
                                INSERT OR REPLACE INTO sector_fund_flow 
                                (date, sector_name, sector_type, main_inflow, main_inflow_pct, change_pct, turnover, rank_period)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, records)
                            self.conn.commit()
                            logger.info(f"Saved {len(records)} {sector_type_name} records for {period}")
                    except Exception as e:
                        logger.warning(f"Sector flow {period}/{sector_type_name} failed: {e}")
                        
        except Exception as e:
            logger.error(f"Sector flow fetch failed: {e}")
    
    def fetch_and_save_north_flow(self, date_str):
        """下载并保存北向资金"""
        try:
            import akshare as ak
            df = ak.stock_hsgt_fund_flow_summary_em()
            if df is not None and len(df) > 0:
                records = []
                for _, row in df.iterrows():
                    records.append((
                        str(row.get('交易日', date_str)),
                        self._parse_num(row.get('资金净流入', 0)),
                        self._parse_num(row.get('成交净买额', 0)) if row.get('板块') == '沪股通' else 0,
                        self._parse_num(row.get('成交净买额', 0)) if row.get('板块') == '深股通' else 0,
                        0, 0
                    ))
                
                cursor = self.conn.cursor()
                cursor.executemany("""
                    INSERT OR REPLACE INTO north_fund_flow 
                    (date, net_inflow, sh_net_inflow, sz_net_inflow, total_buy, total_sell)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, records)
                self.conn.commit()
                logger.info(f"Saved {len(records)} north flow records")
        except Exception as e:
            logger.error(f"North flow fetch failed: {e}")
    
    def fetch_and_save_finance(self, stock_codes, batch_size=50):
        """批量下载财务摘要"""
        try:
            import akshare as ak
            
            total_saved = 0
            for i in range(0, len(stock_codes), batch_size):
                batch = stock_codes[i:i+batch_size]
                for code in batch:
                    try:
                        df = ak.stock_financial_abstract_ths(symbol=code)
                        if df is not None and len(df) > 0:
                            records = []
                            for _, row in df.iterrows():
                                records.append((
                                    code,
                                    str(row.get('报告期', '')),
                                    self._parse_num(row.get('净利润', 0)),
                                    self._parse_num(row.get('净利润同比增长率', 0)),
                                    self._parse_num(row.get('营业总收入', 0)),
                                    self._parse_num(row.get('营业总收入同比增长率', 0)),
                                    self._parse_num(row.get('净资产收益率', 0)),
                                    self._parse_num(row.get('净资产收益率-摊薄', 0)),
                                    self._parse_num(row.get('基本每股收益', 0)),
                                    self._parse_num(row.get('每股净资产', 0)),
                                    self._parse_num(row.get('资产负债率', 0)),
                                    self._parse_num(row.get('销售净利率', 0))
                                ))
                            
                            cursor = self.conn.cursor()
                            cursor.executemany("""
                                INSERT OR REPLACE INTO stock_finance 
                                (stock_code, report_period, net_profit, net_profit_yoy, 
                                 operating_revenue, revenue_yoy, roe, roe_diluted, 
                                 eps, bps, debt_ratio, net_margin)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, records)
                            self.conn.commit()
                            total_saved += len(records)
                    except Exception as e:
                        logger.debug(f"Finance fetch {code} failed: {e}")
                
                logger.info(f"Finance batch {i//batch_size + 1}: {total_saved} total records saved")
                
        except Exception as e:
            logger.error(f"Finance fetch failed: {e}")
    
    def fill_sector_map_from_industry_cons(self, max_boards=50):
        """用 akshare 板块成分股填充 stock_sector_map"""
        try:
            import akshare as ak
            
            cursor = self.conn.cursor()
            
            # 获取行业板块列表
            boards = ak.stock_board_industry_name_em()
            logger.info(f"Found {len(boards)} industry boards")
            
            total_records = 0
            for board_name in boards['板块名称'].head(max_boards):
                try:
                    cons = ak.stock_board_industry_cons_em(symbol=board_name)
                    if cons is not None and len(cons) > 0:
                        records = []
                        for _, row in cons.iterrows():
                            code = str(row.get('代码', '')).zfill(6)
                            if code and len(code) == 6:
                                records.append((code, board_name, 'industry'))
                        
                        cursor.executemany("""
                            INSERT OR IGNORE INTO stock_sector_map (stock_code, sector_name, sector_type)
                            VALUES (?, ?, ?)
                        """, records)
                        self.conn.commit()
                        total_records += len(records)
                        logger.info(f"  {board_name}: {len(records)} stocks")
                except Exception as e:
                    logger.debug(f"  {board_name} failed: {e}")
            
            logger.info(f"Total sector_map records: {total_records}")
            
        except Exception as e:
            logger.error(f"Sector map fill failed: {e}")
    
    def calculate_historical_volatility(self):
        """为所有股票计算历史波动率（ATR）"""
        cursor = self.conn.cursor()
        
        # 获取所有股票代码
        cursor.execute("SELECT DISTINCT stock_code FROM stock_history")
        codes = [r[0] for r in cursor.fetchall()]
        
        logger.info(f"Calculating volatility for {len(codes)} stocks")
        
        # 为每只股票计算 ATR
        updated = 0
        for code in codes:
            try:
                df = pd.read_sql(
                    f"SELECT * FROM stock_history WHERE stock_code = '{code}' ORDER BY trade_date",
                    self.conn
                )
                
                if len(df) < 20:
                    continue
                
                # 计算 ATR
                df['tr1'] = df['high'] - df['low']
                df['tr2'] = abs(df['high'] - df['close'].shift(1))
                df['tr3'] = abs(df['low'] - df['close'].shift(1))
                df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
                df['atr14'] = df['tr'].rolling(window=14).mean()
                
                # 计算 60 日波动率
                df['volatility_60d'] = df['close'].pct_change().rolling(window=60).std() * 100
                
                # 更新最新一条记录
                latest = df.iloc[-1]
                cursor.execute("""
                    UPDATE stock_history 
                    SET atr14 = ?, volatility_60d = ?
                    WHERE stock_code = ? AND trade_date = ?
                """, (latest['atr14'], latest['volatility_60d'], code, latest['trade_date']))
                
                updated += 1
                
            except Exception as e:
                logger.debug(f"Volatility calc {code} failed: {e}")
        
        self.conn.commit()
        logger.info(f"Updated volatility for {updated} stocks")
    
    def generate_full_report(self, report_date=None, output_dir='./reports'):
        """生成完整报告"""
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        if report_date is None:
            report_date = self._get_latest_date()
        
        logger.info(f"Generating report for {report_date}")
        
        # 1. 市场情绪扫描
        sentiment = self._scan_sentiment(report_date)
        
        # 2. 板块轮动分析
        rotation = self._analyze_rotation(report_date)
        
        # 3. 热点板块
        hot_sectors = rotation[rotation['stage'].isin(['启动', '扩散', '高潮'])]['sector_name'].tolist() if rotation is not None else []
        
        # 4. 选股
        stock_picks = self._pick_stocks(hot_sectors, report_date)
        
        # 5. 生成报告
        report = self._format_report(report_date, sentiment, rotation, stock_picks)
        
        # 6. 保存
        report_file = os.path.join(output_dir, f"daily_report_v2_{report_date}.md")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        logger.info(f"Report saved: {report_file}")
        return report_file
    
    def _scan_sentiment(self, date):
        """市场情绪扫描"""
        latest = pd.read_sql(f"SELECT * FROM stock_history WHERE trade_date = '{date}'", self.conn)
        
        if len(latest) == 0:
            return None
        
        up = len(latest[latest['change_pct'] > 0])
        down = len(latest[latest['change_pct'] < 0])
        total = len(latest)
        limit_up = len(latest[latest['change_pct'] >= 9.9])
        limit_down = len(latest[latest['change_pct'] <= -9.9])
        
        # 北向资金
        north_df = pd.read_sql(f"SELECT * FROM north_fund_flow WHERE date = '{date}'", self.conn)
        north_inflow = north_df['net_inflow'].sum() if len(north_df) > 0 else 0
        
        # 成交额
        today_amount = latest['amount'].sum()
        
        # 情绪评分
        score = 50.0
        if total > 0:
            score += (up / total - 0.5) * 40
        score += (limit_up - limit_down) * 0.3
        if today_amount > 8e10:
            score += 3
        if north_inflow > 3e9:
            score += 3
        
        score = max(0, min(100, score))
        
        sentiment_map = [(75, "乐观"), (60, "偏乐观"), (45, "中性"), (30, "偏悲观")]
        sentiment = "悲观"
        for threshold, label in sentiment_map:
            if score >= threshold:
                sentiment = label
                break
        
        return {
            'date': date, 'score': round(score, 1), 'sentiment': sentiment,
            'up_count': up, 'down_count': down, 'total': total,
            'up_ratio': round(up/total*100, 1), 'limit_up': limit_up, 'limit_down': limit_down,
            'today_amount': round(today_amount/1e8, 2), 'north_inflow': round(north_inflow/1e8, 2)
        }
    
    def _analyze_rotation(self, date):
        """板块轮动分析"""
        df = pd.read_sql(f"""
            SELECT sector_name, main_inflow, change_pct 
            FROM sector_fund_flow 
            WHERE date = '{date}' AND rank_period = '今日' AND sector_type = 'industry'
            ORDER BY main_inflow DESC
        """, self.conn)
        
        if len(df) == 0:
            return None
        
        # 简单阶段判断（基于资金流向排名）
        df['today_rank'] = range(1, len(df) + 1)
        df['stage'] = df['today_rank'].apply(lambda r: '高潮' if r <= 3 else '扩散' if r <= 8 else '启动' if r <= 15 else '观察')
        df['action'] = df['stage'].apply(lambda s: {'高潮': '持有/减仓', '扩散': '介入/加仓', '启动': '关注/试探', '观察': '观望'}.get(s, '观望'))
        
        return df
    
    def _pick_stocks(self, hot_sectors, date):
        """热点板块内选股"""
        if len(hot_sectors) == 0:
            return pd.DataFrame()
        
        # 获取热点板块内的股票
        placeholders = ','.join(['?' for _ in hot_sectors])
        map_df = pd.read_sql(f"""
            SELECT DISTINCT stock_code FROM stock_sector_map 
            WHERE sector_name IN ({placeholders}) AND sector_type = 'industry'
        """, self.conn, params=hot_sectors)
        
        if len(map_df) == 0:
            return pd.DataFrame()
        
        sector_stocks = map_df['stock_code'].tolist()
        
        # 获取这些股票的技术数据
        stock_placeholders = ','.join(['?' for _ in sector_stocks])
        tech_df = pd.read_sql(f"""
            SELECT * FROM stock_history WHERE trade_date = '{date}' AND stock_code IN ({stock_placeholders})
        """, self.conn, params=sector_stocks)
        
        if len(tech_df) == 0:
            return pd.DataFrame()
        
        # 获取财务数据
        fin_df = pd.read_sql(f"""
            SELECT stock_code, roe, debt_ratio, revenue_yoy, net_profit
            FROM stock_finance
            WHERE stock_code IN ({stock_placeholders})
            AND report_period = (SELECT MAX(report_period) FROM stock_finance WHERE stock_code IN ({stock_placeholders}))
        """, self.conn, params=sector_stocks + sector_stocks)
        
        if len(fin_df) > 0:
            tech_df = tech_df.merge(fin_df, on='stock_code', how='left')
        
        # 技术筛选
        mask = (
            (tech_df['change_pct'] > -1) &
            (tech_df.get('close', 0) > 0)
        )
        filtered = tech_df[mask].copy()
        
        if len(filtered) == 0:
            return pd.DataFrame()
        
        # 计算评分（确保有区分度）
        filtered['tech_score'] = self._calc_tech_score(filtered)
        filtered['fund_score'] = self._calc_fund_score(filtered)
        filtered['total_score'] = filtered['tech_score'] * 0.6 + filtered['fund_score'] * 0.4
        
        # 计算买卖点
        filtered['atr14'] = filtered.get('atr14', filtered['close'] * 0.02).fillna(filtered['close'] * 0.02)
        filtered['buy_low'] = filtered['close'] * 0.98
        filtered['buy_high'] = filtered['close'] * 1.02
        filtered['stop_loss'] = filtered['close'] - 2 * filtered['atr14']
        filtered['target'] = filtered['close'] + 3 * filtered['atr14']
        filtered['risk_reward'] = np.where(
            (filtered['buy_high'] - filtered['stop_loss']) > 0,
            (filtered['target'] - filtered['buy_high']) / (filtered['buy_high'] - filtered['stop_loss']),
            0
        )
        
        result = filtered.sort_values('total_score', ascending=False).head(20)
        return result
    
    def _calc_tech_score(self, df):
        """技术面评分（0-100，确保区分度）"""
        score = 50.0
        
        # 涨跌幅（-20 ~ +20）
        score += df['change_pct'].clip(-10, 10) * 1.5
        
        # 如果有波动率数据
        if 'volatility_60d' in df.columns:
            vol = df['volatility_60d'].fillna(20)
            score += (30 - vol).clip(-10, 10) * 0.5  # 低波动加分
        
        # 如果有 ATR 数据
        if 'atr14' in df.columns:
            atr = df['atr14'].fillna(df['close'] * 0.02)
            atr_ratio = atr / df['close'] * 100
            score += (5 - atr_ratio).clip(-5, 5) * 2  # 低 ATR 加分
        
        # 成交量（如果 amount 大则加分）
        if 'amount' in df.columns:
            amt = df['amount'].fillna(0)
            score += (amt / amt.max()).fillna(0) * 10
        
        return score.clip(0, 100)
    
    def _calc_fund_score(self, df):
        """基本面评分（0-100，确保区分度）"""
        score = 50.0
        
        # ROE（0-30% 映射到 0-30 分）
        if 'roe' in df.columns:
            roe = df['roe'].fillna(0)
            score += roe.clip(0, 30) * 1.5
        
        # 净利润
        if 'net_profit' in df.columns:
            profit = df['net_profit'].fillna(0)
            score += np.where(profit > 0, 10, -5)
        
        # 负债率
        if 'debt_ratio' in df.columns:
            debt = df['debt_ratio'].fillna(100)
            score -= (debt - 50).clip(0, 50) * 0.3
        
        # 营收增长
        if 'revenue_yoy' in df.columns:
            revenue = df['revenue_yoy'].fillna(0)
            score += revenue.clip(-20, 50) * 0.2
        
        return score.clip(0, 100)
    
    def _format_report(self, date, sentiment, rotation, stock_picks):
        """格式化报告"""
        report = f"""# 📊 每日深度投资分析报告

**报告日期**: {date}  
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**数据来源**: AData + akshare（A股全市场）

---

## 一、市场情绪扫描

"""
        
        if sentiment:
            report += f"""
**情绪评分**: {sentiment['score']}/100 （{sentiment['sentiment']}）

| 指标 | 数值 |
|------|------|
| 统计股票数 | {sentiment['total']} 只 |
| 上涨家数 | {sentiment['up_count']} ({sentiment['up_ratio']}%) |
| 下跌家数 | {sentiment['down_count']} |
| 涨停数 | {sentiment['limit_up']} |
| 跌停数 | {sentiment['limit_down']} |
| 今日成交额 | ¥{sentiment['today_amount']} 亿 |
| 北向资金净流入 | ¥{sentiment['north_inflow']} 亿 |
"""
        else:
            report += "市场情绪数据暂不可用\n"
        
        report += "\n---\n\n## 二、板块轮动分析\n\n"
        
        if rotation is not None and len(rotation) > 0:
            report += """| 板块名称 | 排名 | 主力净流入(亿) | 涨跌幅 | 轮动阶段 | 推荐操作 |
|---------|------|---------------|--------|---------|---------|
"""
            for _, row in rotation.head(20).iterrows():
                inflow = row['main_inflow'] / 1e8 if row['main_inflow'] else 0
                report += f"| {row['sector_name']} | {row['today_rank']} | {'+' if inflow > 0 else ''}¥{inflow:.1f} | {row['change_pct']:+.2f}% | {row['stage']} | {row['action']} |\n"
        else:
            report += "板块轮动数据暂不可用\n"
        
        report += "\n---\n\n## 三、热点板块个股推荐\n\n"
        
        if stock_picks is not None and len(stock_picks) > 0:
            report += f"基于热点板块扫描，综合技术面和基本面筛选出 **{len(stock_picks)}** 只推荐股票：\n\n"
            report += """| 排名 | 股票代码 | 收盘价 | 涨跌幅 | 综合评分 | 推荐买入区间 | 止损价 | 目标价 | 盈亏比 |
|------|---------|--------|--------|---------|-------------|--------|--------|--------|
"""
            for i, (_, row) in enumerate(stock_picks.head(20).iterrows(), 1):
                rr = row['risk_reward']
                rr_str = f"{rr:.2f}" if pd.notna(rr) else "N/A"
                report += f"| {i} | {row['stock_code']} | ¥{row['close']:.2f} | {row['change_pct']:+.2f}% | {row['total_score']:.1f} | ¥{row['buy_low']:.2f}~¥{row['buy_high']:.2f} | ¥{row['stop_loss']:.2f} | ¥{row['target']:.2f} | {rr_str} |\n"
            
            report += "\n---\n\n## 四、重点个股深度分析\n\n"
            
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
| | 综合评分 | {row['total_score']:.1f}/100 |
| **基本面** | ROE | {row.get('roe', 'N/A'):.1f if pd.notna(row.get('roe')) else 'N/A'}% |
| | 资产负债率 | {row.get('debt_ratio', 'N/A'):.1f if pd.notna(row.get('debt_ratio')) else 'N/A'}% |
| | 营收同比 | {row.get('revenue_yoy', 'N/A'):.1f if pd.notna(row.get('revenue_yoy')) else 'N/A'}% |

**买入原因**: 
- 技术面评分 {row['tech_score']:.1f}/100，{'强势' if row['tech_score'] > 70 else '中等' if row['tech_score'] > 50 else '一般'}
- 基本面评分 {row['fund_score']:.1f}/100，{'良好' if row['fund_score'] > 70 else '中等' if row['fund_score'] > 50 else '一般'}
- 盈亏比 {row['risk_reward']:.2f}，{'优秀' if row['risk_reward'] > 1.5 else '可接受' if row['risk_reward'] > 1 else '一般'}

---

"""
        else:
            report += "暂无符合条件的推荐股票\n"
        
        report += """
## 五、免责声明

⚠️ **本报告仅供学习研究使用，不构成任何投资建议。**

---

*报告由 LOM Trade System v2 自动生成*
"""
        
        return report
    
    def _get_latest_date(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM stock_history")
        date = cursor.fetchone()[0]
        return date
    
    def _parse_num(self, val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(',', '').replace('万', '').replace('亿', '')
        try:
            return float(s)
        except:
            return 0.0
    
    def close(self):
        self.conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='./data/stock_db.sqlite')
    parser.add_argument('--date', default=None)
    parser.add_argument('--output', default='./reports')
    parser.add_argument('--mode', choices=['data', 'report', 'all'], default='all')
    args = parser.parse_args()
    
    opt = TradeSystemOptimizer(db_path=args.db)
    
    if args.mode in ['data', 'all']:
        logger.info("=== Step 1: Fetching sector fund flow ===")
        opt.fetch_and_save_sector_flow(args.date or opt._get_latest_date())
        
        logger.info("=== Step 2: Fetching north fund flow ===")
        opt.fetch_and_save_north_flow(args.date or opt._get_latest_date())
        
        logger.info("=== Step 3: Filling sector map ===")
        opt.fill_sector_map_from_industry_cons()
        
        logger.info("=== Step 4: Calculating historical volatility ===")
        opt.calculate_historical_volatility()
        
        # 下载部分财务数据（前100只股票）
        cursor = opt.conn.cursor()
        cursor.execute("SELECT DISTINCT stock_code FROM stock_history LIMIT 100")
        codes = [r[0] for r in cursor.fetchall()]
        logger.info(f"=== Step 5: Fetching finance data for {len(codes)} stocks ===")
        opt.fetch_and_save_finance(codes)
    
    if args.mode in ['report', 'all']:
        logger.info("=== Step 6: Generating report ===")
        report_file = opt.generate_full_report(args.date, args.output)
        logger.info(f"Report generated: {report_file}")
    
    opt.close()
    logger.info("All done!")
