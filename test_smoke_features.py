#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
astock_system 功能冒烟测试

使用临时 SQLite 数据库验证 PostgreSQLStockDB 的核心接口：
- 股票基础信息
- 日线后复权
- 财务数据
- 指数数据
- 概念板块与成分股
- 实时行情快照
"""

import os
import sys
import tempfile

import pandas as pd

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.postgresql_db import PostgreSQLStockDB


def main():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    try:
        db = PostgreSQLStockDB(connection_string=f'sqlite:///{path}')
        db.init_tables()

        db.save_stock_basic(pd.DataFrame([
            {'stock_code': '000001', 'short_name': '平安银行', 'industry': '银行'}
        ]))
        db.save_daily_hfq(pd.DataFrame([
            {
                'trade_date': '2024-01-02',
                'open': 10.0,
                'close': 11.0,
                'high': 11.2,
                'low': 9.8,
                'volume': 1000,
                'amount': 10000,
                'change_pct': 1.0,
                'change_amount': 1.0,
                'turnover_ratio': 2.0,
                'pre_close': 10.0,
            }
        ]), '000001')
        db.save_financial(pd.DataFrame([
            {'report_date': '2024-12-31', 'report_type': '年报', 'basic_eps': 1.23}
        ]), '000001')
        db.save_index_daily(pd.DataFrame([
            {
                'trade_date': '2024-01-02',
                'open': 3000,
                'close': 3010,
                'high': 3020,
                'low': 2990,
                'volume': 1000,
                'amount': 2000,
                'change_pct': 0.3,
            }
        ]), '000300', '沪深300')
        db.save_concept_boards(pd.DataFrame([
            {'concept_code': 'GN001', 'concept_name': '人工智能'}
        ]))
        db.replace_concept_constituents('GN001', pd.DataFrame([
            {'stock_code': '000001', 'stock_name': '平安银行'}
        ]))
        db.save_realtime_quotes(pd.DataFrame([
            {
                'stock_code': '000001',
                'short_name': '平安银行',
                'open': 10.0,
                'close': 10.5,
                'high': 10.6,
                'low': 9.9,
                'volume': 100,
                'amount': 1000,
                'change_pct': 0.5,
                'change_amount': 0.05,
            }
        ]))

        stats = db.get_statistics()
        concept_stats = db.get_concept_stats()
        realtime_stats = db.get_realtime_stats()

        assert stats['total_stocks'] == 1
        assert stats['downloaded_stocks'] == 1
        assert stats['total_history_records'] == 1
        assert stats['total_financial_records'] == 1
        assert stats['total_index_records'] == 1
        assert stats['total_concepts'] == 1
        assert stats['total_realtime_records'] == 1
        assert len(db.get_financial('000001')) == 1
        assert len(db.get_index_daily('000300')) == 1
        assert concept_stats['total_concepts'] == 1
        assert concept_stats['total_constituents'] == 1
        assert realtime_stats['total_records'] == 1
        assert len(db.get_latest_realtime_snapshot()) == 1

        print("✓ 功能冒烟测试通过")
    finally:
        if os.path.exists(path):
            os.remove(path)


if __name__ == '__main__':
    main()
