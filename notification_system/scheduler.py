"""
Simplified, accurate scheduler for automated notifications
"""
import asyncio
import logging
import os
from datetime import datetime, time, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

TIMEZONE = os.getenv('TIMEZONE', None)


def _get_local_now(business_slug=None, config=None):
    """Get current time in configured timezone for a specific business"""
    target_tz = TIMEZONE

    if business_slug and config:
        business_config = config.config.get('business_settings', {}).get(business_slug, {})
        business_tz = business_config.get('timezone')
        if business_tz:
            target_tz = business_tz

    if target_tz:
        try:
            import pytz
            tz = pytz.timezone(target_tz)
            return datetime.now(tz)
        except (ImportError, Exception):
            return datetime.now()
    return datetime.now()


try:
    from .data_collector import DailyDataCollector
    DATA_COLLECTOR_AVAILABLE = True
except ImportError:
    DATA_COLLECTOR_AVAILABLE = False
    logger.warning("[Scheduler] Data collector not available - using fallback mode")


class ScheduledTask:
    """Simple scheduled task definition"""
    def __init__(self, name: str, time_str: str, callback, is_weekly: bool = False):
        self.name = name
        self.time_str = time_str
        self.callback = callback
        self.is_weekly = is_weekly
        self.last_run_date = None
        self.target_time = _parse_time(time_str)

    def should_run(self, now: datetime, business_time: time, business_date) -> bool:
        """Check if task should run now"""
        if self.last_run_date == business_date:
            return False

        if self.is_weekly and now.weekday() != 6:
            return False


        if self.last_run_date is None or self.last_run_date != business_date:
            now_minutes = now.hour * 60 + now.minute
            target_minutes = self.target_time.hour * 60 + self.target_time.minute


            return now_minutes >= target_minutes

        return False

    def mark_as_run(self, business_date):
        """Mark task as run for this date"""
        self.last_run_date = business_date


def _parse_time(time_str: str) -> time:
    """Parse time string (HH:MM) into time object"""
    try:
        hour_str, minute_str = time_str.split(':')
        return time(hour=int(hour_str), minute=int(minute_str))
    except (ValueError, AttributeError):
        logger.error(f"[Scheduler] Invalid time string '{time_str}', using 21:00")
        return time(hour=21, minute=0)


