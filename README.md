# A股数据下载与可视化系统

## 系统架构

```
astock_system/
├── app.py                    # Streamlit主应用（可视化界面）
├── core/
│   ├── __init__.py
│   ├── downloader.py         # 数据下载核心
│   ├── database.py           # 数据库管理
│   └── scheduler.py          # 定时任务
├── data/                     # 数据存储目录
│   ├── stock_db.sqlite       # SQLite数据库
│   └── cache/                # 缓存文件
└── requirements.txt          # 依赖列表
```

## 功能特性

1. **历史数据下载**
   - 支持任意时间范围（10年、5年等）
   - 支持批量下载全市场股票
   - 自动断点续传
   - 多线程加速

2. **实时数据更新**
   - 定时自动更新（交易日15:30后）
   - 手动实时更新
   - 更新进度显示

3. **数据可视化**
   - K线图展示
   - 技术指标分析
   - 数据表格浏览
   - 统计分析

4. **数据管理**
   - 股票池管理
   - 数据完整性检查
   - 数据导出

## 安装依赖

```bash
pip install streamlit pandas plotly sqlalchemy apscheduler adata
```

## 运行系统

```bash
streamlit run app.py
```

## 访问界面

打开浏览器访问: http://localhost:8501

## 使用说明

1. **首次使用**：点击"初始化数据库"创建数据表
2. **下载历史数据**：在"历史数据下载"页面选择股票和时间范围
3. **查看数据**：在"数据可视化"页面查看K线图
4. **自动更新**：在"系统设置"中配置定时更新任务