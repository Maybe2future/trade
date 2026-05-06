# -*- coding: utf-8 -*-
"""
A股数据下载系统 - 数据库管理模块
"""

import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import os


class StockDatabase:
    """股票数据库管理类"""
    
    def __init__(self, db_path='./data/stock_db.sqlite'):
        """
        初始化数据库连接
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # 创建数据库连接
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        
    def init_tables(self):
        """初始化数据库表结构"""
        with self.engine.connect() as conn:
            # 股票基本信息表
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS stock_info (
                    stock_code TEXT PRIMARY KEY,
                    short_name TEXT,
                    exchange TEXT,
                    list_date TEXT,
                    industry TEXT,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            
            # 历史行情数据表
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS stock_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT,
                    trade_date TEXT,
                    open REAL,
                    close REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    amount REAL,
                    change_pct REAL,
                    change_amount REAL,
                    turnover_ratio REAL,
                    pre_close REAL,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date)
                )
            '''))
            
            # 实时行情数据表
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS stock_realtime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT,
                    short_name TEXT,
                    trade_date TEXT,
                    trade_time TEXT,
                    open REAL,
                    close REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    amount REAL,
                    change_pct REAL,
                    change_amount REAL,
                    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code, trade_date, trade_time)
                )
            '''))
            
            # 下载记录表
            conn.execute(text('''
                CREATE TABLE IF NOT EXISTS download_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT,
                    download_type TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    records_count INTEGER,
                    status TEXT,
                    message TEXT,
                    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            
            # 创建索引
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_history_code_date 
                ON stock_history(stock_code, trade_date)
            '''))
            
            conn.execute(text('''
                CREATE INDEX IF NOT EXISTS idx_realtime_code 
                ON stock_realtime(stock_code)
            '''))
            
            conn.commit()
        
        print("✓ 数据库表初始化完成")
    
    def save_stock_info(self, df):
        """
        保存股票基本信息
        
        Args:
            df: DataFrame包含股票信息
        """
        df['update_time'] = datetime.now()
        df.to_sql('stock_info', self.engine, if_exists='replace', index=False)
        print(f"✓ 保存股票信息: {len(df)} 条")
    
    def get_stock_info(self, stock_code=None):
        """
        获取股票基本信息
        
        Args:
            stock_code: 股票代码，None返回所有
            
        Returns:
            DataFrame
        """
        if stock_code:
            query = "SELECT * FROM stock_info WHERE stock_code = :code"
            return pd.read_sql(query, self.engine, params={'code': stock_code})
        else:
            return pd.read_sql("SELECT * FROM stock_info", self.engine)
    
    def save_history_data(self, df, stock_code):
        """
        保存历史行情数据
        
        Args:
            df: DataFrame包含历史数据
            stock_code: 股票代码
        """
        if df.empty:
            return
        
        # 确保列名正确
        df = df.copy()
        df['stock_code'] = stock_code
        df['update_time'] = datetime.now()
        
        # 选择需要的列
        columns = ['stock_code', 'trade_date', 'open', 'close', 'high', 'low', 
                   'volume', 'amount', 'change_pct', 'change_amount', 
                   'turnover_ratio', 'pre_close', 'update_time']
        
        # 删除重复的trade_time列（AData同时返回了trade_time和trade_date）
        if 'trade_time' in df.columns:
            df = df.drop(columns=['trade_time'])
        
        # 重命名列（适配AData返回的列名）
        column_map = {
            'change': 'change_amount'
        }
        df = df.rename(columns=column_map)
        
        # 只保留需要的列
        available_cols = [c for c in columns if c in df.columns]
        df = df[available_cols]
        
        # 查询该股票已存在的日期，避免重复插入
        try:
            existing_dates = self.get_data_date_range(stock_code)
            if existing_dates[0] and existing_dates[1]:
                # 获取已存在的所有日期
                existing_df = self.get_history_data(stock_code)
                existing_date_set = set(existing_df['trade_date'].tolist())
                
                # 过滤掉已存在的数据
                df = df[~df['trade_date'].isin(existing_date_set)]
                
                if df.empty:
                    print(f"  股票 {stock_code}: 所有数据已存在，跳过")
                    return
        except Exception as e:
            print(f"  检查现有数据时出错: {e}")
        
        # 插入数据（使用 try-except 捕获重复键错误）
        try:
            df.to_sql('stock_history', self.engine, if_exists='append', index=False)
            print(f"  股票 {stock_code}: 成功保存 {len(df)} 条记录")
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                print(f"  股票 {stock_code}: 数据已存在，跳过")
            else:
                raise e
    
    def get_history_data(self, stock_code, start_date=None, end_date=None):
        """
        获取历史行情数据
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame
        """
        query = "SELECT * FROM stock_history WHERE stock_code = :code"
        params = {'code': stock_code}
        
        if start_date:
            query += " AND trade_date >= :start"
            params['start'] = start_date
        if end_date:
            query += " AND trade_date <= :end"
            params['end'] = end_date
        
        query += " ORDER BY trade_date"
        
        return pd.read_sql(query, self.engine, params=params)
    
    def save_realtime_data(self, df):
        """
        保存实时行情数据
        
        Args:
            df: DataFrame包含实时数据
        """
        if df.empty:
            return
        
        df = df.copy()
        df['update_time'] = datetime.now()
        df['trade_date'] = datetime.now().strftime('%Y-%m-%d')
        df['trade_time'] = datetime.now().strftime('%H:%M:%S')
        
        df.to_sql('stock_realtime', self.engine, if_exists='append', index=False)
    
    def get_data_date_range(self, stock_code):
        """
        获取某只股票的数据日期范围
        
        Args:
            stock_code: 股票代码
            
        Returns:
            tuple: (最早日期, 最晚日期)
        """
        query = """
            SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date 
            FROM stock_history 
            WHERE stock_code = :code
        """
        df = pd.read_sql(query, self.engine, params={'code': stock_code})
        
        if df.empty or pd.isna(df['min_date'].iloc[0]):
            return None, None
        
        return df['min_date'].iloc[0], df['max_date'].iloc[0]
    
    def get_downloaded_stocks(self):
        """
        获取已下载数据的股票列表
        
        Returns:
            list: 股票代码列表
        """
        query = "SELECT DISTINCT stock_code FROM stock_history"
        df = pd.read_sql(query, self.engine)
        return df['stock_code'].tolist() if not df.empty else []
    
    def log_download(self, stock_code, download_type, start_date, end_date, 
                     records_count, status, message=''):
        """
        记录下载日志
        """
        with self.engine.connect() as conn:
            conn.execute(text('''
                INSERT INTO download_log 
                (stock_code, download_type, start_date, end_date, 
                 records_count, status, message)
                VALUES (:code, :type, :start, :end, :count, :status, :msg)
            '''), {
                'code': stock_code,
                'type': download_type,
                'start': start_date,
                'end': end_date,
                'count': records_count,
                'status': status,
                'msg': message
            })
            conn.commit()
    
    def get_download_logs(self, limit=100):
        """
        获取下载日志
        
        Args:
            limit: 返回记录数
            
        Returns:
            DataFrame
        """
        query = f"""
            SELECT * FROM download_log 
            ORDER BY create_time DESC 
            LIMIT {limit}
        """
        return pd.read_sql(query, self.engine)
    
    def get_statistics(self):
        """
        获取数据库统计信息
        
        Returns:
            dict: 统计信息
        """
        stats = {}
        
        with self.engine.connect() as conn:
            # 股票总数
            result = conn.execute(text("SELECT COUNT(*) FROM stock_info"))
            stats['total_stocks'] = result.scalar()
            
            # 已下载数据的股票数
            result = conn.execute(text("SELECT COUNT(DISTINCT stock_code) FROM stock_history"))
            stats['downloaded_stocks'] = result.scalar()
            
            # 历史数据总条数
            result = conn.execute(text("SELECT COUNT(*) FROM stock_history"))
            stats['total_history_records'] = result.scalar()
            
            # 实时数据总条数
            result = conn.execute(text("SELECT COUNT(*) FROM stock_realtime"))
            stats['total_realtime_records'] = result.scalar()
            
            # 数据日期范围
            result = conn.execute(text("""
                SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date 
                FROM stock_history
            """))
            row = result.fetchone()
            stats['date_range'] = f"{row[0]} ~ {row[1]}" if row[0] else "无数据"
        
        return stats
    
    def export_to_csv(self, stock_code, filepath):
        """
        导出数据到CSV
        
        Args:
            stock_code: 股票代码
            filepath: 导出文件路径
        """
        df = self.get_history_data(stock_code)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        return len(df)