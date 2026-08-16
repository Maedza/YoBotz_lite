import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
import pytz

logger = logging.getLogger(__name__)


class ReservationTimeValidator:

    def __init__(self, business_name: str, config: Dict[str, Any]):
        self.business_name = business_name
        self.config = config
        self.reservation_config = config.get('reservation', {})


        self.business_hours = config.get('business_hours', {})
        self.timezone = config.get('timezone', 'UTC')
        self.tz = pytz.timezone(self.timezone)

    def validate_reservation_time(self, requested_time: datetime) -> Tuple[bool, str]:
        try:

            if requested_time.tzinfo is None:
                requested_time = self.tz.localize(requested_time)
            else:
                requested_time = requested_time.astimezone(self.tz)

            logger.info(f"[ReservationTimeValidator] Validating reservation for {self.business_name}")
            logger.info(f"[ReservationTimeValidator] Requested time: {requested_time.isoformat()}")


            now = datetime.now(self.tz)


            is_valid, message = self._validate_not_past(requested_time, now)
            if not is_valid:
                return False, message


            is_valid, message = self._validate_min_notice(requested_time, now)
            if not is_valid:
                return False, message


            is_valid, message = self._validate_max_lead_time(requested_time, now)
            if not is_valid:
                return False, message


            is_valid, message = self._validate_business_hours(requested_time)
            if not is_valid:
                return False, message


            logger.info(f"[ReservationTimeValidator] ✅ Reservation time validated")
            return True, "Reservation time is valid."

        except Exception as e:
            logger.error(f"[ReservationTimeValidator] Error validating time: {e}")
            return False, f"Error validating reservation time: {str(e)}"

    def _validate_not_past(self, requested_time: datetime, now: datetime) -> Tuple[bool, str]:
        if requested_time < now:
            logger.warning(f"[ReservationTimeValidator] ❌ Past time requested")
            return False, "❌ Cannot make reservations in the past. Please select a future date and time."
        return True, ""

    def _validate_min_notice(self, requested_time: datetime, now: datetime) -> Tuple[bool, str]:
        min_notice_hours = self.reservation_config.get('min_notice_hours', 2)
        min_notice_delta = timedelta(hours=min_notice_hours)

        if requested_time < now + min_notice_delta:
            logger.warning(f"[ReservationTimeValidator] ❌ Insufficient notice: {min_notice_hours}h required")
            return False, f"❌ Minimum notice required: {min_notice_hours} hours. Please choose a time at least {min_notice_hours} hours from now."
        return True, ""

    def _validate_max_lead_time(self, requested_time: datetime, now: datetime) -> Tuple[bool, str]:
        max_lead_days = self.reservation_config.get('max_lead_time_days', 30)
        max_lead_delta = timedelta(days=max_lead_days)

        if requested_time > now + max_lead_delta:
            logger.warning(f"[ReservationTimeValidator] ❌ Exceeds max lead time: {max_lead_days} days")
            return False, f"❌ Maximum lead time: {max_lead_days} days. Please choose a date within the next {max_lead_days} days."
        return True, ""

    def _validate_business_hours(self, requested_time: datetime) -> Tuple[bool, str]:
        allow_off_hours = self.reservation_config.get('allow_off_hours', False)

        if allow_off_hours:
            logger.info(f"[ReservationTimeValidator] Off-hours reservations allowed")
            return True, ""


        day_name = requested_time.strftime('%A').lower()


        if day_name not in self.business_hours:
            logger.warning(f"[ReservationTimeValidator] ❌ Closed on {day_name}")
            return False, f"❌ We're closed on {day_name.title()}. Please choose another day."


        day_hours = self.business_hours[day_name]


        if not day_hours:
            logger.warning(f"[ReservationTimeValidator] ❌ No hours defined for {day_name}")
            return False, f"❌ No business hours defined for {day_name.title()}."


        time_str = requested_time.strftime('%H:%M')
        is_within_hours = False

        for time_range in day_hours:
            open_time = time_range.get('open')
            close_time = time_range.get('close')

            if open_time and close_time:
                if open_time <= time_str <= close_time:
                    is_within_hours = True
                    break

        if not is_within_hours:

            hours_str = self._format_day_hours(day_hours)

            logger.warning(f"[ReservationTimeValidator] ❌ Outside business hours")
            return False, f"❌ That time is outside our business hours.\n\n**Hours for {day_name.title()}:**\n{hours_str}"

        return True, ""

    def get_confirmation_timeout(self) -> int:
        return self.reservation_config.get('confirmation_timeout_minutes', 15)

    def get_available_days(self, days_ahead: int = 7) -> list:
        available_days = []
        now = datetime.now(self.tz)

        for i in range(days_ahead):
            day_date = now + timedelta(days=i)
            day_name = day_date.strftime('%A').lower()


            if day_name not in self.business_hours or not self.business_hours[day_name]:
                continue


            day_hours = self.business_hours[day_name]
            if not day_hours:
                continue


            slots = self.get_available_time_slots(day_date, 30)


            min_notice_hours = self.reservation_config.get('min_notice_hours', 2)
            min_notice_delta = timedelta(hours=min_notice_hours)

            if slots and day_date >= now + min_notice_delta:
                available_days.append({
                    'date': day_date,
                    'day_name': day_name,
                    'day_display': day_date.strftime('%A, %b %d'),
                    'slots_count': len(slots),
                    'hours': self._format_day_hours(day_hours)
                })

        logger.info(f"[ReservationTimeValidator] Found {len(available_days)} available days")
        return available_days

    def get_business_hours_for_day(self, date: datetime) -> str:
        day_name = date.strftime('%A').lower()
        if day_name in self.business_hours and self.business_hours[day_name]:
            return self._format_day_hours(self.business_hours[day_name])
        return "Closed"

    def parse_time_input(self, time_str: str) -> Optional[datetime]:
        import re
        time_str = time_str.strip().lower()


        match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if match:
            return datetime.strptime(time_str, "%H:%M").time()


        match = re.match(r'^(\d{1,2}):(\d{2})\s*(am|pm)$', time_str)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            period = match.group(3)
            if period == 'pm' and hour != 12:
                hour += 12
            elif period == 'am' and hour == 12:
                hour = 0
            return datetime.strptime(f"{hour:02d}:{minute}", "%H:%M").time()


        match = re.match(r'^(\d{1,2})\s*(am|pm)$', time_str)
        if match:
            hour = int(match.group(1))
            minute = 0
            period = match.group(2)
            if period == 'pm' and hour != 12:
                hour += 12
            elif period == 'am' and hour == 12:
                hour = 0
            return datetime.strptime(f"{hour:02d}:{minute}", "%H:%M").time()

        return None

    def parse_date_input(self, date_input: str, days_ahead: int = 7) -> Tuple[bool, str, Optional[datetime]]:
        date_input = date_input.strip().lower()
        available_days = self.get_available_days(days_ahead)

        if not available_days:
            return False, "No available days for reservation. Please try again later.", None


        if date_input.isdigit():
            idx = int(date_input) - 1
            if 0 <= idx < len(available_days):
                return True, "", available_days[idx]['date']
            else:
                day_list = "\n".join([f"{i+1}. {d['day_display']}" for i, d in enumerate(available_days)])
                return False, f"Please select a number between 1 and {len(available_days)}.\n\nAvailable days:\n{day_list}", None


        now = datetime.now(self.tz)

        if date_input == 'tomorrow':
            tomorrow = now + timedelta(days=1)
            for day in available_days:
                if day['date'].date() == tomorrow.date():
                    return True, "", day['date']
            return False, "Tomorrow is not available. Please select from the available days.", None


        if date_input == 'today':
            for day in available_days:
                if day['date'].date() == now.date():
                    return True, "", day['date']
            return False, "Today is not available for reservation. Please select another day.", None


        for day in available_days:
            if day['day_name'] == date_input:
                return True, "", day['date']


        if date_input.startswith('next '):
            target_day = date_input.replace('next ', '')
            for day in available_days:
                if day['day_name'] == target_day:
                    return True, "", day['date']
            return False, f"'{target_day.title()}' is not available in the next {days_ahead} days.", None


        day_list = "\n".join([f"{i+1}. {d['day_display']}" for i, d in enumerate(available_days)])
        return False, f"Could not understand date '{date_input}'.\n\nPlease select:\n- A number (1-{len(available_days)})\n- Day name (e.g., 'tomorrow', 'friday')\n\nAvailable days:\n{day_list}", None

    def is_time_within_hours(self, date: datetime, time_str: str) -> Tuple[bool, str]:
        parsed_time = self.parse_time_input(time_str)
        if parsed_time is None:
            return False, f"Could not understand time format: '{time_str}'. Try formats like '14:00', '2pm', or '14:30'."

        time_obj = parsed_time
        day_name = date.strftime('%A').lower()


        if day_name not in self.business_hours or not self.business_hours[day_name]:
            return False, f"We're closed on {day_name.title()}. Please choose another day."


        day_hours = self.business_hours[day_name]
        time_str_fmt = time_obj.strftime('%H:%M')

        for time_range in day_hours:
            open_time = time_range.get('open')
            close_time = time_range.get('close')

            if open_time and close_time:
                if open_time <= time_str_fmt <= close_time:
                    return True, ""

        hours_str = self._format_day_hours(day_hours)
        return False, f"Time {time_obj.strftime('%H:%M')} is outside business hours.\n\n**Hours for {day_name.title()}:**\n{hours_str}"

    def get_available_time_slots(self, date: datetime, slot_duration_minutes: int = 30) -> list:
        available_slots = []


        if date.tzinfo is None:
            date = self.tz.localize(date)
        else:
            date = date.astimezone(self.tz)


        day_name = date.strftime('%A').lower()


        allow_off_hours = self.reservation_config.get('allow_off_hours', False)

        if allow_off_hours:

            start_hour = 6
            end_hour = 22
        else:

            if day_name not in self.business_hours or not self.business_hours[day_name]:
                return []

            day_hours = self.business_hours[day_name]
            start_hour = int(day_hours[0].get('open', '09:00').split(':')[0])
            end_hour = int(day_hours[0].get('close', '17:00').split(':')[0])


        current_time = date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        end_time = date.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        slot_delta = timedelta(minutes=slot_duration_minutes)
        min_notice_delta = timedelta(hours=self.reservation_config.get('min_notice_hours', 2))
        max_lead_delta = timedelta(days=self.reservation_config.get('max_lead_time_days', 30))
        now = datetime.now(self.tz)

        while current_time + slot_delta <= end_time:

            if current_time >= now + min_notice_delta and current_time <= now + max_lead_delta:
                available_slots.append(current_time)

            current_time += slot_delta

        logger.info(f"[ReservationTimeValidator] Generated {len(available_slots)} slots for {day_name}")
        return available_slots

    def _format_day_hours(self, day_hours: list) -> str:
        lines = []
        for time_range in day_hours:
            open_time = time_range.get('open')
            close_time = time_range.get('close')
            if open_time and close_time:
                lines.append(f"  • {open_time} - {close_time}")
        return '\n'.join(lines)
