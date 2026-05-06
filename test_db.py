#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库连接与表结构测试
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import DB_TYPE, get_database_url, POOL_SIZE, MAX_OVERFLOW

print("=" * 60)
print("  A股数据管理系统 — 数据库连接测试")
print("=" * 60)
print()

print(f"数据库类型: {DB_TYPE.upper()}")
print(f"连接字符串: {get_database_url()}")
print(f"连接池: size={POOL_SIZE}, overflow={MAX_OVERFLOW}")
print()

if DB_TYPE == 'postgresql':
    try:
        from core.postgresql_db import PostgreSQLStockDB

        db = PostgreSQLStockDB()
        print("✓ PostgreSQL 连接成功")

        db.init_tables()
        print("✓ 表结构初始化完成")
        print("  包含: stock_basic, stock_daily_hfq, stock_financial, index_daily,")
        print("       concept_board, concept_constituent, stock_realtime, sync_log")

        stats = db.get_statistics()
        print(f"\n数据库状态:")
        print(f"  - 股票总数: {stats.get('total_stocks', 0)}")
        print(f"  - 已下载: {stats.get('downloaded_stocks', 0)} 只")
        print(f"  - 总记录: {stats.get('total_history_records', 0):,} 条")
        print(f"  - 财务记录: {stats.get('total_financial_records', 0):,} 条")
        print(f"  - 指数记录: {stats.get('total_index_records', 0):,} 条")
        print(f"  - 概念数量: {stats.get('total_concepts', 0):,} 个")
        print(f"  - 实时记录: {stats.get('total_realtime_records', 0):,} 条")
        print(f"  - 磁盘占用: {stats.get('database_size', 'N/A')}")
        print(f"  - 数据范围: {stats.get('date_range', '无')}")

    except Exception as e:
        print(f"✗ 连接失败: {e}")
        print()
        print("可能的原因:")
        print("  1. PostgreSQL 未安装")
        print("  2. 服务未启动 — sudo systemctl start postgresql")
        print("  3. 用户/密码/库名不正确 — 检查 config.py")
        print("  4. 缺少 psycopg2 — pip install psycopg2-binary")
else:
    print("当前配置为 SQLite，跳过 PostgreSQL 测试")

print()
print("=" * 60)
print("测试完成")
print("=" * 60)
