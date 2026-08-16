"""
Professional business notification templates with clean HTML formatting
Minimal emoji usage for professional communication
"""
from datetime import datetime
import os


def _format_time(dt_format='%Y-%m-%d %H:%M:%S'):
    """Get formatted time in local timezone"""
    try:
        tz = os.getenv('TIMEZONE')
        if tz:
            import pytz
            local_tz = pytz.timezone(tz)
            return datetime.now(local_tz).strftime(dt_format)
    except (ImportError, Exception):
        pass
    return datetime.now().strftime(dt_format)
from typing import Dict, Any
from .models import Notification, NotificationRole, NotificationPriority

class NotificationTemplates:
    """Professional notification templates with clean HTML formatting"""

    @staticmethod
    def get_business_display_name(business_slug: str, config) -> str:
        """Get business display name using config utility"""
        try:

            display_map = config.config.get('business', {}).get('display_name_map', {})
            if business_slug in display_map:
                return display_map[business_slug]


            try:
                from smart_engine.core.utils.business_utils import get_business_display_name
                return get_business_display_name(business_slug)
            except ImportError:
                pass

        except Exception:
            pass


        return business_slug.replace('_', ' ').title()

    @staticmethod
    def booking_created(business_slug: str, booking_data: Dict[str, Any], config) -> Notification:
        """Template for new booking confirmation - BUSINESS OWNER"""
        display_name = NotificationTemplates.get_business_display_name(business_slug, config)


        booking_time = booking_data.get('booking_time', 'Not specified')
        booking_date = booking_data.get('booking_date', 'Not specified')

        return Notification(
            title=f"Booking Confirmed - {display_name}",
            message=(
                "<b>Appointment Confirmation</b>\n\n"
                f"<b>Customer:</b> {booking_data.get('customer_name', 'Guest')}\n"
                f"<b>Service:</b> {booking_data.get('service_name', 'Service')}\n"
                f"<b>Date:</b> {booking_date}\n"
                f"<b>Time:</b> {booking_time}\n"
                f"<b>Contact:</b> {booking_data.get('contact_info', 'Not provided')}\n"
                "<b>Status:</b> Confirmed"
            ),
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.HIGH,
            business_name=business_slug
        )

    @staticmethod
    def booking_cancelled(business_slug: str, booking_data: Dict[str, Any], config) -> Notification:
        """Template for cancelled booking - BUSINESS OWNER"""
        display_name = NotificationTemplates.get_business_display_name(business_slug, config)

        return Notification(
            title=f"Booking Cancelled - {display_name}",
            message=(
                "<b>Appointment Cancellation</b>\n\n"
                f"<b>Customer:</b> {booking_data.get('customer_name', 'Guest')}\n"
                f"<b>Service:</b> {booking_data.get('service_name', 'Service')}\n"
                f"<b>Date:</b> {booking_data.get('booking_date', 'Not specified')}\n"
                f"<b>Time:</b> {booking_data.get('booking_time', 'Not specified')}\n"
                f"<b>Cancelled at:</b> {_format_time('%H:%M')}\n"
                "<b>Status:</b> Cancelled"
            ),
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.CRITICAL,
            business_name=business_slug
        )

    @staticmethod
    def order_created(business_slug: str, order_data: Dict[str, Any], config) -> Notification:
        """Template for new order confirmation - BUSINESS OWNER"""
        display_name = NotificationTemplates.get_business_display_name(business_slug, config)


        total_amount = order_data.get('total_amount', '0.00')
        if isinstance(total_amount, str):
            total_amount = total_amount.replace('$$', '$').strip()


        items = order_data.get('items', [])
        items_text = ""
        if items and isinstance(items, list):
            if len(items) > 0:
                if isinstance(items[0], str):
                    items_text = "\n".join([f"  • {item}" for item in items])
                elif isinstance(items[0], dict):
                    items_text = "\n".join([
                        f"  • {item.get('quantity', 1)}x {item.get('name', 'Item')} @ ${item.get('price', 0):.2f} each"
                        for item in items
                    ])
                else:
                    items_text = "\n".join([f"  • {str(item)}" for item in items])

        message_lines = [
            "<b>New Order Received</b>\n",
            f"<b>Order ID:</b> #{order_data.get('order_id', 'N/A')}",
            f"<b>Customer:</b> {order_data.get('customer_name', 'Guest')}",
            f"<b>Items ({order_data.get('item_count', '0')}):</b>"
        ]

        if items_text:
            message_lines.append(items_text)

        message_lines.extend([
            f"<b>Total Amount:</b> ${total_amount}",
            f"<b>Delivery Method:</b> {order_data.get('delivery_type', 'Pickup')}",
            f"<b>Contact:</b> {order_data.get('contact_info', 'Not provided')}"
        ])

        return Notification(
            title=f"Order Confirmation - {display_name}",
            message="\n".join(message_lines),
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.HIGH,
            business_name=business_slug
        )

    @staticmethod
    def order_cancelled(business_slug: str, order_data: Dict[str, Any], config) -> Notification:
        """Template for cancelled order - BUSINESS OWNER"""
        display_name = NotificationTemplates.get_business_display_name(business_slug, config)

        return Notification(
            title=f"Order Cancelled - {display_name}",
            message=(
                "<b>Order Cancellation</b>\n\n"
                f"<b>Order ID:</b> #{order_data.get('order_id', 'N/A')}\n"
                f"<b>Customer:</b> {order_data.get('customer_name', 'Guest')}\n"
                f"<b>Items:</b> {order_data.get('item_count', '0')}\n"
                f"<b>Total Amount:</b> ${order_data.get('total_amount', '0.00')}\n"
                f"<b>Time Placed:</b> {order_data.get('order_time', 'Not specified')}\n"
                f"<b>Status:</b> Cancelled"
            ),
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.CRITICAL,
            business_name=business_slug
        )

    @staticmethod
    def daily_summary(business_slug: str, summary_data: Dict[str, Any], config) -> Notification:
        """Template for enhanced daily business summary with insights - BUSINESS OWNER - HTML VERSION"""
        display_name = NotificationTemplates.get_business_display_name(business_slug, config)


        key_metrics = summary_data.get('key_metrics', {})
        performance = summary_data.get('performance_metrics', {})
        historical = summary_data.get('historical_comparison', {})
        insights = summary_data.get('business_insights', {})


        revenue_growth = historical.get('week_over_week', {}).get('revenue', {}).get('growth_percent', 0)
        revenue_trend = historical.get('week_over_week', {}).get('revenue', {}).get('trend', 'stable')


        performance_grade = performance.get('performance_grade', 'N/A')

        message_parts = [
            f"<b>Business Performance Report - {display_name}</b>",
            f"<b>Date:</b> {_format_time('%Y-%m-%d')}\n",

            f"<b>Key Performance Metrics</b>",
            f"Revenue: <b>{key_metrics.get('total_revenue', '$0.00')}</b> ({revenue_growth:+.1f}% vs last week)",
            f"Bookings: <b>{key_metrics.get('total_bookings', 0)}</b> ({key_metrics.get('confirmed_bookings', 0)} confirmed)",
            f"Orders: <b>{key_metrics.get('total_orders', 0)}</b> ({key_metrics.get('completed_orders', 0)} completed)",
            f"Customers: <b>{key_metrics.get('total_customers', 0)}</b> ({key_metrics.get('new_customers', 0)} new)",
            "",

            f"<b>Performance Analysis</b>",
            f"Overall Grade: <b>{performance_grade}</b>",
            f"Revenue per Customer: <b>${performance.get('revenue_per_customer', 0):.2f}</b>",
            f"Booking Efficiency: <b>{performance.get('booking_efficiency', 0):.1f}%</b>",
            f"Order Efficiency: <b>{performance.get('order_efficiency', 0):.1f}%</b>"
        ]


        if insights.get('strengths'):
            message_parts.extend([
                "",
                f"<b>Key Strengths</b>"
            ])
            for strength in insights['strengths'][:2]:
                message_parts.append(f"  • {strength}")

        if insights.get('concerns'):
            message_parts.extend([
                "",
                f"<b>Areas for Attention</b>"
            ])
            for concern in insights['concerns'][:2]:
                message_parts.append(f"  • {concern}")

        if insights.get('recommendations'):
            message_parts.extend([
                "",
                f"<b>Recommendations</b>"
            ])
            for recommendation in insights.get('recommendations', [])[:2]:
                message_parts.append(f"  • {recommendation}")


        top_service = summary_data.get('top_service', 'N/A')
        peak_hour = summary_data.get('peak_hour', 'N/A')

        if top_service != 'N/A' or peak_hour != 'N/A':
            message_parts.extend([
                "",
                f"<b>Operational Insights</b>"
            ])
            if top_service != 'N/A':
                message_parts.append(f"  Most Popular Service: {top_service}")
            if peak_hour != 'N/A':
                message_parts.append(f"  Peak Activity Hour: {peak_hour}")

        message_parts.extend([
            "",
            f"<b>Business Trend:</b> {historical.get('trend_direction', 'stable').replace('_', ' ').title()}",
            "",
            "Best regards for your business operations."
        ])

        return Notification(
            title=f"Business Report - {display_name}",
            message="\n".join(message_parts),
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.LOW,
            business_name=business_slug
        )

    @staticmethod
    def technical_summary(summary_data: Dict[str, Any], config) -> Notification:
        """Template for enhanced technical system summary with insights - DEVELOPER - HTML VERSION"""

        health_score = float(summary_data.get('health_score', 0))
        health_status = "Healthy" if health_score >= 90 else "Needs Attention" if health_score >= 70 else "Critical"


        total_errors = summary_data.get('errors_today', 0)
        critical_errors = summary_data.get('critical_errors', 0)
        error_status = "No Errors" if total_errors == 0 else "Minor Issues" if total_errors < 5 else "Multiple Errors"


        bot_active = summary_data.get('bot_active', False)
        bot_status = "Active" if bot_active else "Inactive"

        message_lines = [
            f"<b>System Status Report - {_format_time('%Y-%m-%d')}</b>\n",
            f"<b>System Health:</b> {health_status} ({health_score:.1f}/100)",
            f"<b>Error Status:</b> {error_status} ({total_errors} total, {critical_errors} critical)",
            f"<b>Bot Status:</b> {bot_status}",
            f"<b>Disk Space:</b> {summary_data.get('disk_space_available', 'Unknown')} available"
        ]


        if total_errors > 0:
            last_error_time = summary_data.get('last_error_time', 'Unknown')
            common_error = summary_data.get('common_error', 'Unknown')

            message_lines.extend([
                "",
                f"   <b>Error Analysis</b>",
                f"   Last Error: {last_error_time}",
                f"   Most Common: {common_error}"
            ])


            if critical_errors > 0:
                message_lines.extend([
                    "",
                    f"<b>Critical Issues - Immediate Action Required</b>",
                    f"  • {critical_errors} critical errors detected today",
                    f"  • Review system logs and prioritize fixes"
                ])
            elif total_errors > 5:
                message_lines.extend([
                    "",
                    f"<b>System Health Recommendations</b>",
                    f"  • High error rate detected - investigate root causes",
                    f"  • Consider implementing better error handling"
                ])
            elif total_errors > 0:
                message_lines.extend([
                    "",
                    f"<b>System Optimization</b>",
                    f"• Minor errors detected - schedule review"
                ])


        if health_score >= 90:
            message_lines.extend([
                "",
                f"<b>System Excellence</b>",
                f"  • System performing optimally",
                f"  • Continue current monitoring practices"
            ])
        elif health_score >= 70:
            message_lines.extend([
                "",
                f"<b>Maintenance Suggestions</b>",
                f"  • System needs attention in some areas",
                f"  • Schedule preventive maintenance soon"
            ])
        else:
            message_lines.extend([
                "",
                f"<b>Immediate Action Required</b>",
                f"  • System health is below optimal levels",
                f"  • Prioritize system stabilization"
            ])

        message_lines.extend([
            "",
            f"<b>Performance Metrics</b>",
            f"   Health Score: {health_score:.1f}/100 ({'Excellent' if health_score >= 90 else 'Good' if health_score >= 70 else 'Needs Improvement'})",
            f"   Bot Activity: {'Running smoothly' if bot_active else 'Bot needs attention'}",
            f"   Storage: {'Adequate' if summary_data.get('disk_space_available', '0 GB') != 'Unknown' else 'Check disk space'}"
        ])

        return Notification(
            title=f"System Intelligence Report",
            message="\n".join(message_lines),
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.MEDIUM
        )

    @staticmethod
    def system_error(error_message: str, component: str) -> Notification:
        """Template for system errors - DEVELOPER - HTML VERSION"""
        return Notification(
            title=f"{component} Error",
            message=(
                f"<b>System error detected</b>\n\n"
                f"<b>Component:</b> {component}\n"
                f"<b>Error:</b> {error_message[:150]}\n"
                f"<b>Time:</b> {_format_time('%H:%M:%S')}"
            ),
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.CRITICAL
        )

    @staticmethod
    def weekly_intelligence_report(business_slug: str, weekly_data: Dict[str, Any], config) -> Notification:
        """Template for weekly business intelligence report with trends - BUSINESS OWNER"""
        display_name = NotificationTemplates.get_business_display_name(business_slug, config)


        performance = weekly_data.get('performance_metrics', {})
        historical = weekly_data.get('historical_comparison', {})
        insights = weekly_data.get('business_insights', {})
        key_metrics = weekly_data.get('key_metrics', {})


        trend = historical.get('trend_direction', 'stable')
        trend_text = trend.replace('_', ' ').title()


        grade = performance.get('performance_grade', 'N/A')

        message_parts = [
            f"<b>Weekly Business Intelligence Report</b>",
            f"<b>{display_name} - Week of {_format_time('%Y-%m-%d')}</b>\n",

            f"<b>Overall Trend: {trend_text}</b>",
            f"<b>Performance Grade: {grade}</b>",
            "",

            f" <b>Weekly Performance Summary</b>",
            f" Total Revenue: <b>{key_metrics.get('total_revenue', '$0.00')}</b>",
            f" Total Bookings: <b>{key_metrics.get('total_bookings', 0)}</b>",
            f" Total Orders: <b>{key_metrics.get('total_orders', 0)}</b>",
            f" Total Customers: <b>{key_metrics.get('total_customers', 0)}</b>",
            "",

            f" <b>Growth Analysis</b>"
        ]


        week_growth = historical.get('week_over_week', {})
        for metric in ['revenue', 'bookings', 'orders', 'customers']:
            if metric in week_growth:
                data = week_growth[metric]
                current = data.get('current', 0)
                previous = data.get('previous', 0)
                growth_pct = data.get('growth_percent', 0)
                trend_symbol = "+" if data.get('trend') == 'up' else "-" if data.get('trend') == 'down' else "="
                metric_name = metric.title()
                message_parts.append(f"  {trend_symbol} {metric_name}: {current} vs {previous} ({growth_pct:+.1f}%)")


        if insights.get('strengths'):
            message_parts.extend([
                "",
                f"<b>Weekly Strengths</b>"
            ])
            for strength in insights.get('strengths', [])[:3]:
                message_parts.append(f"  • {strength}")

        if insights.get('concerns'):
            message_parts.extend([
                "",
                f"<b>Areas Requiring Attention</b>"
            ])
            for concern in insights.get('concerns', [])[:3]:
                message_parts.append(f"  • {concern}")


        if insights.get('recommendations'):
            message_parts.extend([
                "",
                f"<b>Strategic Recommendations for Next Week</b>"
            ])
            for rec in insights.get('recommendations', [])[:3]:
                message_parts.append(f"  • {rec}")


        if insights.get('opportunities'):
            message_parts.extend([
                "",
                f"<b>Growth Opportunities</b>"
            ])
            for opp in insights.get('opportunities', [])[:2]:
                message_parts.append(f"  • {opp}")


        message_parts.extend([
            "",
            f"⚡ <b>Efficiency Metrics</b>",
            f"   Booking Efficiency: {performance.get('booking_efficiency', 0):.1f}%",
            f"   Order Completion: {performance.get('order_efficiency', 0):.1f}%",
            f"   Revenue per Customer: ${performance.get('revenue_per_customer', 0):.2f}",
            "",
            f"  <b>Next Week's Focus Areas</b>"
        ])


        if performance.get('booking_efficiency', 0) < 70:
            message_parts.append("  • Improve booking confirmation process")
        if performance.get('revenue_per_customer', 0) < 25:
            message_parts.append("  • Implement upselling strategies")
        if key_metrics.get('new_customers', 0) < 5:
            message_parts.append("  • Launch customer acquisition campaign")

        message_parts.extend([
            "",
            f"Ready for another successful week!"
        ])

        return Notification(
            title=f"Weekly Intelligence Report - {display_name}",
            message="\n".join(message_parts),
            role=NotificationRole.BUSINESS_OWNER,
            priority=NotificationPriority.LOW,
            business_name=business_slug
        )

    @staticmethod
    def server_started(business_slug: str, config) -> Notification:
        """Template for server started - DEVELOPER - HTML VERSION"""
        display_name = NotificationTemplates.get_business_display_name(business_slug, config)

        return Notification(
            title=f"Bot Server Started",
            message=(
                f"<b>Telegram bot server for {display_name} is now running.</b>\n\n"
                f"<b>Startup time:</b> {_format_time('%H:%M:%S')}\n"
                f"<b>Date:</b> {_format_time('%Y-%m-%d')}"
            ),
            role=NotificationRole.DEVELOPER,
            priority=NotificationPriority.LOW,
            business_name=business_slug
        )
