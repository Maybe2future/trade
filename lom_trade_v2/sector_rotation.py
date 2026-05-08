#!/usr/bin/env python3
"""
LOM Trade System v2 — 板块轮动分析模块
"""

import sqlite3
import pandas as pd
from datetime import datetime


class SectorRotation:
    """板块轮动分析器"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        self.db_path = db_path
    
    def analyze_sector_rotation(self, date=None):
        """
        分析板块轮动
        返回每个板块的阶段判断：启动/扩散/高潮/退潮/切换/冷门
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        conn = sqlite3.connect(self.db_path)
        
        # 获取今日、3日、5日、10日的板块资金流向
        periods = ['今日', '3日', '5日', '10日']
        all_data = {}
        
        for period in periods:
            df = pd.read_sql(f"""
                SELECT sector_name, main_inflow, main_inflow_pct, change_pct
                FROM sector_fund_flow 
                WHERE date = '{date}' AND rank_period = '{period}' AND sector_type = 'industry'
                ORDER BY main_inflow DESC
            """, conn)
            all_data[period] = df
        
        conn.close()
        
        if len(all_data['今日']) == 0:
            return None
        
        # 分析每个板块的阶段
        results = []
        for _, row in all_data['今日'].iterrows():
            sector = row['sector_name']
            
            # 获取该板块在各周期的排名
            rank_today = self._get_rank(all_data['今日'], sector)
            rank_3d = self._get_rank(all_data.get('3日', pd.DataFrame()), sector)
            rank_5d = self._get_rank(all_data.get('5日', pd.DataFrame()), sector)
            rank_10d = self._get_rank(all_data.get('10日', pd.DataFrame()), sector)
            
            # 轮动阶段判断
            stage = self._judge_stage(rank_today, rank_3d, rank_5d, rank_10d)
            
            # 近5日趋势判断
            trend = self._judge_trend(rank_today, rank_3d, rank_5d)
            
            # 推荐操作
            action = self._recommend_action(stage, trend)
            
            results.append({
                'sector_name': sector,
                'today_rank': rank_today,
                'main_inflow': row['main_inflow'],
                'main_inflow_pct': row['main_inflow_pct'],
                'change_pct': row['change_pct'],
                'stage': stage,
                'trend': trend,
                'action': action
            })
        
        return pd.DataFrame(results)
    
    def _get_rank(self, df, sector_name):
        """获取板块在排名中的位置"""
        if len(df) == 0:
            return 999
        mask = df['sector_name'] == sector_name
        if mask.any():
            return mask.idxmax() + 1
        return 999
    
    def _judge_stage(self, r_today, r_3d, r_5d, r_10d):
        """判断板块轮动阶段"""
        in_top10_today = r_today <= 10
        in_top10_3d = r_3d <= 10
        in_top10_5d = r_5d <= 10
        in_top10_10d = r_10d <= 10
        
        if in_top10_today and in_top10_5d and in_top10_10d:
            return "高潮"
        elif in_top10_today and in_top10_3d and in_top10_5d:
            return "扩散"
        elif in_top10_today and in_top10_3d and not in_top10_5d:
            return "扩散"
        elif in_top10_today and not in_top10_3d and not in_top10_5d:
            return "启动"
        elif not in_top10_today and (in_top10_3d or in_top10_5d):
            return "退潮"
        elif not in_top10_today and not in_top10_3d and not in_top10_5d:
            return "冷门"
        else:
            return "观察"
    
    def _judge_trend(self, r_today, r_3d, r_5d):
        """判断趋势方向"""
        if r_today == 999:
            return "——"
        
        # 排名数字越小越好，排名上升意味着数字变小
        if r_5d == 999:
            if r_3d == 999:
                return "↑ 新进"
            elif r_today < r_3d:
                return "↑↑ 加速"
            else:
                return "↑ 上升"
        
        if r_today < r_5d:
            return "↑↑ 加速"
        elif r_today < r_3d:
            return "↑ 上升"
        elif r_today > r_5d and r_today > r_3d:
            return "↓↓ 回落"
        else:
            return "→ 平稳"
    
    def _recommend_action(self, stage, trend):
        """推荐操作"""
        action_map = {
            "启动": "关注/试探",
            "扩散": "介入/加仓",
            "高潮": "持有/减仓",
            "退潮": "规避",
            "冷门": "忽略",
            "观察": "观望"
        }
        return action_map.get(stage, "观望")
    
    def get_hot_sectors(self, date=None, top_n=10):
        """获取热点板块列表"""
        df = self.analyze_sector_rotation(date)
        if df is None:
            return []
        
        # 筛选处于启动/扩散/高潮阶段的板块
        hot = df[df['stage'].isin(['启动', '扩散', '高潮'])].head(top_n)
        return hot['sector_name'].tolist()


if __name__ == '__main__':
    sr = SectorRotation()
    result = sr.analyze_sector_rotation()
    if result is not None:
        print(result.head(10).to_string())
        print("\nHot sectors:", sr.get_hot_sectors())
