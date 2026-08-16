"""
Fixed data collector with health_score and business notifications
"""
import json
import sqlite3
import logging
from datetime import datetime
import os

def _get_local_now(business_slug=None, config=None):
    """Get current time in configured timezone for a specific business"""
    target_tz = os.getenv('TIMEZONE')


    if business_slug and config:
        business_config = config.config.get('business_settings', {}).get(business_slug, {})
        business_tz = business_config.get('timezone')
        if business_tz:
            target_tz = business_tz

    if target_tz:
        try:
            import pytz
            local_tz = pytz.timezone(target_tz)
            return datetime.now(local_tz)
        except (ImportError, Exception):
            pass
    return datetime.now()
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class DailyDataCollector:
    """Collects essential daily metrics for business owners and developers - FIXED"""

    def __init__(self):
        self.base_dir = Path(__file__).resolve().parent.parent

    async def collect_business_metrics(self, business_slug: str, target_date: str) -> Dict[str, Any]:
        """Collect comprehensive business metrics with intelligence insights"""
        try:

            bookings = await self._get_bookings_summary(business_slug, target_date)
            orders = await self._get_orders_summary(business_slug, target_date)
            revenue = await self._get_revenue_summary(business_slug, target_date)
            customers = await self._get_customers_summary(business_slug, target_date)


            historical_data = await self._get_historical_comparison(business_slug, target_date)


            performance_metrics = await self._calculate_performance_metrics(
                bookings, orders, revenue, customers, historical_data
            )


            insights = await self._generate_business_insights(
                bookings, orders, revenue, customers, performance_metrics, historical_data
            )

            logger.debug(f"[DataCollector] Business metrics collected for {business_slug} on {target_date}")

            return {
                'summary_date': target_date,
                'business': business_slug,
                'key_metrics': {
                    'total_bookings': bookings.get('total', 0),
                    'confirmed_bookings': bookings.get('confirmed', 0),
                    'cancelled_bookings': bookings.get('cancelled', 0),
                    'total_orders': orders.get('total', 0),
                    'completed_orders': orders.get('completed', 0),
                    'total_revenue': f"${revenue.get('total', 0):.2f}",
                    'new_customers': customers.get('new_customers', 0),
                    'total_customers': customers.get('total_customers', 0)
                },
                'conversion_rates': {
                    'booking_confirmation_rate': bookings.get('confirmation_rate', 0),
                    'order_completion_rate': orders.get('completion_rate', 0),
                    'overall_success_rate': self._calculate_success_rate(bookings, orders)
                },
                'performance_metrics': performance_metrics,
                'historical_comparison': historical_data,
                'business_insights': insights,
                'top_service': bookings.get('top_service', 'N/A'),
                'peak_hour': bookings.get('peak_hour', 'N/A')
            }

        except Exception as e:
            logger.error(f"[DataCollector] Error collecting business metrics: {e}")
            return self._get_empty_business_metrics(business_slug, target_date)

    async def collect_system_metrics(self) -> Dict[str, Any]:
        """Collect essential system metrics for developers - FIXED"""
        try:
            errors = await self._get_error_summary()
            system_health_result = await self._get_system_health()


            system_health = system_health_result.get('status', 'Unknown')
            health_score = system_health_result.get('score', 0.0)

            return {
                'timestamp': _get_local_now().isoformat(),
                'system_health': system_health,
                'health_score': health_score,
                'errors_today': errors.get('total_errors', 0),
                'critical_errors': errors.get('critical_errors', 0),
                'last_error_time': errors.get('last_error_time', 'None'),
                'common_error': errors.get('most_common_error', 'None'),
                'bot_active': await self._check_bot_status(),
                'disk_space_available': await self._check_disk_space()
            }

        except Exception as e:
            logger.error(f"[DataCollector] Error collecting system metrics: {e}")
            return self._get_empty_system_metrics()


    async def _get_bookings_summary(self, business_slug: str, target_date: str) -> Dict[str, Any]:
        """Get bookings summary for the day"""
        bookings_file = self.base_dir / "businesses" / business_slug / "bookings.json"

        if not bookings_file.exists():
            logger.debug(f"[DataCollector] Bookings file not found: {bookings_file}")
            return {"total": 0, "confirmed": 0, "cancelled": 0}

        try:
            with open(bookings_file, 'r', encoding='utf-8') as f:
                all_bookings = json.load(f)

            day_bookings = [
                b for b in all_bookings
                if self._is_same_day(b.get('created_at'), target_date)
            ]


            logger.info(f"[DataCollector] Bookings for {target_date}: {len(day_bookings)} total, {len([b for b in day_bookings if b.get('status') == 'confirmed'])} confirmed")

            total = len(day_bookings)
            confirmed = len([b for b in day_bookings if b.get('status') == 'confirmed'])
            cancelled = len([b for b in day_bookings if b.get('status') == 'cancelled'])


            services = {}
            for booking in day_bookings:
                service = booking.get('service_name', 'Unknown')
                services[service] = services.get(service, 0) + 1

            top_service = max(services.items(), key=lambda x: x[1])[0] if services else 'N/A'


            peak_hour = 'N/A'
            if day_bookings:
                hours = {}
                for booking in day_bookings:
                    if booking.get('created_at'):
                        hour = datetime.fromisoformat(
                            booking['created_at'].replace('Z', '+00:00')
                        ).strftime('%H:00')
                        hours[hour] = hours.get(hour, 0) + 1
                if hours:
                    peak_hour = max(hours.items(), key=lambda x: x[1])[0]

            result = {
                'total': total,
                'confirmed': confirmed,
                'cancelled': cancelled,
                'confirmation_rate': (confirmed / total * 100) if total > 0 else 0,
                'top_service': top_service,
                'peak_hour': peak_hour
            }

            logger.debug(f"[DataCollector] Bookings summary: {result}")
            return result

        except Exception as e:
            logger.error(f"[DataCollector] Error getting bookings summary: {e}")
            return {"total": 0, "confirmed": 0, "cancelled": 0}

    async def _get_orders_summary(self, business_slug: str, target_date: str) -> Dict[str, Any]:
        """Get orders summary for the day"""

        if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("DOCKER_ENV"):
            orders_db = "/app/data/databases/ordering_carts.sqlite"

        else:
            orders_db = Path(self.base_dir) / "data/databases/ordering_carts.sqlite"

        if not orders_db.exists():
            logger.warning(f"[DataCollector] Orders DB not found: {orders_db}")
            return {"total": 0, "completed": 0, "failed": 0, "total_amount": 0.0}

        try:
            conn = sqlite3.connect(str(orders_db))
            cursor = conn.cursor()


            cursor.execute("""
                SELECT 
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                    COALESCE(SUM(total_amount), 0) as total_revenue
                FROM orders 
                WHERE DATE(created_at) = ?
            """, (target_date,))

            result = cursor.fetchone()
            conn.close()

            total = result[0] or 0
            completed = result[1] or 0
            revenue = float(result[2]) if result[2] else 0.0

            result = {
                'total': total,
                'completed': completed,
                'failed': total - completed,
                'total_amount': revenue,
                'completion_rate': (completed / total * 100) if total > 0 else 0
            }

            logger.info(f"[DataCollector] Orders summary for {target_date}: total={total}, completed={completed}, revenue=${revenue:.2f}")
            return result

        except Exception as e:
            logger.error(f"[DataCollector] Error getting orders summary: {e}")
            return {"total": 0, "completed": 0, "failed": 0, "total_amount": 0.0}

    async def _get_revenue_summary(self, business_slug: str, target_date: str) -> Dict[str, Any]:
        """Get revenue summary from both orders and bookings"""

        orders = await self._get_orders_summary(business_slug, target_date)
        orders_revenue = orders.get('total_amount', 0.0)


        bookings = await self._get_bookings_summary(business_slug, target_date)
        bookings_revenue = 0.0

        bookings_file = self.base_dir / "businesses" / business_slug / "bookings.json"
        try:
            with open(bookings_file, 'r', encoding='utf-8') as f:
                all_bookings = json.load(f)

            day_bookings = [
                b for b in all_bookings
                if self._is_same_day(b.get('created_at'), target_date)
                and b.get('status') == 'confirmed'
            ]

            bookings_revenue = sum(b.get('price', 0) for b in day_bookings if isinstance(b.get('price'), (int, float)))
        except Exception as e:
            logger.error(f"[DataCollector] Error calculating bookings revenue: {e}")

        total_revenue = orders_revenue + bookings_revenue

        return {
            'total': total_revenue,
            'from_orders': orders_revenue,
            'from_bookings': bookings_revenue
        }

    async def _get_customers_summary(self, business_slug: str, target_date: str) -> Dict[str, Any]:
        """Get simplified customers summary"""
        sessions_file = self.base_dir / f"data/sessions/sessions_{business_slug}.json"

        if not sessions_file.exists():
            logger.warning(f"[DataCollector] Sessions file not found: {sessions_file}")
            return {"new_customers": 0, "total_customers": 0}

        try:
            with open(sessions_file, 'r', encoding='utf-8') as f:
                sessions = json.load(f)


            active_today = set()
            first_time_users = set()

            for user_id, data in sessions.items():
                if data.get('last_activity') and self._is_same_day(data['last_activity'], target_date):
                    active_today.add(user_id)

                    if (data.get('first_activity') and 
                        self._is_same_day(data['first_activity'], target_date)):
                        first_time_users.add(user_id)

            result = {
                'new_customers': len(first_time_users),
                'total_customers': len(active_today)
            }

            logger.info(f"[DataCollector] Customers summary: {result}")
            return result

        except Exception as e:
            logger.error(f"[DataCollector] ❌ Error getting customers summary: {e}")
            return {"new_customers": 0, "total_customers": 0}

    async def _get_error_summary(self) -> Dict[str, Any]:
        """Get error summary from logs"""
        try:
            log_file = self.base_dir / "data/logs/unified_gateway.log"

            if not log_file.exists():
                return {"total_errors": 0, "critical_errors": 0}

            today = datetime.now().strftime('%Y-%m-%d')
            error_count = 0
            critical_count = 0
            error_types = {}
            last_error_time = None

            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if today in line:
                        if 'ERROR' in line:
                            error_count += 1

                            if 'connection' in line.lower():
                                error_types['connection'] = error_types.get('connection', 0) + 1
                            elif 'database' in line.lower():
                                error_types['database'] = error_types.get('database', 0) + 1
                            elif 'api' in line.lower():
                                error_types['api'] = error_types.get('api', 0) + 1

                            parts = line.split()
                            if len(parts) > 1:
                                last_error_time = parts[1]

                        if 'CRITICAL' in line:
                            critical_count += 1

            most_common_error = max(error_types.items(), key=lambda x: x[1])[0] if error_types else 'None'

            result = {
                'total_errors': error_count,
                'critical_errors': critical_count,
                'most_common_error': most_common_error,
                'last_error_time': last_error_time or 'None'
            }

            logger.debug(f"[DataCollector] Error summary: {result}")
            return result

        except Exception:
            return {"total_errors": 0, "critical_errors": 0}

    async def _get_system_health(self) -> Dict[str, Any]:
        """Quick system health check - returns dict with status and score"""
        try:
            checks = []
            check_details = []


            if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("DOCKER_ENV"):
                orders_db = "/app/data/databases/ordering_carts.sqlite"
            else:
                orders_db = Path(self.base_dir) / "data/databases/ordering_carts.sqlite"

            if orders_db.exists():
                try:
                    conn = sqlite3.connect(str(orders_db))
                    conn.execute("SELECT 1")
                    conn.close()
                    checks.append(True)
                    check_details.append("✅ Database accessible")
                except:
                    checks.append(False)
                    check_details.append("❌ Database not accessible")
            else:
                checks.append(False)
                check_details.append("❌ Database file missing")


            log_file = self.base_dir / "data/logs/unified_gateway.log"
            if log_file.exists() and log_file.stat().st_size > 0:
                checks.append(True)
                check_details.append("✅ Bot logging active")
            else:
                checks.append(False)
                check_details.append("❌ Bot log missing or empty")


            try:
                import shutil
                total, used, free = shutil.disk_usage("/")
                free_gb = free / (1024**3)
                if free_gb > 1.0:
                    checks.append(True)
                    check_details.append(f"✅ Disk space OK ({free_gb:.1f}GB free)")
                else:
                    checks.append(False)
                    check_details.append(f"⚠️ Low disk space ({free_gb:.1f}GB free)")
            except:
                checks.append(True)
                check_details.append("⚠️ Could not check disk space")

            all_ok = all(checks)
            passed = sum(checks)
            total_checks = len(checks)
            health_percentage = (passed / total_checks * 100) if total_checks > 0 else 0

            logger.debug(f"[DataCollector] System health: {passed}/{total_checks} checks passed ({health_percentage:.1f}%)")

            if health_percentage >= 90:
                status = "Healthy"
            elif health_percentage >= 70:
                status = "Needs Attention"
            else:
                status = "Critical"

            return {
                'status': status,
                'score': health_percentage,
                'passed': passed,
                'total': total_checks,
                'details': check_details
            }

        except Exception as e:
            logger.error(f"[DataCollector] Error checking system health: {e}")
            return {
                'status': 'Unknown',
                'score': 0.0,
                'passed': 0,
                'total': 0,
                'details': [f"Error: {e}"]
            }

    async def _check_bot_status(self) -> bool:
        """Check if bot is active (simplified - check last log entry)"""
        try:
            log_file = self.base_dir / "data/logs/unified_gateway.log"
            if not log_file.exists():
                return False

            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if lines:
                    last_line = lines[-1]

                    if "INFO" in last_line and "Processing" in last_line:
                        return True
            return False

        except Exception:
            return False

    async def _check_disk_space(self) -> str:
        """Check available disk space"""
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            free_gb = free / (1024**3)
            return f"{free_gb:.1f} GB"
        except Exception:
            return "Unknown"


    def _is_same_day(self, timestamp: str, target_date: str) -> bool:
        """Check if timestamp is on target date"""
        try:
            if not timestamp:
                return False
            ts = timestamp.replace('Z', '+00:00')
            date_obj = datetime.fromisoformat(ts).date()
            target = datetime.strptime(target_date, '%Y-%m-%d').date()
            return date_obj == target
        except Exception:
            return False

    async def _get_historical_comparison(self, business_slug: str, target_date: str) -> Dict[str, Any]:
        """Get historical data for comparison (7 days ago, 30 days ago)"""
        try:
            from datetime import timedelta
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')


            week_ago = (target_dt - timedelta(days=7)).strftime('%Y-%m-%d')
            month_ago = (target_dt - timedelta(days=30)).strftime('%Y-%m-%d')


            week_ago_data = await self._get_basic_metrics_for_date(business_slug, week_ago)
            month_ago_data = await self._get_basic_metrics_for_date(business_slug, month_ago)


            current_data = await self._get_basic_metrics_for_date(business_slug, target_date)


            comparison = {
                'week_over_week': self._calculate_growth(current_data, week_ago_data, 'week'),
                'month_over_month': self._calculate_growth(current_data, month_ago_data, 'month'),
                'trend_direction': self._determine_trend_direction(current_data, week_ago_data, month_ago_data)
            }

            logger.debug(f"[DataCollector] Historical comparison: Week {comparison['week_over_week']}, Month {comparison['month_over_month']}")
            return comparison

        except Exception as e:
            logger.error(f"[DataCollector] Error getting historical comparison: {e}")
            return {'week_over_week': {}, 'month_over_month': {}, 'trend_direction': 'stable'}

    async def _get_basic_metrics_for_date(self, business_slug: str, date: str) -> Dict[str, Any]:
        """Get basic metrics for a specific date"""
        try:
            bookings = await self._get_bookings_summary(business_slug, date)
            orders = await self._get_orders_summary(business_slug, date)
            revenue = await self._get_revenue_summary(business_slug, date)

            return {
                'bookings': bookings.get('total', 0),
                'orders': orders.get('total', 0),
                'revenue': revenue.get('total', 0.0),
                'customers': (await self._get_customers_summary(business_slug, date)).get('total_customers', 0)
            }
        except Exception as e:
            logger.error(f"[DataCollector] Error getting basic metrics for {date}: {e}")
            return {'bookings': 0, 'orders': 0, 'revenue': 0.0, 'customers': 0}

    def _calculate_growth(self, current: Dict[str, Any], previous: Dict[str, Any], period: str) -> Dict[str, Any]:
        """Calculate growth percentage between two periods"""
        growth = {}

        for metric in ['bookings', 'orders', 'revenue', 'customers']:
            current_val = current.get(metric, 0)
            previous_val = previous.get(metric, 0)

            if previous_val > 0:
                growth_pct = ((current_val - previous_val) / previous_val) * 100
                growth[metric] = {
                    'current': current_val,
                    'previous': previous_val,
                    'growth_percent': round(growth_pct, 1),
                    'trend': 'up' if growth_pct > 0 else 'down' if growth_pct < 0 else 'stable'
                }
            else:
                growth[metric] = {
                    'current': current_val,
                    'previous': previous_val,
                    'growth_percent': float('inf') if current_val > 0 else 0.0,
                    'trend': 'new' if current_val > 0 else 'stable'
                }

        return growth

    def _determine_trend_direction(self, current: Dict, week_ago: Dict, month_ago: Dict) -> str:
        """Determine overall trend direction"""
        try:
            current_rev = current.get('revenue', 0)
            week_rev = week_ago.get('revenue', 0)
            month_rev = month_ago.get('revenue', 0)

            week_growth = ((current_rev - week_rev) / week_rev * 100) if week_rev > 0 else 0
            month_growth = ((current_rev - month_rev) / month_rev * 100) if month_rev > 0 else 0

            if week_growth > 10 and month_growth > 5:
                return 'strong_up'
            elif week_growth > 0 and month_growth > 0:
                return 'moderate_up'
            elif week_growth < -10 and month_growth < -5:
                return 'strong_down'
            elif week_growth < 0 or month_growth < 0:
                return 'moderate_down'
            else:
                return 'stable'
        except:
            return 'stable'

    async def _calculate_performance_metrics(self, bookings: Dict, orders: Dict, 
                                           revenue: Dict, customers: Dict, 
                                           historical: Dict) -> Dict[str, Any]:
        """Calculate comprehensive performance metrics"""
        try:

            avg_revenue_per_order = (revenue.get('total', 0) / orders.get('total', 1)) if orders.get('total', 0) > 0 else 0
            avg_revenue_per_customer = (revenue.get('total', 0) / customers.get('total_customers', 1)) if customers.get('total_customers', 0) > 0 else 0


            booking_efficiency = (bookings.get('confirmed', 0) / bookings.get('total', 1)) * 100 if bookings.get('total', 0) > 0 else 0
            order_efficiency = (orders.get('completed', 0) / orders.get('total', 1)) * 100 if orders.get('total', 0) > 0 else 0


            revenue_growth = historical.get('week_over_week', {}).get('revenue', {}).get('growth_percent', 0)
            customer_growth = historical.get('week_over_week', {}).get('customers', {}).get('growth_percent', 0)


            performance_score = (
                min(booking_efficiency, 100) * 0.25 +
                min(order_efficiency, 100) * 0.25 +
                min(max(avg_revenue_per_customer * 10, 100), 100) * 0.25 +
                min(max(revenue_growth + 50, 100), 100) * 0.25
            )

            return {
                'revenue_per_order': round(avg_revenue_per_order, 2),
                'revenue_per_customer': round(avg_revenue_per_customer, 2),
                'booking_efficiency': round(booking_efficiency, 1),
                'order_efficiency': round(order_efficiency, 1),
                'revenue_growth_rate': revenue_growth,
                'customer_growth_rate': customer_growth,
                'overall_performance_score': round(performance_score, 1),
                'performance_grade': self._get_performance_grade(performance_score)
            }
        except Exception as e:
            logger.error(f"[DataCollector] Error calculating performance metrics: {e}")
            return self._get_empty_performance_metrics()

    def _get_performance_grade(self, score: float) -> str:
        """Get performance grade based on score"""
        if score >= 90:
            return 'A+ (Excellent)'
        elif score >= 80:
            return 'A (Very Good)'
        elif score >= 70:
            return 'B (Good)'
        elif score >= 60:
            return 'C (Average)'
        elif score >= 50:
            return 'D (Below Average)'
        else:
            return 'F (Needs Improvement)'

    async def _generate_business_insights(self, bookings: Dict, orders: Dict, 
                                        revenue: Dict, customers: Dict,
                                        performance: Dict, historical: Dict) -> Dict[str, Any]:
        """Generate actionable business insights"""
        try:
            insights = {
                'strengths': [],
                'concerns': [],
                'recommendations': [],
                'opportunities': []
            }


            if bookings.get('confirmation_rate', 0) > 80:
                insights['strengths'].append("High booking confirmation rate indicates good customer satisfaction")

            if performance.get('revenue_growth_rate', 0) > 10:
                insights['strengths'].append("Strong revenue growth showing positive business momentum")

            if customers.get('new_customers', 0) > customers.get('total_customers', 0) * 0.3:
                insights['strengths'].append("Good customer acquisition with high new customer ratio")


            if bookings.get('cancelled', 0) > bookings.get('total', 0) * 0.2:
                insights['concerns'].append("High cancellation rate may indicate service quality issues")

            if orders.get('completion_rate', 0) < 70:
                insights['concerns'].append("Low order completion rate needs immediate attention")

            if performance.get('overall_performance_score', 0) < 60:
                insights['concerns'].append("Overall performance score indicates need for operational improvements")


            if bookings.get('total', 0) < 5:
                insights['recommendations'].append("Consider marketing campaigns to increase booking volume")

            if performance.get('booking_efficiency', 0) < 70:
                insights['recommendations'].append("Review booking process to improve confirmation rates")

            if performance.get('revenue_per_customer', 0) < 20:
                insights['recommendations'].append("Implement upselling strategies to increase average order value")


            if bookings.get('peak_hour', 'N/A') != 'N/A':
                insights['opportunities'].append(f"Peak booking hour is {bookings.get('peak_hour')} - optimize staffing during this time")

            if bookings.get('top_service', 'N/A') != 'N/A':
                insights['opportunities'].append(f"Popular service: {bookings.get('top_service')} - consider promoting it more")

            if historical.get('trend_direction') == 'strong_up':
                insights['opportunities'].append("Strong upward trend - consider expanding capacity or services")

            return insights
        except Exception as e:
            logger.error(f"[DataCollector] Error generating insights: {e}")
            return {'strengths': [], 'concerns': [], 'recommendations': [], 'opportunities': []}

    def _calculate_success_rate(self, bookings: Dict, orders: Dict) -> float:
        """Calculate overall success rate"""
        total_success = bookings.get('confirmed', 0) + orders.get('completed', 0)
        total_attempts = bookings.get('total', 0) + orders.get('total', 0)

        if total_attempts > 0:
            return (total_success / total_attempts) * 100
        return 0.0

    def _get_empty_business_metrics(self, business_slug: str, target_date: str) -> Dict[str, Any]:
        """Return empty business metrics structure"""
        return {
            'summary_date': target_date,
            'business': business_slug,
            'key_metrics': {
                'total_bookings': 0,
                'confirmed_bookings': 0,
                'cancelled_bookings': 0,
                'total_orders': 0,
                'completed_orders': 0,
                'total_revenue': '$0.00',
                'new_customers': 0,
                'total_customers': 0
            },
            'conversion_rates': {
                'booking_confirmation_rate': 0,
                'order_completion_rate': 0,
                'overall_success_rate': 0
            },
            'performance_metrics': self._get_empty_performance_metrics(),
            'historical_comparison': {'week_over_week': {}, 'month_over_month': {}, 'trend_direction': 'stable'},
            'business_insights': {'strengths': [], 'concerns': [], 'recommendations': [], 'opportunities': []},
            'top_service': 'N/A',
            'peak_hour': 'N/A'
        }

    def _get_empty_performance_metrics(self) -> Dict[str, Any]:
        """Return empty performance metrics structure"""
        return {
            'revenue_per_order': 0.0,
            'revenue_per_customer': 0.0,
            'booking_efficiency': 0.0,
            'order_efficiency': 0.0,
            'revenue_growth_rate': 0.0,
            'customer_growth_rate': 0.0,
            'overall_performance_score': 0.0,
            'performance_grade': 'N/A'
        }

    def _get_empty_system_metrics(self) -> Dict[str, Any]:
        """Return empty system metrics structure"""
        return {
            'timestamp': _get_local_now().isoformat(),
            'system_health': 'Unknown',
            'health_score': 0.0,
            'errors_today': 0,
            'critical_errors': 0,
            'last_error_time': 'None',
            'common_error': 'None',
            'bot_active': False,
            'disk_space_available': 'Unknown'
        }
