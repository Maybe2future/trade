# -*- coding: utf-8 -*-
"""
简化版 - A股数据下载系统
用于测试基本功能
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.database import StockDatabase
from core.downloader import StockDownloader

st.set_page_config(page_title="A股数据系统", page_icon="📈", layout="wide")

st.title("📈 A股数据下载与可视化系统")
st.markdown("---")

# 初始化
if 'db' not in st.session_state:
    st.session_state.db = StockDatabase('./data/stock_db.sqlite')
if 'downloader' not in st.session_state:
    st.session_state.downloader = StockDownloader(st.session_state.db)

# 侧边栏
with st.sidebar:
    st.header("系统状态")
    try:
        stats = st.session_state.db.get_statistics()
        st.metric("股票总数", stats['total_stocks'])
        st.metric("已下载", stats['downloaded_stocks'])
        st.metric("历史数据", f"{stats['total_history_records']:,}")
    except:
        st.info("数据库未初始化")
    
    st.markdown("---")
    page = st.radio("功能菜单", ["🏠 首页", "📥 下载数据", "📊 查看数据"])

# 主页面
if page == "🏠 首页":
    st.header("欢迎使用")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("**快速开始**\n\n1. 初始化数据库\n2. 下载股票数据\n3. 查看可视化")
    with col2:
        st.success("**支持功能**\n\n• 10年历史数据\n• 批量下载\n• 自动更新")
    with col3:
        st.warning("**数据源**\n\n• 同花顺\n• 东方财富\n• 新浪财经")
    
    if st.button("🚀 初始化数据库", type="primary"):
        with st.spinner("初始化中..."):
            st.session_state.db.init_tables()
            stocks = st.session_state.downloader.fetch_all_stocks()
            if not stocks.empty:
                st.session_state.db.save_stock_info(stocks)
        st.success("✓ 初始化完成！")
        st.rerun()

elif page == "📥 下载数据":
    st.header("下载股票数据")
    
    tab1, tab2 = st.tabs(["单只股票", "批量下载"])
    
    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            code = st.text_input("股票代码", "000001")
        with col2:
            years = st.slider("下载年数", 1, 20, 5)
        
        if st.button("开始下载", key="single"):
            progress = st.progress(0)
            status = st.empty()
            
            end_date = datetime.now()
            start_date = end_date - pd.DateOffset(years=years)
            
            status.text(f"正在下载 {code}...")
            success, records, msg = st.session_state.downloader.download_stock_history(
                code,
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            )
            
            progress.progress(100)
            
            if success:
                st.success(f"✓ 下载成功！共 {records} 条记录")
            else:
                st.error(f"✗ 下载失败: {msg}")
    
    with tab2:
        codes = st.text_area("股票代码列表（逗号分隔）", "000001, 600000, 000858")
        if st.button("批量下载", key="batch"):
            code_list = [c.strip() for c in codes.split(',')]
            st.info(f"准备下载 {len(code_list)} 只股票...")
            
            result = st.session_state.downloader.download_batch(code_list, '2024-01-01')
            st.success(f"✓ 完成: 成功 {result['success']} 只，共 {result['records']} 条")

elif page == "📊 查看数据":
    st.header("查看股票数据")
    
    stocks = st.session_state.db.get_downloaded_stocks()
    if not stocks:
        st.warning("暂无数据，请先下载")
    else:
        selected = st.selectbox("选择股票", stocks)
        
        if selected:
            df = st.session_state.db.get_history_data(selected)
            st.markdown(f"**{selected}** 共 {len(df)} 条记录")
            
            # 显示K线数据
            st.line_chart(df.set_index('trade_date')[['open', 'close', 'high', 'low']])
            
            # 显示表格
            with st.expander("查看数据表格"):
                st.dataframe(df.sort_values('trade_date', ascending=False))
            
            # 导出
            if st.button("导出CSV"):
                csv = df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="下载文件",
                    data=csv,
                    file_name=f'{selected}_data.csv',
                    mime='text/csv'
                )