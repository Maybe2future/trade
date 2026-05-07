# -*- coding: utf-8 -*-
"""
系统配置文件
支持 PostgreSQL 数据库，含连接池参数
"""

import os

# ==================== 数据库配置 ====================

# 数据库类型: 'sqlite' 或 'postgresql'
DB_TYPE = 'sqlite'

# SQLite配置（备选，零配置，适合小型应用）
SQLITE_CONFIG = {
    'db_path': '/home/lom/openclaw_file/trade/astock_system/data/stock_db.sqlite'
}

# PostgreSQL配置（主力数据库）
POSTGRESQL_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'stock_db',
    'username': 'stock_user',
    'password': 'stock_password_123',
}

# 连接池配置
POOL_SIZE = 5          # 连接池常驻连接数
MAX_OVERFLOW = 10      # 允许溢出的额外连接数
POOL_RECYCLE = 3600    # 连接回收时间（秒），防止数据库端超时断连

# ==================== 下载配置 ====================

# 请求间隔（秒），避免被限制
DOWNLOAD_DELAY = 0.5

# 并发线程数（>=2 时：财务批量、多指数下载使用线程池提速）。
# 设为 1 则完全串行，行为与旧版一致。过大易触发东财/同花顺限流，建议 2～4。
DOWNLOAD_PARALLEL_WORKERS = 3

# 分批下载批次大小（每批处理多少只股票后暂停）
BATCH_SIZE = 50

# 单只股票下载失败后的重试次数
RETRY_COUNT = 3

# 重试等待基数（秒），实际等待 = base * 2^retry
RETRY_WAIT_BASE = 2.0

# 默认下载年数
DEFAULT_YEARS = 10

# ==================== 定时更新配置 ====================

AUTO_UPDATE_HOUR = 15
AUTO_UPDATE_MINUTE = 30
ENABLE_AUTO_UPDATE = False

# ==================== 日志配置 ====================

LOG_LEVEL = 'INFO'
LOG_FILE = './logs/astock_system.log'

# ==================== 性能配置 ====================

# 每次查询返回的最大记录数
MAX_QUERY_ROWS = 100000

# Streamlit 数据预览行数
PREVIEW_ROWS = 100

# ==================== 外部 Provider 配置 ====================

QVERIS_CONFIG = {
    'enabled': os.getenv('QVERIS_ENABLED', '1') == '1',
    'api_key': os.getenv('QVERIS_API_KEY', ''),
    'base_url': os.getenv('QVERIS_BASE_URL', 'https://qveris.ai/api/v1'),
    'timeout': int(os.getenv('QVERIS_TIMEOUT', '40')),
}


def get_database_url(host=None, port=None, database=None,
                     username=None, password=None):
    """
    获取数据库连接字符串。
    传入参数优先于配置文件中的默认值（用于侧边栏动态配置）。
    """
    if DB_TYPE == 'postgresql':
        h = host or POSTGRESQL_CONFIG['host']
        p = port or POSTGRESQL_CONFIG['port']
        d = database or POSTGRESQL_CONFIG['database']
        u = username or POSTGRESQL_CONFIG['username']
        pw = password or POSTGRESQL_CONFIG['password']
        return f"postgresql+psycopg2://{u}:{pw}@{h}:{p}/{d}"
    else:
        return f"sqlite:///{SQLITE_CONFIG['db_path']}"
