#!/bin/bash
# 停止A股数据下载系统

echo "停止A股数据下载系统..."

# 查找并停止Streamlit进程
pkill -f "streamlit run app.py" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✓ 系统已停止"
else
    echo "服务未运行"
fi