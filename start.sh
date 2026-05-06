#!/bin/bash
# A股数据下载系统启动脚本

cd "$(dirname "$0")"

echo "======================================"
echo "   A股数据下载与可视化系统"
echo "======================================"
echo ""

# 检查依赖
echo "检查依赖..."
python3 -c "import streamlit, pandas, plotly, adata, sqlalchemy, apscheduler" 2>/dev/null

if [ $? -ne 0 ]; then
    echo "正在安装依赖..."
    pip install -r requirements.txt -q
fi

echo "✓ 依赖检查完成"
echo ""

# 停止可能存在的旧进程
pkill -f "streamlit run app.py" 2>/dev/null
sleep 1

echo "启动系统..."
echo "请在浏览器中访问: http://localhost:8501"
echo ""

# 启动Streamlit（无头模式，避免交互式提示）
streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false \
    --server.maxUploadSize=200 \
    > /dev/null 2>&1 &

# 等待启动
sleep 3

# 检查是否成功启动
if ss -tlnp | grep -q ":8501"; then
    echo "✓ 系统启动成功！"
    echo ""
    echo "访问地址:"
    echo "  - 本地: http://localhost:8501"
    echo "  - 局域网: http://$(hostname -I | awk '{print $1}'):8501"
    echo ""
    echo "按 Ctrl+C 停止日志输出（服务会继续在后台运行）"
    echo "使用 ./stop.sh 停止服务"
    echo ""
    # 显示日志
    tail -f /tmp/streamlit.log 2>/dev/null || echo "服务已启动"
else
    echo "✗ 启动失败，请检查日志"
fi