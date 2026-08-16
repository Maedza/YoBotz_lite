# Reservation Time Configuration

## Overview

The reservation system includes comprehensive time validation configurable per business. Each business can set their own reservation rules through `business_config.yaml`.

## Configuration Structure

In `businesses/{business_name}/business_config.yaml`:

```yaml
# =============================
# Reservation Time Limits
# =============================
reservation:
  # How far in advance customers can make reservations (in days)
  max_lead_time_days: 30
  # Minimum notice required (in hours)
  min_notice_hours: 2
  # How long a reservation is held without confirmation (in minutes)
  confirmation_timeout_minutes: 15
  # Maximum duration for a single reservation (in hours)
  max_duration_hours: 4
  # Allow reservations during closed hours (true/false)
  allow_off_hours: false
```

## Configuration Options

### `max_lead_time_days`

**Purpose**: Limits how far in advance customers can book

**Default**: `30`

**Example Values**:
- `7` - Bookings up to 1 week ahead
- `30` - Bookings up to 1 month ahead
- `90` - Bookings up to 3 months ahead

**Use Case**:
- **Short duration (7-14 days)**: High-demand restaurants, special events
- **Medium duration (30 days)**: Standard restaurants, cafes
- **Long duration (90+ days)**: Hotels, wedding venues, corporate events

---

### `min_notice_hours`

**Purpose**: Minimum time required before a reservation

**Default**: `2`

**Example Values**:
- `1` - 1 hour notice (casual dining)
- `2` - 2 hours notice (standard restaurant)
- `24` - 1 day notice (fine dining)
- `48` - 2 days notice (special events, catered services)

**Use Case**:
- **1-2 hours**: Fast food, casual dining, bakeries
- **4-8 hours**: Restaurants, cafes, salons
- **24+ hours**: Fine dining, custom cakes, special events

---

### `confirmation_timeout_minutes`

**Purpose**: How long to hold a reservation without confirmation

**Default**: `15`

**Example Values**:
- `10` - 10 minutes (fast-paced service)
- `15` - 15 minutes (standard)
- `30` - 30 minutes (leisure service)

**Use Case**:
- **Short timeout (5-10 min)**: Prevents stale reservations in high-demand venues
- **Medium timeout (15-20 min)**: Balances availability and convenience
- **Long timeout (30+ min)**: Gives customers more time to confirm

**Note**: This is used when the system requires explicit confirmation (not payment-based).

---

### `max_duration_hours`

**Purpose**: Maximum length of a single reservation

**Default**: `4`

**Example Values**:
- `2` - 2 hours maximum (quick service)
- `4` - 4 hours maximum (standard dining)
- `6` - 6 hours maximum (extended events)

**Use Case**:
- **1-2 hours**: Quick service restaurants, coffee shops, bakeries
- **3-4 hours**: Standard restaurants, salons, consulting
- **6+ hours**: Events, parties, extended services

---

### `allow_off_hours`

**Purpose**: Allow reservations outside regular business hours

**Default**: `false`

**Example Values**:
- `false` - Reservations only during business hours
- `true` - Reservations allowed anytime

**Use Case**:
- **`false`**: Most businesses (restaurants, retail, service providers)
- **`true`**: Special events, after-hours parties, corporate bookings

---

## Example Configurations

### Bakery (Yo Bakery)

```yaml
reservation:
  max_lead_time_days: 30
  min_notice_hours: 2
  confirmation_timeout_minutes: 15
  max_duration_hours: 4
  allow_off_hours: false
```

**Rationale**:
- 30 days advance for custom cake orders
- 2 hours notice for pickup
- 4 hours max duration (catering or events)
- No off-hours reservations (closed hours)

---

### Restaurant (Fine Dining)

```yaml
reservation:
  max_lead_time_days: 60
  min_notice_hours: 24
  confirmation_timeout_minutes: 30
  max_duration_hours: 3
  allow_off_hours: false
```

**Rationale**:
- 60 days for special occasions
- 24 hours notice for preparation
- 3 hours max dining time
- No off-hours

---

### Salon/Spa

