#!/usr/bin/env python3
"""
LOM Trade System v2 — 每日深度报告生成入口
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from advanced_report_generator import AdvancedReportGenerator


def main():
    parser = argparse.ArgumentParser(description='LOM Trade System v2 — 每日深度投资报告')
    parser.add_argument('--db', default='./data/stock_db.sqlite', help='数据库路径')
    parser.add_argument('--date', default=None, help='报告日期（默认最新）')
    parser.add_argument('--output', default='./reports', help='报告输出目录')
    parser.add_argument('--mode', choices=['full', 'sentiment', 'rotation', 'stocks'], 
                        default='full', help='分析模式')
    
    args = parser.parse_args()
    
    print("="*60)
    print("LOM Trade System v2 — 每日深度投资报告生成器")
    print("="*60)
    print(f"数据库: {args.db}")
    print(f"日期: {args.date or '最新'}")
    print(f"模式: {args.mode}")
    print("="*60)
    
    gen = AdvancedReportGenerator(db_path=args.db)
    
    if args.mode == 'full':
        report_file = gen.generate_report(date=args.date, output_path=args.output)
        print(f"\n✅ 报告已生成: {report_file}")
    else:
        print(f"模式 {args.mode} 开发中...")
    
    print("="*60)


if __name__ == '__main__':
    main()
