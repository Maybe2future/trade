# LOM Trade System v2 — 每日深度投资报告

## 模块说明

| 文件 | 功能 |
|------|------|
| `data_enhancement.py` | 数据增强：板块资金/财务摘要/北向资金入库 |
| `sentiment_scanner.py` | 市场情绪扫描（0-100分评分） |
| `sector_rotation.py` | 板块轮动分析（启动/扩散/高潮/退潮） |
| `sector_stock_picker.py` | 热点板块内选股（技术+基本面） |
| `advanced_report_generator.py` | 高级报告生成器（5层深度分析） |
| `generate_report_v2.py` | 入口脚本 |

## 报告架构（5层深度分析）

1. **市场情绪扫描** — 涨跌比/涨跌停/成交额/北向资金
2. **板块轮动分析** — 资金流向TOP10 + 轮动阶段判断
3. **热点板块个股推荐** — 技术+基本面综合评分
4. **重点个股深度分析** — 技术面/基本面/资金面
5. **策略说明与风险提示**

## 使用方法

```bash
python generate_report_v2.py --db ./data/stock_db.sqlite --output ./reports
```

## 依赖

- pandas
- numpy
- akshare（板块资金/财务数据/北向资金）
- sqlite3（内置）