class NotificationScheduler:
    """Simplified, accurate notification scheduler"""

    def __init__(self, service):
        self.service = service

        from .config import NotificationConfig as FullConfig
        self.full_config = FullConfig()
        self.running = False

        self.data_collector = None
        if DATA_COLLECTOR_AVAILABLE:
            try:
                self.data_collector = DailyDataCollector()
            except Exception as e:
                logger.error(f"[Scheduler] Failed to initialize data collector: {e}")

        self.default_business = self.full_config.config.get('business', {}).get('default', 'yo_bakery')
        self._init_scheduled_tasks()
        self._set_initial_run_dates()

    def _init_scheduled_tasks(self):
        """Initialize scheduled tasks from config"""
        schedule_config = self.full_config.config.get('schedule', {})

        self.tasks = [
            ScheduledTask(
                name="business_summary",
                time_str=schedule_config.get('business_summary', '21:00'),
                callback=self._send_business_daily_summary,
                is_weekly=False
            ),
            ScheduledTask(
                name="technical_summary",
                time_str=schedule_config.get('technical_summary', '22:00'),
                callback=self._send_technical_summary,
                is_weekly=False
            ),
            ScheduledTask(
                name="weekly_report",
                time_str=schedule_config.get('weekly_report', '18:00'),
                callback=self._send_weekly_intelligence_report,
                is_weekly=True
            )
        ]

    def _set_initial_run_dates(self):
        """Set initial run dates to prevent immediate triggering on startup"""
        now = _get_local_now()
        current_date = now.date()
        current_minutes = now.hour * 60 + now.minute

        for task in self.tasks:
            target_minutes = task.target_time.hour * 60 + task.target_time.minute


            if current_minutes >= target_minutes:
                task.last_run_date = current_date
                logger.info(f"[Scheduler] Task '{task.name}' already passed today, marking as run (will trigger tomorrow)")
            else:
                logger.info(f"[Scheduler] Task '{task.name}' will run today at {task.target_time}")

    async def start(self):
        """Start scheduling loop"""
        self.running = True
        logger.info("Notification scheduler started")

        while self.running:
            try:
                now = _get_local_now()
                await self._check_and_run_tasks(now)


                next_minute = (now.replace(second=0, microsecond=0) + timedelta(minutes=1))
                sleep_duration = (next_minute - now).total_seconds()

                if sleep_duration > 0:
                    await asyncio.sleep(sleep_duration)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)

    async def _check_and_run_tasks(self, now: datetime):
        """Check and run due tasks"""
        business_now = _get_local_now(self.default_business, self.full_config)
        business_time = business_now.time()
        business_date = business_now.date()

        for task in self.tasks:
            if task.should_run(now, business_time, business_date):
                logger.info(f"[Scheduler] ✅ Triggering task: {task.name}")
                try:
                    await task.callback()
                    task.mark_as_run(business_date)
                    logger.info(f"[Scheduler] ✅ Completed: {task.name}")
                except Exception as e:
                    logger.error(f"[Scheduler] ❌ Task {task.name} failed: {e}")

    async def _send_business_daily_summary(self):
        """Send daily business summary"""
        if not self.data_collector:
            return

        max_retries = 3
        for attempt in range(max_retries):
            try:
                today = _get_local_now(self.default_business, self.full_config).strftime('%Y-%m-%d')
                metrics = await self.data_collector.collect_business_metrics(self.default_business, today)

                success = await self.service.send_daily_summary(self.default_business, metrics)
                if success:
                    logger.info(f"[Scheduler] Business summary sent for {self.default_business}")
                    return
                else:
                    raise Exception("Service failed to send summary")

            except Exception as e:
                logger.error(f"[Scheduler] Business summary failed (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(30)

    async def _send_technical_summary(self):
        """Send technical system summary"""
        if not self.data_collector:
            return

        max_retries = 2
        for attempt in range(max_retries):
            try:
                metrics = await self.data_collector.collect_system_metrics()
                summary_data = self._prepare_technical_summary_data(metrics)

                success = await self.service.send_technical_summary(summary_data)

                if success:
                    logger.info("[Scheduler] Technical summary sent to developers")
                    return
                else:
                    raise Exception("Service failed to send technical summary")

            except Exception as e:
                logger.error(f"[Scheduler] Technical summary failed (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(30)

    async def _send_weekly_intelligence_report(self):
        """Send weekly business intelligence report"""
        if not self.data_collector:
            return

        max_retries = 3
        for attempt in range(max_retries):
            try:
                weekly_data = await self._collect_weekly_data(self.default_business)

                success = await self.service.send_weekly_report(self.default_business, weekly_data)

                if success:
                    logger.info(f"[Scheduler] Weekly report sent for {self.default_business}")
                    return
                else:
                    raise Exception("Service failed to send weekly report")

            except Exception as e:
                logger.error(f"[Scheduler] Weekly report failed (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(30)

    async def _collect_weekly_data(self, business_slug: str) -> Dict[str, Any]:
        """Collect 7 days of data for weekly analysis"""
        try:
            weekly_summary = {
                'key_metrics': {
                    'total_bookings': 0, 'total_orders': 0,
                    'total_revenue': '$0.00', 'total_customers': 0
                },
                'performance_metrics': {},
                'historical_comparison': {},
                'business_insights': {
                    'strengths': [], 'concerns': [], 'recommendations': [], 'opportunities': []
                }
            }

            for i in range(1, 8):
                date = (_get_local_now() - timedelta(days=i)).strftime('%Y-%m-%d')
                logger.info(f"[Scheduler] Collecting weekly data for date: {date}")
                daily_metrics = await self.data_collector.collect_business_metrics(business_slug, date)

                key_metrics = daily_metrics.get('key_metrics', {})
                weekly_summary['key_metrics']['total_bookings'] += key_metrics.get('total_bookings', 0)
                weekly_summary['key_metrics']['total_orders'] += key_metrics.get('total_orders', 0)
                weekly_summary['key_metrics']['total_customers'] += key_metrics.get('total_customers', 0)

                revenue_str = key_metrics.get('total_revenue', '$0.00')
                try:
                    current_total = float(str(weekly_summary['key_metrics']['total_revenue']).replace('$', ''))
                    revenue_val = float(str(revenue_str).replace('$', ''))
                    weekly_summary['key_metrics']['total_revenue'] = f"${current_total + revenue_val:.2f}"
                except:
                    pass

            today = _get_local_now().strftime('%Y-%m-%d')
            today_metrics = await self.data_collector.collect_business_metrics(business_slug, today)
            weekly_summary['performance_metrics'] = today_metrics.get('performance_metrics', {})
            weekly_summary['historical_comparison'] = today_metrics.get('historical_comparison', {})
            weekly_summary['business_insights'] = today_metrics.get('business_insights', {})
            return weekly_summary

        except Exception as e:
            logger.error(f"[Scheduler] Error collecting weekly data: {e}")
            return {
                'key_metrics': {
                    'total_bookings': 0, 'total_orders': 0,
                    'total_revenue': '$0.00', 'total_customers': 0
                },
                'performance_metrics': {},
                'historical_comparison': {},
                'business_insights': {
                    'strengths': [], 'concerns': [], 'recommendations': [], 'opportunities': []
                }
            }

    def _prepare_technical_summary_data(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare technical summary data"""
        try:
            health_score = metrics.get('health_score', 0.0)
            formatted_score = 'N/A'
            if health_score not in ['N/A', 0.0]:
                try:
                    formatted_score = f"{float(health_score):.1f}%"
                except (ValueError, TypeError):
                    pass

            total_errors = metrics.get('errors_today', 0)
            error_rate = "critical" if total_errors > 20 else "high" if total_errors > 10 else "normal"

            return {
                'system_health': metrics.get('system_health', '❌ Unknown'),
                'health_score': health_score,
                'total_errors': total_errors,
                'critical_errors': metrics.get('critical_errors', 0),
                'error_rate': error_rate,
                'cpu_usage': 'N/A', 'memory_usage': 'N/A', 'disk_usage': 'N/A',
                'uptime': 'N/A', 'avg_response_time': 'N/A'
            }
        except Exception as e:
            logger.error(f"[Scheduler] Error preparing technical data: {e}")
            return {
                'system_health': '❌ Error', 'health_score': 'N/A',
                'total_errors': 0, 'critical_errors': 0, 'error_rate': 'normal',
                'cpu_usage': 'N/A', 'memory_usage': 'N/A', 'disk_usage': 'N/A',
                'uptime': 'N/A', 'avg_response_time': 'N/A'
            }

    async def stop(self):
        """Stop scheduler gracefully"""
        self.running = False
        logger.info("Notification scheduler stopped")


async def start_scheduler(service):
    """Start scheduler"""
    scheduler = NotificationScheduler(service)
    asyncio.create_task(scheduler.start())
    logger.info("Notification scheduler started")
    return scheduler
