# PostgreSQL 数据库配置指南

## 📋 快速开始（3步完成）

### 第1步：安装PostgreSQL

```bash
cd /home/lom/trade/adata
./install_postgresql.sh
```

**安装完成后会得到：**
- ✅ 数据库地址: `localhost`
- ✅ 端口: `5432`
- ✅ 数据库名: `stock_db`
- ✅ 用户名: `stock_user`
- ✅ 密码: `stock_password_123`

### 第2步：修改系统配置

编辑 `/home/lom/trade/adata/astock_system/config.py`：

```python
# 数据库类型选择
DB_TYPE = 'postgresql'  # 可选: 'sqlite' 或 'postgresql'

# PostgreSQL连接配置
DATABASE_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'stock_db',
    'username': 'stock_user',
    'password': 'stock_password_123'
}
```

### 第3步：初始化数据库

```bash
cd /home/lom/trade/adata/astock_system
./run.sh
```

然后在Web界面点击 **"🚀 初始化数据库"** 按钮。

---

## 🔐 账号密码设置说明

### 1. 修改默认密码（推荐）

```bash
# 进入PostgreSQL命令行
sudo -u postgres psql

# 修改密码（将 your_new_password 替换为你自己的密码）
ALTER USER stock_user WITH PASSWORD 'your_new_password';

# 退出
\q
```

### 2. 创建新用户

```bash
sudo -u postgres psql

-- 创建新用户
CREATE USER my_stock_user WITH PASSWORD 'my_secure_password';

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE stock_db TO my_stock_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO my_stock_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO my_stock_user;

-- 退出
\q
```

### 3. 配置文件中修改密码

编辑 `config.py`：

```python
DATABASE_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'stock_db',
    'username': 'my_stock_user',           # 新用户名
    'password': 'my_secure_password'       # 新密码
}
```

---

## 💾 SQLite vs PostgreSQL 对比

| 功能 | SQLite | PostgreSQL |
|------|--------|------------|
| **适用规模** | < 100万条 | > 1亿条 |
| **并发访问** | 单用户 | 多用户同时访问 |
| **数据安全** | 文件级 | 用户权限+事务 |
| **自动备份** | 手动复制文件 | 自动WAL备份 |
| **分区支持** | 不支持 | 自动按月分区 |
| **数据压缩** | 不支持 | 支持（节省90%空间）|
| **远程访问** | 不支持 | 支持 |
| **查询速度** | 快（小数据）| 快（大数据）|

---

## 🔧 高级配置

### 1. 数据库自动备份

创建备份脚本 `backup.sh`：

```bash
#!/bin/bash
# 每天自动备份数据库

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backup/postgresql"
mkdir -p $BACKUP_DIR

# 备份
pg_dump -U stock_user -d stock_db > $BACKUP_DIR/stock_db_$DATE.sql

# 保留最近30天的备份
find $BACKUP_DIR -name "stock_db_*.sql" -mtime +30 -delete

echo "✓ 备份完成: stock_db_$DATE.sql"
```

添加定时任务：
```bash
crontab -e
# 添加以下行（每天凌晨3点备份）
0 3 * * * /home/lom/trade/adata/backup.sh
```

### 2. 远程访问配置

编辑 `/etc/postgresql/14/main/postgresql.conf`：

```conf
# 监听所有IP
listen_addresses = '*'
```

编辑 `/etc/postgresql/14/main/pg_hba.conf`：

```conf
# 允许所有IP访问（生产环境请限制IP）
host    all             all             0.0.0.0/0               scram-sha-256
```

重启服务：
```bash
service postgresql restart
```

### 3. 性能优化配置

编辑 `/etc/postgresql/14/main/postgresql.conf`：

```conf
# 内存配置（根据服务器内存调整）
shared_buffers = 4GB                  # 25% of RAM
effective_cache_size = 12GB           # 75% of RAM
work_mem = 256MB                      # 每个查询操作内存
maintenance_work_mem = 1GB            # 维护操作内存

# WAL配置
wal_buffers = 64MB
min_wal_size = 1GB
max_wal_size = 4GB

# 并发配置
max_connections = 200
```

---

## 🐛 常见问题

### Q1: 忘记密码怎么办？

```bash
# 重置密码
sudo -u postgres psql -c "ALTER USER stock_user WITH PASSWORD 'new_password';"
```

### Q2: 连接失败 "Connection refused"

```bash
# 检查PostgreSQL是否运行
service postgresql status

# 如果没运行，启动它
service postgresql start

# 检查端口
ss -tlnp | grep 5432
```

### Q3: 权限不足 "permission denied"

```bash
sudo -u postgres psql

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE stock_db TO stock_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO stock_user;
\q
```

### Q4: 查看数据库状态

```bash
# 查看连接
sudo -u postgres psql -c "SELECT * FROM pg_stat_activity;"

# 查看数据库大小
sudo -u postgres psql -c "SELECT pg_size_pretty(pg_database_size('stock_db'));"

# 查看表大小
sudo -u postgres psql -d stock_db -c "
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename))
FROM pg_tables
WHERE schemaname='public';
"
```

---

## 📊 数据导入导出

### 导出整个数据库

```bash
pg_dump -U stock_user -d stock_db > stock_db_backup.sql
```

### 导入数据库

```bash
psql -U stock_user -d stock_db < stock_db_backup.sql
```

### 导出单只股票数据

```python
from core.postgresql_db import PostgreSQLStockDB

db = PostgreSQLStockDB()
db.export_to_csv('000001', '000001_export.csv')
```

---

## 🚀 生产环境建议

1. **定期备份**：至少每天备份一次
2. **监控磁盘**：数据库增长很快，确保磁盘空间充足
3. **使用SSD**：SSD比HDD快10倍以上
4. **定期优化**：每月运行一次 `VACUUM ANALYZE`
5. **设置防火墙**：限制数据库端口只允许特定IP访问
6. **使用SSL**：远程访问时启用SSL加密

---

## 📞 需要帮助？

PostgreSQL官方文档：https://www.postgresql.org/docs/

TimescaleDB文档：https://docs.timescale.com/

常用命令速查：

```bash
# 启动/停止/重启
service postgresql start
service postgresql stop
service postgresql restart

# 查看状态
service postgresql status

# 进入数据库
sudo -u postgres psql stock_db

# 查看日志
tail -f /var/log/postgresql/postgresql-14-main.log
```