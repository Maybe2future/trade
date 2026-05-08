#!/usr/bin/env python3
"""
LOM Trade System v2 — 数据增强层
负责获取板块资金流向、财务摘要、北向资金等数据
"""

import sqlite3
import pandas as pd
import akshare as ak
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataEnhancement:
    """数据增强类：将板块资金、财务、北向资金等数据入库"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_tables()
    
    def _init_tables(self):
        """初始化新表"""
        cursor = self.conn.cursor()
        
        # 板块资金流向表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sector_fund_flow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                sector_name TEXT NOT NULL,
                sector_type TEXT NOT NULL,
                main_inflow REAL,
                main_inflow_pct REAL,
                change_pct REAL,
                turnover REAL,
                rank_period TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, sector_name, rank_period)
            )
        """)
        
        # 概念/行业板块行情表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sector_quotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                sector_name TEXT NOT NULL,
                sector_type TEXT NOT NULL,
                latest_price REAL,
                change_pct REAL,
                turnover REAL,
                amplitude REAL,
                amount REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, sector_name)
            )
        """)
        
        # 个股财务摘要表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_finance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                report_period TEXT NOT NULL,
                net_profit REAL,
                net_profit_yoy REAL,
                operating_revenue REAL,
                revenue_yoy REAL,
                roe REAL,
                roe_diluted REAL,
                eps REAL,
                bps REAL,
                debt_ratio REAL,
                net_margin REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_code, report_period)
            )
        """)
        
        # 北向资金流向表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS north_fund_flow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                net_inflow REAL,
                sh_net_inflow REAL,
                sz_net_inflow REAL,
                total_buy REAL,
                total_sell REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 个股-板块关联表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_sector_map (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                sector_name TEXT NOT NULL,
                sector_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(stock_code, sector_name)
            )
        """)
        
        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector_flow_date ON sector_fund_flow(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sector_flow_name ON sector_fund_flow(sector_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_fin_code ON stock_finance(stock_code)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_north_flow_date ON north_fund_flow(date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_stock_map_code ON stock_sector_map(stock_code)')
        
        self.conn.commit()
        logger.info("All tables initialized")
    
    def fetch_sector_fund_flow(self, rank_period='今日', sector_type='行业资金流'):
        """获取板块资金流向"""
        try:
            df = ak.stock_sector_fund_flow_rank(indicator=rank_period, sector_type=sector_type)
            logger.info(f"Fetched {len(df)} sectors for {rank_period}")
            return df
        except Exception as e:
            logger.error(f"Failed to fetch sector fund flow: {e}")
            return None
    
    def save_sector_fund_flow(self, df, rank_period, sector_type_name):
        """保存板块资金流向到数据库"""
        if df is None or len(df) == 0:
            return 0
        
        today = datetime.now().strftime('%Y-%m-%d')
        records = []
        for _, row in df.iterrows():
            records.append((
                today,
                row.get('板块名称', ''),
                sector_type_name,
                self._parse_number(row.get('主力净流入-净额', 0)),
                self._parse_number(row.get('主力净流入-净占比', 0)),
                self._parse_number(row.get('涨跌幅', 0)),
                self._parse_number(row.get('换手率', 0)),
                rank_period
            ))
        
        cursor = self.conn.cursor()
        cursor.executemany('''
            INSERT OR REPLACE INTO sector_fund_flow 
            (date, sector_name, sector_type, main_inflow, main_inflow_pct, change_pct, turnover, rank_period)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', records)
        self.conn.commit()
        logger.info(f"Saved {len(records)} sector fund flow records")
        return len(records)
    
    def fetch_stock_finance(self, stock_code):
        """获取个股财务摘要"""
        try:
            df = ak.stock_financial_abstract_ths(symbol=stock_code)
            logger.info(f"Fetched finance for {stock_code}: {len(df)} records")
            return df
        except Exception as e:
            logger.error(f"Failed to fetch finance for {stock_code}: {e}")
            return None
    
    def save_stock_finance(self, stock_code, df):
        """保存个股财务摘要"""
        if df is None or len(df) == 0:
            return 0
        
        records = []
        for _, row in df.iterrows():
            records.append((
                stock_code,
                row.get('报告期', ''),
                self._parse_number(row.get('净利润', 0)),
                self._parse_number(row.get('净利润同比增长率', 0)),
                self._parse_number(row.get('营业总收入', 0)),
                self._parse_number(row.get('营业总收入同比增长率', 0)),
                self._parse_number(row.get('净资产收益率', 0)),
                self._parse_number(row.get('净资产收益率-摊薄', 0)),
                self._parse_number(row.get('基本每股收益', 0)),
                self._parse_number(row.get('每股净资产', 0)),
                self._parse_number(row.get('资产负债率', 0)),
                self._parse_number(row.get('销售净利率', 0))
            ))
        
        cursor = self.conn.cursor()
        cursor.executemany('''
            INSERT OR REPLACE INTO stock_finance 
            (stock_code, report_period, net_profit, net_profit_yoy, 
             operating_revenue, revenue_yoy, roe, roe_diluted, eps, bps, debt_ratio, net_margin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', records)
        self.conn.commit()
        return len(records)
    
    def fetch_north_fund_flow(self):
        """获取北向资金流向"""
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
            logger.info(f"Fetched north fund flow: {len(df)} records")
            return df
        except Exception as e:
            logger.error(f"Failed to fetch north fund flow: {e}")
            return None
    
    def save_north_fund_flow(self, df):
        """保存北向资金流向"""
        if df is None or len(df) == 0:
            return 0
        
        records = []
        for _, row in df.iterrows():
            records.append((
                row.get('交易日', ''),
                self._parse_number(row.get('资金净流入', 0)),
                self._parse_number(row.get('成交净买额', 0)) if row.get('板块') == '沪股通' else 0,
                self._parse_number(row.get('成交净买额', 0)) if row.get('板块') == '深股通' else 0,
                0,
                0
            ))
        
        cursor = self.conn.cursor()
        cursor.executemany('''
            INSERT OR REPLACE INTO north_fund_flow 
            (date, net_inflow, sh_net_inflow, sz_net_inflow, total_buy, total_sell)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', records)
        self.conn.commit()
        return len(records)
    
    def _parse_number(self, val):
        """解析数值（处理中文单位）"""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if s == '' or s == 'False':
            return 0.0
        try:
            if '万' in s:
                return float(s.replace('万', '').replace(',', '')) * 10000
            if '亿' in s:
                return float(s.replace('亿', '').replace(',', '')) * 100000000
            return float(s.replace(',', ''))
        except:
            return 0.0
    
    def close(self):
        self.conn.close()


if __name__ == '__main__':
    de = DataEnhancement()
    df = de.fetch_sector_fund_flow('今日', '2')
    if df is not None:
        de.save_sector_fund_flow(df, '今日', 'industry')
    de.close()
