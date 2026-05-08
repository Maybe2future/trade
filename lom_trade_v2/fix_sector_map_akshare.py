#!/usr/bin/env python3
"""
用 akshare 获取板块成分股，填充 stock_sector_map 表
"""

import akshare as ak
import sqlite3
import pandas as pd


def fill_sector_map_with_akshare(db_path='./data/stock_db.sqlite'):
    """用 akshare 获取板块成分股数据"""
    conn = sqlite3.connect(db_path)
    
    # 1. 先获取行业板块列表
    print("获取行业板块列表...")
    try:
        industry_boards = ak.stock_board_industry_name_em()
        print(f"获取到 {len(industry_boards)} 个行业板块")
    except Exception as e:
        print(f"获取行业板块失败: {e}")
        industry_boards = pd.DataFrame()
    
    # 2. 获取概念板块列表
    print("获取概念板块列表...")
    try:
        concept_boards = ak.stock_board_concept_name_em()
        print(f"获取到 {len(concept_boards)} 个概念板块")
    except Exception as e:
        print(f"获取概念板块失败: {e}")
        concept_boards = pd.DataFrame()
    
    # 3. 逐个行业板块获取成分股
    records = []
    
    if len(industry_boards) > 0:
        for board_name in industry_boards['板块名称'].head(50):  # 先取前50个
            try:
                cons = ak.stock_board_industry_cons_em(symbol=board_name)
                for _, row in cons.iterrows():
                    code = str(row.get('代码', '')).zfill(6)
                    if code:
                        records.append((code, board_name, 'industry'))
                print(f"  {board_name}: {len(cons)} 只成分股")
            except Exception as e:
                print(f"  {board_name} 失败: {e}")
    
    # 4. 插入数据库
    if len(records) > 0:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR IGNORE INTO stock_sector_map (stock_code, sector_name, sector_type)
            VALUES (?, ?, ?)
        """, records)
        conn.commit()
        
        cursor.execute("SELECT COUNT(*) FROM stock_sector_map")
        count = cursor.fetchone()[0]
        print(f"\n成功填充 {count} 条 stock_sector_map 记录")
    else:
        print("\n没有获取到任何板块成分股数据")
    
    conn.close()


if __name__ == '__main__':
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else './data/stock_db.sqlite'
    fill_sector_map_with_akshare(db)
