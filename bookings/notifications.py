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


def booking_crew_emails(booking):
    return [
        athlete.user.email
        for athlete in booking.crew.select_related('user')
        if athlete.user and athlete.user.email
    ]


def get_booking_notification_recipients(booking, previous_booking=None):
    staff_emails = User.objects.filter(
        is_staff=True,
        is_active=True,
    ).exclude(email='').values_list('email', flat=True)

    previous_emails = previous_booking.get('crew_emails', []) if previous_booking else []
    extra_emails = getattr(settings, 'BOOKING_NOTIFICATION_EXTRA_RECIPIENTS', [])
    return unique_emails([*staff_emails, *booking_crew_emails(booking), *previous_emails, *extra_emails])


def get_booking_details_lines(booking):
    return [
        f'Boat: {booking.boat.name}',
        f'Slot: {booking.slot.date:%Y-%m-%d} {booking.slot.start_time:%H:%M}-{booking.slot.end_time:%H:%M}',
        f'Workout: {booking.slot.workout.name if booking.slot.workout else "-"}',
        f'Crew: {booking.crew_names()}',
    ]


def snapshot_booking(booking):
    return {
        'boat': booking.boat.name,
        'slot_date': booking.slot.date,
        'start_time': booking.slot.start_time,
        'end_time': booking.slot.end_time,
        'workout': booking.slot.workout.name if booking.slot.workout else '',
        'crew': booking.crew_names(),
        'crew_emails': booking_crew_emails(booking),
    }


def get_snapshot_details_lines(snapshot):
    return [
        f'Boat: {snapshot["boat"]}',
        f'Slot: {snapshot["slot_date"]:%Y-%m-%d} {snapshot["start_time"]:%H:%M}-{snapshot["end_time"]:%H:%M}',
        f'Workout: {snapshot["workout"] or "-"}',
        f'Crew: {snapshot["crew"]}',
    ]


def build_booking_event_email(booking, event_type, previous_booking=None):
    event_label = EVENT_LABELS[event_type]
    subject = f'Booking {event_label}: {booking.boat.name} on {booking.slot.date:%Y-%m-%d}'
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
