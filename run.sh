#!/bin/bash
cd "$(dirname "$0")"

# 停止旧进程
pkill -f "streamlit run" 2>/dev/null
sleep 2

echo "🚀 启动A股数据系统..."
echo ""

# 在后台启动
nohup streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --browser.gatherUsageStats=false \
    > streamlit.log 2>&1 &

sleep 3

# 检查是否启动成功
if ss -tlnp | grep -q ":8501"; then
    echo "✅ 系统启动成功！"
    echo ""
    echo "🌐 访问地址："
    echo "   本地: http://localhost:8501"
    echo "   网络: http://$(hostname -I | awk '{print $1}'):8501"
    echo ""
    echo "📊 查看日志: tail -f streamlit.log"
    echo "🛑 停止服务: pkill -f 'streamlit run'"
else
    echo "❌ 启动失败，查看日志："
    tail -20 streamlit.log
fi
