import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail


logger = logging.getLogger(__name__)


EVENT_LABELS = {
    'created': 'created',
    'updated': 'updated',
    'cancelled': 'cancelled',
}


def clean_email(email):
    return (email or '').strip()


def unique_emails(emails):
    recipients = []
    seen = set()
    for email in emails:
        email = clean_email(email)
        if not email:
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email)
    return recipients


def get_booking_notification_recipients(booking, previous_booking=None):
    staff_emails = User.objects.filter(
        is_staff=True,
        is_active=True,
    ).exclude(email='').values_list('email', flat=True)

    athlete_emails = [booking.athlete.email]
    if previous_booking:
        athlete_emails.append(previous_booking.get('athlete_email'))

    extra_emails = getattr(settings, 'BOOKING_NOTIFICATION_EXTRA_RECIPIENTS', [])
    return unique_emails([*staff_emails, *athlete_emails, *extra_emails])


def get_booking_details_lines(booking):
    athlete_name = booking.athlete.get_full_name() or booking.athlete.username
    return [
        f'Athlete: {athlete_name}',
        f'Username: {booking.athlete.username}',
        f'Boat: {booking.boat.name}',
        f'Date: {booking.date:%Y-%m-%d}',
        f'Time: {booking.start_time:%H:%M}-{booking.end_time:%H:%M}',
    ]


def snapshot_booking(booking):
    athlete_name = booking.athlete.get_full_name() or booking.athlete.username
    return {
        'athlete': athlete_name,
        'athlete_username': booking.athlete.username,
        'athlete_email': booking.athlete.email,
        'boat': booking.boat.name,
        'date': booking.date,
        'start_time': booking.start_time,
        'end_time': booking.end_time,
    }


def get_snapshot_details_lines(snapshot):
    return [
        f'Athlete: {snapshot["athlete"]}',
        f'Username: {snapshot["athlete_username"]}',
        f'Boat: {snapshot["boat"]}',
        f'Date: {snapshot["date"]:%Y-%m-%d}',
        f'Time: {snapshot["start_time"]:%H:%M}-{snapshot["end_time"]:%H:%M}',
    ]


def build_booking_event_email(booking, event_type, previous_booking=None):
    event_label = EVENT_LABELS[event_type]
    subject = f'Booking {event_label}: {booking.boat.name} on {booking.date:%Y-%m-%d}'
    if event_type == 'cancelled' and previous_booking:
        return subject, '\n'.join([
            'A booking has been cancelled.',
            '',
            'Cancelled booking:',
            *get_snapshot_details_lines(previous_booking),
        ])

    lines = [
        f'A booking has been {event_label}.',
        '',
        'Current booking:',
        *get_booking_details_lines(booking),
    ]

    if previous_booking:
        lines.extend([
            '',
            'Previous booking:',
            *get_snapshot_details_lines(previous_booking),
        ])

    return subject, '\n'.join(lines)


def notify_booking_event(booking, event_type, previous_booking=None):
    if event_type not in EVENT_LABELS:
        raise ValueError(f'Unsupported booking notification event: {event_type}')

    recipients = get_booking_notification_recipients(booking, previous_booking)
    if not recipients:
        logger.info('Skipping booking notification: no recipients configured.')
        return False

    subject, message = build_booking_event_email(booking, event_type, previous_booking)
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception:
        logger.exception(
            'Failed to send %s booking notification for booking %s.',
            event_type,
            booking.pk,
        )
        return False

    return True


def notify_new_booking(booking):
    return notify_booking_event(booking, 'created')
