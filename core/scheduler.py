# -*- coding: utf-8 -*-
"""
A股数据下载系统 - 定时任务模块
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import time


class UpdateScheduler:
    """数据更新定时器"""
    
    def __init__(self, downloader):
        """
        初始化定时器
        
        Args:
            downloader: StockDownloader实例
        """
        self.downloader = downloader
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        
    def start_daily_update(self, hour=15, minute=30):
        """
        启动每日定时更新
        
        Args:
            hour: 小时（默认15，即下午3点）
            minute: 分钟（默认30）
        """
        if self.is_running:
            print("定时任务已在运行")
            return
        
        # 添加每日定时任务
        trigger = CronTrigger(hour=hour, minute=minute)
        self.scheduler.add_job(
            self._daily_update_job,
            trigger=trigger,
            id='daily_update',
            replace_existing=True
        )
        
        self.scheduler.start()
        self.is_running = True
        print(f"✓ 定时任务已启动: 每天 {hour:02d}:{minute:02d} 自动更新")
    
    def _daily_update_job(self):
        """每日更新任务"""
        print(f"\n[{datetime.now()}] 开始执行定时更新任务...")
        self.downloader.update_daily()
        print(f"[{datetime.now()}] 定时更新任务完成\n")
    
    def stop(self):
        """停止定时任务"""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            print("✓ 定时任务已停止")
    
    def is_scheduler_running(self):
        """检查定时器是否运行"""
        return self.is_running