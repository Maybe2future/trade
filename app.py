# -*- coding: utf-8 -*-
"""
A股数据管理系统 — Streamlit 主应用
模块化设计：UI 与 Data Engine 完全分离
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import (
    DB_TYPE, get_database_url, POSTGRESQL_CONFIG,
    POOL_SIZE, MAX_OVERFLOW, POOL_RECYCLE, DEFAULT_YEARS, PREVIEW_ROWS,
    DOWNLOAD_PARALLEL_WORKERS,
)

# ─────────────────────────────────────────────────────────
# 页面配置
# ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="A股数据管理系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────
# CSS 深色主题
# ─────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #1a1a2e; }
    .main-header {
        font-size: 2.2rem; font-weight: bold; color: #00d4ff;
        text-align: center; margin-bottom: 1.5rem;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
    }
    .sub-header {
        font-size: 1.4rem; font-weight: bold; color: #fff;
        background-color: #16213e; padding: 10px; border-radius: 5px;
        border-left: 4px solid #00d4ff; margin: 1rem 0;
    }
    .metric-card {
        background: linear-gradient(135deg, #16213e 0%, #1a1a2e 100%);
        padding: 1.2rem; border-radius: 0.8rem;
        border-left: 4px solid #00d4ff;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3); margin-bottom: 1rem;
    }
    .metric-card h3 { color: #00d4ff; margin-bottom: 0.3rem; }
    .metric-card p { color: #e0e0e0; line-height: 1.5; }
    .success-text { color: #00ff88; font-weight: bold; }
    .error-text   { color: #ff6b6b; font-weight: bold; }
    [data-testid="stSidebar"] { background-color: #16213e; }
    [data-testid="stSidebar"] .stMarkdown { color: #e0e0e0; }
    .stButton > button {
        background: linear-gradient(135deg, #0f3460, #1a1a2e);
        color: #fff; border: 2px solid #00d4ff; border-radius: 8px;
        padding: 8px 18px; font-weight: bold;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #00d4ff, #0f3460);
        color: #1a1a2e;
    }
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input {
        background-color: #16213e; color: #fff;
        border: 2px solid #0f3460; border-radius: 5px;
    }
    p, span, label { color: #e0e0e0; }
    h1, h2, h3, h4, h5, h6 { color: #fff; }
    code { background-color: #0f3460; color: #00ff88;
           padding: 2px 6px; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# 数据库 & 下载器初始化（session_state 缓存）
# ─────────────────────────────────────────────────────────
def _init_db():
    """根据侧边栏参数（如有）创建 / 重建数据库连接"""
    sb = st.session_state
    url = get_database_url(
        host=sb.get('db_host'),
        port=sb.get('db_port'),
        database=sb.get('db_name'),
        username=sb.get('db_user'),
        password=sb.get('db_pass'),
    )
    from core.postgresql_db import PostgreSQLStockDB
    db = PostgreSQLStockDB(
        connection_string=url,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_recycle=POOL_RECYCLE,
    )
    return db


def _get_db():
    if 'db' not in st.session_state:
        st.session_state.db = _init_db()
    return st.session_state.db


def _get_downloader():
    if 'downloader' not in st.session_state:
        from core.downloader import StockDownloader
        st.session_state.downloader = StockDownloader(_get_db())
    return st.session_state.downloader


# ─────────────────────────────────────────────────────────
# 侧边栏
# ─────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.markdown("## 📊 A股数据管理系统")
        st.markdown("---")

        # ── 数据库连接配置 ──
        with st.expander("🔧 数据库连接", expanded=False):
            st.text_input("Host", value=POSTGRESQL_CONFIG['host'],
                          key='db_host')
            st.number_input("Port", value=POSTGRESQL_CONFIG['port'],
                            min_value=1, max_value=65535, key='db_port')
            st.text_input("Database", value=POSTGRESQL_CONFIG['database'],
                          key='db_name')
            st.text_input("User", value=POSTGRESQL_CONFIG['username'],
                          key='db_user')
            st.text_input("Password", value=POSTGRESQL_CONFIG['password'],
                          type='password', key='db_pass')
            if st.button("🔄 重新连接", key='btn_reconnect'):
                st.session_state.pop('db', None)
                st.session_state.pop('downloader', None)
                st.rerun()

        # ── CSV 导出路径 ──
        st.text_input("📁 CSV 导出路径", value="./data/csv_export",
                      key='csv_export_path')

        st.markdown("---")

        # ── 导航 ──
        page = st.radio(
            "选择功能",
            ["📊 状态概览", "📥 数据下载", "🔄 增量更新",
             "💰 财务数据", "📈 指数行情", "🏷️ 概念板块", "⚡ 实时行情",
             "🔍 数据预览", "📋 同步日志", "⚙️ 系统设置"],
        )

        st.markdown("---")

        # ── 快速统计 ──
        try:
            stats = _get_db().get_statistics()
            st.metric("股票总数", stats['total_stocks'])
            st.metric("已下载", stats['downloaded_stocks'])
            st.metric("总记录", f"{stats['total_history_records']:,}")
            st.metric("最近更新", stats.get('last_update', '无'))
            # 新增数据类型统计
            try:
                fin_stats = _get_db().get_financial_stats()
                idx_stats = _get_db().get_index_stats()
                concept_stats = _get_db().get_concept_stats()
                realtime_stats = _get_db().get_realtime_stats()
                st.metric("财务数据", f"{fin_stats['total_stocks']} 只")
                st.metric("指数数据", f"{idx_stats['total_indices']} 个")
                st.metric("概念板块", f"{concept_stats['total_concepts']} 个")
                st.metric("实时快照", f"{realtime_stats['total_records']} 条")
            except Exception:
                pass
        except Exception:
            st.info("数据库未初始化")

        st.markdown("---")
        st.caption("基于 AData · PostgreSQL · Streamlit")

    return page


# ═══════════════════════════════════════════════════════════
# 📊 状态概览
# ═══════════════════════════════════════════════════════════
def page_overview():
    st.markdown('<div class="main-header">📈 A股数据管理系统</div>',
                unsafe_allow_html=True)

    db = _get_db()

    # ── 初始化按钮 ──
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("🗄️ 初始化数据库", use_container_width=True):
            with st.spinner("正在初始化表结构..."):
                db.init_tables()
            st.success("✓ 数据库表初始化完成")
    with col_b:
        if st.button("📥 同步股票列表", use_container_width=True):
            with st.spinner("正在从 adata 获取全市场股票列表..."):
                dl = _get_downloader()
                df = dl.fetch_all_stocks()
            if not df.empty:
                st.success(f"✓ 同步完成: {len(df)} 只股票")
            else:
                st.error("✗ 获取股票列表失败")
    with col_c:
        if st.button("📊 刷新统计", use_container_width=True):
            st.rerun()

    st.markdown("---")

    # ── 统计卡片 ──
    try:
        stats = db.get_statistics()
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f"""<div class="metric-card">
                <h3>📋 股票池</h3>
                <p style="font-size:2rem;">{stats['total_stocks']}</p>
                <p>只股票</p></div>""", unsafe_allow_html=True)
        with c2:
            st.markdown(f"""<div class="metric-card">
                <h3>📥 已下载</h3>
                <p style="font-size:2rem;">{stats['downloaded_stocks']}</p>
                <p>只有日线数据</p></div>""", unsafe_allow_html=True)
        with c3:
            st.markdown(f"""<div class="metric-card">
                <h3>📊 总记录</h3>
                <p style="font-size:2rem;">{stats['total_history_records']:,}</p>
                <p>条日线数据</p></div>""", unsafe_allow_html=True)
        with c4:
            st.markdown(f"""<div class="metric-card">
                <h3>💾 磁盘</h3>
                <p style="font-size:2rem;">{stats.get('database_size','N/A')}</p>
                <p>数据范围: {stats['date_range']}</p></div>""",
                        unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"无法获取统计信息: {e}")
        st.info('请先点击上方"初始化数据库"和"同步股票列表"按钮')


# ═══════════════════════════════════════════════════════════
# 📥 数据下载
# ═══════════════════════════════════════════════════════════
def page_download():
    st.markdown('<div class="sub-header">📥 数据下载控制台</div>',
                unsafe_allow_html=True)

    db = _get_db()
    dl = _get_downloader()
    dl.reset_stop()

    # ── 下载模式 ──
    mode = st.radio("下载模式",
                    ["全量下载", "按行业下载", "按指定代码下载"],
                    horizontal=True)

    # ── 日期范围 ──
    col1, col2 = st.columns(2)
    with col1:
        years = st.slider("下载年数", 1, 20, DEFAULT_YEARS)
    with col2:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=years * 365)
        st.markdown(f"**时间范围**: `{start_dt.strftime('%Y-%m-%d')}` "
                    f"~ `{end_dt.strftime('%Y-%m-%d')}`")

    # ── 存储模式 ──
    store_mode = st.radio("存储模式", ["仅数据库", "数据库 + CSV"], horizontal=True)
    csv_path = st.session_state.get('csv_export_path') if "CSV" in store_mode else None

    # ── 选择股票 ──
    stock_codes = []

    if mode == "全量下载":
        try:
            all_stocks = db.get_stock_basic()
            if all_stocks.empty:
                st.warning('股票列表为空,请先在"状态概览"页同步股票列表')
                return
            stock_codes = all_stocks['stock_code'].tolist()
            st.info(f"将下载全部 **{len(stock_codes)}** 只股票的 {years} 年后复权日线数据")
        except Exception:
            st.warning("请先初始化数据库并同步股票列表")
            return

    elif mode == "按行业下载":
        try:
            industries = db.get_industries()
            if not industries:
                st.warning('暂无行业信息,请先同步股票列表')
                return
            selected_ind = st.selectbox("选择行业", industries)
            ind_stocks = db.get_stock_basic_by_industry(selected_ind)
            stock_codes = ind_stocks['stock_code'].tolist()
            st.info(f"行业 **{selected_ind}** 共 {len(stock_codes)} 只股票")
            with st.expander("查看股票列表"):
                st.dataframe(ind_stocks[['stock_code', 'short_name']])
        except Exception as e:
            st.warning(f"获取行业信息失败: {e}")
            return

    elif mode == "按指定代码下载":
        codes_input = st.text_area(
            "输入股票代码（逗号或换行分隔）",
            value="000001, 600000, 000858, 300750, 600519",
            height=80,
        )
        if codes_input:
            stock_codes = [c.strip() for c in
                           codes_input.replace('\n', ',').split(',')
                           if c.strip()]
        st.info(f"已选择 **{len(stock_codes)}** 只股票")

    # ── 开始下载 ──
    if stock_codes and st.button("🚀 开始下载", type="primary"):
        start_date = start_dt.strftime('%Y-%m-%d')
        end_date = end_dt.strftime('%Y-%m-%d')

        progress_bar = st.progress(0)
        status_text = st.empty()
        log_container = st.empty()

        logs = []

        def update_progress(msg, progress=None):
            logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            status_text.text(msg)
            if progress is not None:
                progress_bar.progress(min(progress, 1.0))
            # 显示最近 20 条日志
            log_container.code('\n'.join(logs[-20:]), language='text')

        dl.set_progress_callback(update_progress)

        with st.spinner("正在下载..."):
            result = dl.download_batch(
                stock_codes, start_date, end_date,
                csv_path=csv_path,
            )

        progress_bar.progress(1.0)

        # ── 结果汇总 ──
        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("总数", result['total'])
        c2.metric("成功", result['success'])
        c3.metric("失败", result['failed'])
        c4.metric("总记录", f"{result['records']:,}")

        if result['failed'] > 0 and result.get('errors'):
            with st.expander(f"⚠️ 查看 {result['failed']} 个失败详情"):
                st.dataframe(pd.DataFrame(result['errors']))

        if result['success'] > 0:
            st.success(f"✓ 下载完成！成功 {result['success']} 只，"
                       f"共 {result['records']:,} 条记录")


# ═══════════════════════════════════════════════════════════
# 🔄 增量更新
# ═══════════════════════════════════════════════════════════
def page_incremental_update():
    st.markdown('<div class="sub-header">🔄 增量更新</div>',
                unsafe_allow_html=True)

    db = _get_db()
    dl = _get_downloader()
    dl.reset_stop()

    st.markdown("系统将自动识别每只股票的**最后交易日期**，仅抓取新增数据。")

    # ── 更新范围 ──
    scope = st.radio("更新范围", ["全部已下载股票", "选择股票"], horizontal=True)

    selected = None
    if scope == "选择股票":
        downloaded = db.get_downloaded_stocks()
        if not downloaded:
            st.warning("暂无已下载的股票")
            return
        selected = st.multiselect("选择要更新的股票", downloaded,
                                  default=downloaded[:10])

    if st.button("🚀 开始增量更新", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        log_container = st.empty()
        logs = []

        def update_progress(msg, progress=None):
            logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
            status_text.text(msg)
            if progress is not None:
                progress_bar.progress(min(progress, 1.0))
            log_container.code('\n'.join(logs[-20:]), language='text')

        dl.set_progress_callback(update_progress)

        with st.spinner("正在增量更新..."):
            result = dl.update_incremental(selected)

        progress_bar.progress(1.0)

        c1, c2, c3 = st.columns(3)
        c1.metric("已更新", result['updated'])
        c2.metric("跳过", result['skipped'])
        c3.metric("失败", result['failed'])

        if result['updated'] > 0:
            st.success(f"✓ 增量更新完成：{result['updated']} 只股票已更新")
        else:
            st.info("所有股票均已是最新数据")


# ═══════════════════════════════════════════════════════════
# 🔍 数据预览
# ═══════════════════════════════════════════════════════════
def page_preview():
    st.markdown('<div class="sub-header">🔍 数据预览与验证</div>',
                unsafe_allow_html=True)

    db = _get_db()

    # ── 股票代码输入 ──
    col1, col2 = st.columns([2, 3])
    with col1:
        stock_code = st.text_input("输入股票代码", value="000001",
                                   help="输入 6 位代码，如 000001")

    if not stock_code:
        return

    # ── 验证信息 ──
    info = db.verify_stock_data(stock_code)

    with col2:
        if info['count'] > 0:
            st.success(
                f"✅ 代码 **{stock_code}** 已入库 **{info['count']}** 条记录，"
                f"覆盖范围 **{info['min_date']}** ~ **{info['max_date']}**"
            )
        else:
            st.warning(f"⚠️ 代码 {stock_code} 暂无数据")

            dl = _get_downloader()
            if st.button(f"📥 快速下载 {stock_code} (近3年)"):
                start = (datetime.now() - timedelta(days=3*365)).strftime('%Y-%m-%d')
                with st.spinner(f"正在下载 {stock_code}..."):
                    ok, records, msg = dl.download_stock_history(stock_code, start)
                if ok:
                    st.success(f"✓ 下载成功: {records} 条 — {msg}")
                    st.rerun()
                else:
                    st.error(f"✗ 下载失败: {msg}")
            return

    # ── 股票基本信息 ──
    basic = db.get_stock_basic(stock_code)
    if not basic.empty:
        row = basic.iloc[0]
        cols = st.columns(4)
        cols[0].markdown(f"**名称**: {row.get('short_name', '')}")
        cols[1].markdown(f"**交易所**: {row.get('exchange', '')}")
        cols[2].markdown(f"**行业**: {row.get('industry', '未知')}")
        cols[3].markdown(f"**上市日期**: {row.get('list_date', '')}")

    st.markdown("---")

    # ── 数据表格预览 ──
    tab_table, tab_chart = st.tabs(["📋 数据表格", "📈 K线图"])

    with tab_table:
        df = db.get_daily_hfq(stock_code, limit=PREVIEW_ROWS)
        if not df.empty:
            st.markdown(f"显示最近 **{len(df)}** 条记录（按日期倒序）")
            st.dataframe(df, use_container_width=True, height=400)
        else:
            st.info("无数据")

    with tab_chart:
        df_chart = db.get_daily_hfq(stock_code)
        if df_chart.empty:
            st.info("无数据")
            return

        # 按日期正序
        df_chart = df_chart.sort_values('trade_date')

        period = st.selectbox("显示周期", ["全部", "1年", "6个月", "3个月", "1个月"])
        if period != "全部":
            days_map = {"1年": 365, "6个月": 180, "3个月": 90, "1个月": 30}
            cutoff = (datetime.now() - timedelta(
                days=days_map[period])).strftime('%Y-%m-%d')
            df_chart = df_chart[df_chart['trade_date'].astype(str) >= cutoff]

        if df_chart.empty:
            st.info("该周期内无数据")
            return

        # K线 + 成交量
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            vertical_spacing=0.03, row_heights=[0.7, 0.3])

        fig.add_trace(go.Candlestick(
            x=df_chart['trade_date'],
            open=df_chart['open'], high=df_chart['high'],
            low=df_chart['low'], close=df_chart['close'],
            name='K线',
        ), row=1, col=1)

        colors = ['#ef5350' if c >= o else '#26a69a'
                  for c, o in zip(df_chart['close'], df_chart['open'])]
        fig.add_trace(go.Bar(
            x=df_chart['trade_date'], y=df_chart['volume'],
            marker_color=colors, name='成交量',
        ), row=2, col=1)

        fig.update_layout(
            title=f'{stock_code} 后复权 K线图',
            xaxis_rangeslider_visible=False,
            height=550,
            template='plotly_dark',
        )
        st.plotly_chart(fig, use_container_width=True)

        # 导出
        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            csv_data = df_chart.to_csv(index=False, encoding='utf-8-sig')
            st.download_button("⬇️ 导出 CSV", csv_data,
                               file_name=f"{stock_code}_hfq.csv",
                               mime='text/csv')

# ═══════════════════════════════════════════════════════════
# 💰 财务数据
# ═══════════════════════════════════════════════════════════
def page_financial():
    st.markdown('<div class="sub-header">💰 财务数据（核心指标）</div>',
                unsafe_allow_html=True)

    db = _get_db()
    dl = _get_downloader()
    dl.reset_stop()

    tab_download, tab_browse = st.tabs(["📥 下载财务数据", "🔍 查看财务数据"])

    # ── 下载 ──
    with tab_download:
        st.markdown("""
        从东方财富获取上市公司**核心财务指标**：EPS、ROE、毛利率、净利率、资产负债率等。
        数据按年报/中报/季报分期。
        """)
        st.caption(
            f"每次仍请求接口返回该股**全部报告期**，数据库按报告期 **UPSERT** 更新；"
            f"并发线程数见 `config.DOWNLOAD_PARALLEL_WORKERS`（当前 **{DOWNLOAD_PARALLEL_WORKERS}**，"
            f"为 1 即串行）。"
        )

        dl_mode = st.radio("下载模式", ["按指定代码", "按行业", "全量下载"],
                           horizontal=True, key='fin_dl_mode')

        stock_codes = []

        if dl_mode == "按指定代码":
            codes_input = st.text_area(
                "输入股票代码（逗号或换行分隔）",
                value="000001, 600000, 000858, 300750, 600519",
                height=80, key='fin_codes',
            )
            if codes_input:
                stock_codes = [c.strip() for c in
                               codes_input.replace('\n', ',').split(',')
                               if c.strip()]
        elif dl_mode == "按行业":
            try:
                industries = db.get_industries()
                if industries:
                    selected_ind = st.selectbox("选择行业", industries,
                                                key='fin_industry')
                    ind_stocks = db.get_stock_basic_by_industry(selected_ind)
                    stock_codes = ind_stocks['stock_code'].tolist()
                    st.info(f"行业 **{selected_ind}** 共 {len(stock_codes)} 只股票")
            except Exception:
                st.warning("请先同步股票列表")
        elif dl_mode == "全量下载":
            try:
                all_stocks = db.get_stock_basic()
                stock_codes = all_stocks['stock_code'].tolist()
                st.warning(f"将下载全部 **{len(stock_codes)}** 只股票的财务数据，耗时较长")
            except Exception:
                st.warning("请先同步股票列表")

        if stock_codes:
            st.info(f"已选择 **{len(stock_codes)}** 只股票")

        if stock_codes and st.button("🚀 开始下载财务数据", type="primary",
                                     key='btn_dl_fin'):
            progress_bar = st.progress(0)
            status_text = st.empty()
            log_container = st.empty()
            logs = []

            def update_progress(msg, progress=None):
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                status_text.text(msg)
                if progress is not None:
                    progress_bar.progress(min(progress, 1.0))
                log_container.code('\n'.join(logs[-20:]), language='text')

            dl.set_progress_callback(update_progress)

            with st.spinner("正在下载财务数据..."):
                result = dl.download_financial_batch(stock_codes)

            progress_bar.progress(1.0)

            c1, c2, c3 = st.columns(3)
            c1.metric("成功", result['success'])
            c2.metric("失败", result['failed'])
            c3.metric("总记录", f"{result['records']:,}")

            if result['success'] > 0:
                st.success(f"✓ 下载完成！{result['success']} 只股票财务数据入库")

    # ── 查看 ──
    with tab_browse:
        stock_code = st.text_input("输入股票代码", value="000001",
                                   key='fin_view_code')

        if stock_code:
            try:
                fin_df = db.get_financial(stock_code)
                if fin_df.empty:
                    st.info(f"代码 {stock_code} 暂无财务数据，请先下载")
                else:
                    st.markdown(f"**{stock_code}** 共 {len(fin_df)} 期财务数据")

                    # 关键指标趋势图
                    fin_df = fin_df.sort_values('report_date')
                    metric = st.selectbox("选择指标", [
                        'basic_eps', 'roe_wtd', 'gross_margin', 'net_margin',
                        'total_rev', 'net_profit_attr_sh', 'asset_liab_ratio',
                    ], format_func=lambda x: {
                        'basic_eps': '基本每股收益',
                        'roe_wtd': '加权ROE(%)',
                        'gross_margin': '毛利率(%)',
                        'net_margin': '净利率(%)',
                        'total_rev': '营业总收入',
                        'net_profit_attr_sh': '归母净利润',
                        'asset_liab_ratio': '资产负债率(%)',
                    }.get(x, x))

                    if metric in fin_df.columns:
                        fig = go.Figure()
                        fig.add_trace(go.Bar(
                            x=fin_df['report_date'].astype(str),
                            y=pd.to_numeric(fin_df[metric], errors='coerce'),
                            marker_color='#00d4ff',
                        ))
                        fig.update_layout(
                            title=f"{stock_code} 财务指标趋势",
                            template='plotly_dark', height=400,
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    st.dataframe(fin_df, use_container_width=True, height=400)
            except Exception as e:
                st.error(f"查询失败: {e}")

        # 统计
        st.markdown("---")
        try:
            stats = db.get_financial_stats()
            c1, c2, c3 = st.columns(3)
            c1.metric("覆盖股票", stats['total_stocks'])
            c2.metric("总记录", f"{stats['total_records']:,}")
            c3.metric("数据范围", stats['date_range'])
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 📈 指数行情
# ═══════════════════════════════════════════════════════════
def page_index():
    st.markdown('<div class="sub-header">📈 指数行情数据</div>',
                unsafe_allow_html=True)

    db = _get_db()
    dl = _get_downloader()
    dl.reset_stop()

    tab_download, tab_browse = st.tabs(["📥 下载指数数据", "🔍 查看指数数据"])

    # ── 下载 ──
    with tab_download:
        st.markdown("""
        下载A股常用指数的日线行情数据：上证指数、深证成指、创业板指、沪深300、中证500等。
        """)
        st.caption(
            f"默认**增量**：从库里该指数最后交易日续拉到今日；入库按交易日 **UPSERT**。"
            f" 多指数并发线程数：`DOWNLOAD_PARALLEL_WORKERS` = **{DOWNLOAD_PARALLEL_WORKERS}**。"
        )

        # 显示默认指数列表
        from core.downloader import StockDownloader
        default_idx = StockDownloader.DEFAULT_INDICES
        st.markdown("**默认指数列表：**")
        idx_info_df = pd.DataFrame([
            {'代码': k, '名称': v} for k, v in default_idx.items()
        ])
        st.dataframe(idx_info_df, use_container_width=True, height=200)

        # 额外指数
        extra_input = st.text_area(
            "额外指数（格式: 代码:名称，逗号分隔）",
            placeholder="如: 000016:上证50, 399005:中小板指",
            height=60, key='idx_extra',
        )
        extra_indices = {}
        if extra_input:
            for item in extra_input.split(','):
                parts = item.strip().split(':')
                if len(parts) == 2:
                    extra_indices[parts[0].strip()] = parts[1].strip()

        start_date = st.date_input("起始日期", value=datetime(2015, 1, 1),
                                   key='idx_start')
        # 默认增量：从库里该指数最后交易日续拉；勾选则从起始日全量请求（UPSERT 覆盖）
        idx_full_refresh = st.checkbox(
            "强制全量（忽略库中最新日期，从上方起始日重新拉）",
            value=False,
            key='idx_full_refresh',
        )

        if st.button("🚀 下载全部指数", type="primary", key='btn_dl_idx'):
            progress_bar = st.progress(0)
            status_text = st.empty()
            log_container = st.empty()
            logs = []

            def update_progress(msg, progress=None):
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                status_text.text(msg)
                if progress is not None:
                    progress_bar.progress(min(progress, 1.0))
                log_container.code('\n'.join(logs[-20:]), language='text')

            dl.set_progress_callback(update_progress)

            with st.spinner("正在下载指数数据..."):
                result = dl.download_all_indices(
                    start_date=start_date.strftime('%Y-%m-%d'),
                    extra_indices=extra_indices if extra_indices else None,
                    incremental=not idx_full_refresh,
                )

            progress_bar.progress(1.0)

            c1, c2, c3 = st.columns(3)
            c1.metric("总数", result['total'])
            c2.metric("成功", result['success'])
            c3.metric("失败", result['failed'])

            if result['success'] > 0:
                st.success(f"✓ {result['success']} 个指数数据下载完成！")

    # ── 查看 ──
    with tab_browse:
        try:
            downloaded = db.get_downloaded_indices()
        except Exception:
            downloaded = []

        if not downloaded:
            st.info("暂无指数数据，请先下载")
        else:
            from core.downloader import StockDownloader
            default_idx = StockDownloader.DEFAULT_INDICES
            index_code = st.selectbox("选择指数", downloaded,
                                      format_func=lambda x: f"{x} - {default_idx.get(x, x)}",
                                      key='idx_view')

            if index_code:
                idx_df = db.get_index_daily(index_code)
                if idx_df.empty:
                    st.info("无数据")
                else:
                    st.markdown(f"**{index_code}** 共 {len(idx_df)} 条记录")

                    # K线图
                    idx_df = idx_df.sort_values('trade_date')

                    period = st.selectbox("显示周期",
                                          ["全部", "1年", "6个月", "3个月"],
                                          key='idx_period')
                    if period != "全部":
                        days_map = {"1年": 365, "6个月": 180, "3个月": 90}
                        cutoff = (datetime.now() - timedelta(
                            days=days_map[period])).strftime('%Y-%m-%d')
                        idx_df = idx_df[idx_df['trade_date'].astype(str) >= cutoff]

                    if not idx_df.empty:
                        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                            vertical_spacing=0.03,
                                            row_heights=[0.7, 0.3])

                        fig.add_trace(go.Candlestick(
                            x=idx_df['trade_date'],
                            open=idx_df['open'], high=idx_df['high'],
                            low=idx_df['low'], close=idx_df['close'],
                            name='K线',
                        ), row=1, col=1)

                        fig.add_trace(go.Bar(
                            x=idx_df['trade_date'], y=idx_df['volume'],
                            marker_color='#0f3460', name='成交量',
                        ), row=2, col=1)

                        fig.update_layout(
                            title=f'{index_code} 指数K线',
                            xaxis_rangeslider_visible=False,
                            height=550, template='plotly_dark',
                        )
                        st.plotly_chart(fig, use_container_width=True)

                    st.dataframe(idx_df, use_container_width=True, height=400)

        # 统计
        st.markdown("---")
        try:
            stats = db.get_index_stats()
            c1, c2, c3 = st.columns(3)
            c1.metric("指数数量", stats['total_indices'])
            c2.metric("总记录", f"{stats['total_records']:,}")
            c3.metric("数据范围", stats['date_range'])
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 🏷️ 概念板块
# ═══════════════════════════════════════════════════════════
def page_concept():
    st.markdown('<div class="sub-header">🏷️ 概念板块数据</div>',
                unsafe_allow_html=True)

    db = _get_db()
    dl = _get_downloader()
    dl.reset_stop()

    tab_sync, tab_browse = st.tabs(["📥 同步概念板块", "🔍 查看概念板块"])

    with tab_sync:
        st.caption(
            "概念列表与成分股均为**整表同步**：列表 UPSERT；每个概念的成分股先删后插全量替换，"
            "不是按日期增量。"
        )
        sync_constituents = st.checkbox("同步成分股", value=True)
        limit = st.number_input(
            "同步成分股的概念数量上限（0 表示全部）",
            min_value=0, max_value=5000, value=100, step=10,
        )
        if st.button("🚀 开始同步概念板块", type="primary", key='btn_sync_concept'):
            progress_bar = st.progress(0)
            status_text = st.empty()
            log_container = st.empty()
            logs = []

            def update_progress(msg, progress=None):
                logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
                status_text.text(msg)
                if progress is not None:
                    progress_bar.progress(min(progress, 1.0))
                log_container.code('\n'.join(logs[-20:]), language='text')

            dl.set_progress_callback(update_progress)
            with st.spinner("正在同步概念板块..."):
                result = dl.sync_concept_boards(
                    sync_constituents=sync_constituents,
                    limit=None if limit == 0 else int(limit),
                )
            progress_bar.progress(1.0)

            c1, c2, c3 = st.columns(3)
            c1.metric("概念数量", result['concepts'])
            c2.metric("成分股记录", result['constituents'])
            c3.metric("成分股失败概念", result['failed_constituents'])

    with tab_browse:
        concept_df = db.get_concept_boards()
        if concept_df.empty:
            st.info("暂无概念板块数据，请先同步")
        else:
            concept_code = st.selectbox(
                "选择概念",
                concept_df['concept_code'].tolist(),
                format_func=lambda x: (
                    f"{x} - {concept_df.loc[concept_df['concept_code'] == x, 'concept_name'].iloc[0]}"
                ),
            )
            if concept_code:
                cons_df = db.get_concept_constituents(concept_code)
                st.markdown(f"**{concept_code}** 成分股 {len(cons_df)} 只")
                st.dataframe(cons_df, use_container_width=True, height=420)

        st.markdown("---")
        try:
            stats = db.get_concept_stats()
            c1, c2, c3 = st.columns(3)
            c1.metric("概念数量", stats['total_concepts'])
            c2.metric("成分股记录", stats['total_constituents'])
            c3.metric("最近更新", stats['last_update'])
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# ⚡ 实时行情
# ═══════════════════════════════════════════════════════════
def page_realtime():
    st.markdown('<div class="sub-header">⚡ 实时行情快照</div>',
                unsafe_allow_html=True)

    db = _get_db()
    dl = _get_downloader()
    dl.reset_stop()

    mode = st.radio("股票范围", ["手动输入", "已下载股票前N只"], horizontal=True)
    stock_codes = []

    if mode == "手动输入":
        codes_input = st.text_area(
            "输入股票代码（逗号或换行分隔）",
            value="000001, 600000, 000858, 300750, 600519",
            height=80,
            key='realtime_codes',
        )
        if codes_input:
            stock_codes = [c.strip() for c in codes_input.replace('\n', ',').split(',') if c.strip()]
    else:
        downloaded = db.get_downloaded_stocks()
        top_n = st.slider("抓取前 N 只", 10, 500, 50, 10)
        stock_codes = downloaded[:top_n]
        st.info(f"将抓取已下载股票中的前 {len(stock_codes)} 只")

    if stock_codes and st.button("🚀 获取实时行情", type="primary", key='btn_realtime'):
        with st.spinner("正在获取实时行情..."):
            result = dl.download_realtime_quotes(stock_codes)
        c1, c2, c3 = st.columns(3)
        c1.metric("请求股票数", result['total'])
        c2.metric("保存条数", result['saved'])
        c3.metric("失败估计", result['failed'])
        if result['saved'] > 0:
            st.success(result['message'])
        else:
            st.warning(result['message'])

    st.markdown("---")
    latest_df = db.get_latest_realtime_snapshot(limit=300)
    if latest_df.empty:
        st.info("暂无实时行情快照")
    else:
        st.dataframe(latest_df, use_container_width=True, height=420)

    try:
        stats = db.get_realtime_stats()
        c1, c2, c3 = st.columns(3)
        c1.metric("快照条数", stats['total_records'])
        c2.metric("覆盖股票", stats['total_stocks'])
        c3.metric("最近快照", stats['last_snapshot'])
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# 📋 同步日志
# ═══════════════════════════════════════════════════════════
def page_sync_log():
    st.markdown('<div class="sub-header">📋 同步日志</div>',
                unsafe_allow_html=True)

    db = _get_db()

    limit = st.selectbox("显示条数", [50, 100, 200, 500], index=1)

    try:
        logs_df = db.get_sync_logs(limit=limit)
        if logs_df.empty:
            st.info("暂无同步日志")
            return

        # ── 统计 ──
        c1, c2, c3 = st.columns(3)
        c1.metric("总任务数", len(logs_df))
        succ = logs_df[logs_df['status'] == 'success'].shape[0]
        fail = logs_df[logs_df['status'] == 'failed'].shape[0]
        c2.metric("成功", succ)
        c3.metric("失败", fail)

        st.dataframe(logs_df, use_container_width=True, height=500)

    except Exception as e:
        st.error(f"获取日志失败: {e}")
        st.info("请先初始化数据库")


# ═══════════════════════════════════════════════════════════
# ⚙️ 系统设置
# ═══════════════════════════════════════════════════════════
def page_settings():
    st.markdown('<div class="sub-header">⚙️ 系统设置</div>',
                unsafe_allow_html=True)

    db = _get_db()

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 数据库管理")

        if st.button("🗄️ 重新初始化表结构"):
            with st.spinner("初始化中..."):
                db.init_tables()
            st.success("✓ 表结构已重新初始化")

        if st.button("🔧 优化数据库 (ANALYZE)"):
            with st.spinner("优化中..."):
                db.optimize()
            st.success("✓ 数据库已优化")

    with col2:
        st.markdown("#### 系统信息")
        st.markdown(f"**Python 版本**: `{sys.version.split()[0]}`")
        try:
            import adata as _a
            st.markdown(f"**AData 版本**: `{_a.__version__}`")
        except Exception:
            st.markdown("**AData 版本**: 未知")

        st.markdown(f"**数据库类型**: `{DB_TYPE}`")
        st.markdown(f"**连接池大小**: `{POOL_SIZE}` + overflow `{MAX_OVERFLOW}`")

        try:
            stats = db.get_statistics()
            st.markdown("---")
            st.markdown("#### 数据库统计")
            st.markdown(f"- 股票总数: {stats['total_stocks']}")
            st.markdown(f"- 已下载: {stats['downloaded_stocks']} 只")
            st.markdown(f"- 总记录: {stats['total_history_records']:,} 条")
            st.markdown(f"- 磁盘占用: {stats.get('database_size', 'N/A')}")
            st.markdown(f"- 数据范围: {stats['date_range']}")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────
def main():
    page = render_sidebar()

    if page == "📊 状态概览":
        page_overview()
    elif page == "📥 数据下载":
        page_download()
    elif page == "🔄 增量更新":
        page_incremental_update()
    elif page == "💰 财务数据":
        page_financial()
    elif page == "📈 指数行情":
        page_index()
    elif page == "🏷️ 概念板块":
        page_concept()
    elif page == "⚡ 实时行情":
        page_realtime()
    elif page == "🔍 数据预览":
        page_preview()
    elif page == "📋 同步日志":
        page_sync_log()
    elif page == "⚙️ 系统设置":
        page_settings()


if __name__ == '__main__':
    main()