```yaml
reservation:
  max_lead_time_days: 14
  min_notice_hours: 4
  confirmation_timeout_minutes: 10
  max_duration_hours: 2
  allow_off_hours: false
```

**Rationale**:
- 2 weeks advance booking
- 4 hours notice for appointments
- 2 hours max service duration
- No off-hours

---

## Using the Reservation Validator

The `ReservationTimeValidator` class provides methods to validate reservation times:

### Initialize

```python
from core.business_loader import load_business_config
from smart_engine.features.ordering.reservation_time_validator import ReservationTimeValidator

# Load business config
config = load_business_config("yo_bakery")

# Create validator
validator = ReservationTimeValidator("yo_bakery", config)
```

### Validate a Reservation Time

```python
from datetime import datetime
import pytz

# Create requested time (timezone-aware)
tz = pytz.timezone("America/New_York")
requested_time = tz.localize(datetime(2024, 1, 15, 14, 30))

# Validate
is_valid, message = validator.validate_reservation_time(requested_time)

if is_valid:
    print("Reservation time is valid!")
else:
    print(f"Error: {message}")
```

### Get Available Time Slots

```python
from datetime import datetime
import pytz

# Get date
tz = pytz.timezone("America/New_York")
date = tz.localize(datetime(2024, 1, 15))

# Get available slots (30-minute intervals)
slots = validator.get_available_time_slots(date, slot_duration_minutes=30)

for slot in slots:
    print(f"Available: {slot.strftime('%H:%M')}")
```

### Get Confirmation Timeout

```python
# Get how long a reservation is held without confirmation (minutes)
timeout_minutes = validator.get_confirmation_timeout()
print(f"Reservation held for {timeout_minutes} minutes")
```

### List Available Days

```python
# Get the next N days that have business hours
days = validator.get_available_days(days_ahead=7)
for day in days:
    print(day.strftime("%Y-%m-%d %A"))
```

## Integration with Ordering Manager

The `OrderingManager` wraps the validator for use inside the booking flow:

```python
from smart_engine.features.ordering.ordering_manager import OrderingManager

manager = OrderingManager("yo_bakery")

# Get the next 7 days with availability (for a day picker)
days = manager.get_available_days(days_ahead=7)

# Combine a selected date with a time string, then validate it
is_valid, message = manager.handle_time_input("14:30", "2024-01-15")
```

`handle_time_input` internally runs `is_time_within_hours` → `parse_time_input` → `validate_reservation_time` and returns a user-ready message on failure.

## Error Messages

The validator provides user-friendly error messages:

- **Past time**: "❌ Cannot make reservations in the past. Please select a future date and time."
- **Insufficient notice**: "❌ Minimum notice required: 2 hours. Please choose a time at least 2 hours from now."
- **Exceeds lead time**: "❌ Maximum lead time: 30 days. Please choose a date within the next 30 days."
- **Outside business hours**: "❌ That time is outside our business hours.\n\n**Hours for Monday:**\n  • 08:00 - 18:00"

## Timezone Handling

The validator automatically:
1. Uses business timezone from config (`timezone: "America/New_York"`)
2. Converts naive datetimes to business timezone
3. Handles daylight saving time automatically
4. Validates in business timezone regardless of user's timezone

## Best Practices

1. **Set appropriate lead times**: Balance customer convenience with operational needs
2. **Use reasonable notice periods**: Not too short (business needs prep time) or too long (customer inconvenience)
3. **Consider confirmation timeout**: Shorter timeouts free up slots faster but may frustrate customers
4. **Match duration to service type**: Quick services need shorter max durations
5. **Test configurations**: Validate rules work as expected with real scenarios

## Troubleshooting

### Issue: All times are invalid

**Cause**: Business hours not defined for the day

**Solution**: Add business hours for all days in `business_config.yaml`:
```yaml
business_hours:
  monday:
    - open: "08:00"
      close: "18:00"
  # ... other days
```

### Issue: Past times are accepted

**Cause**: Timezone mismatch - user sending time in different timezone

**Solution**: Ensure all times are converted to business timezone before validation

### Issue: "Unknown timezone" error

**Cause**: Invalid timezone string in config

**Solution**: Use valid IANA timezone names (e.g., "America/New_York", "Europe/London")
