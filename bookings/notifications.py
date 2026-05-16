import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


logger = logging.getLogger(__name__)


EVENT_LABELS = {
    'created': 'creata',
    'updated': 'modificata',
    'cancelled': 'cancellata',
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


def get_booking_details(booking):
    return {
        'boat': booking.boat.name,
        'slot_date': booking.slot.date,
        'start_time': booking.slot.start_time,
        'end_time': booking.slot.end_time,
        'workout': booking.slot.workout.name if booking.slot.workout else '',
        'crew': booking.crew_names(),
    }


def get_booking_details_lines(booking):
    details = get_booking_details(booking)
    return get_details_lines(details)


def snapshot_booking(booking):
    snapshot = get_booking_details(booking)
    snapshot['crew_emails'] = booking_crew_emails(booking)
    return snapshot


def get_snapshot_details(snapshot):
    return {
        'boat': snapshot['boat'],
        'slot_date': snapshot['slot_date'],
        'start_time': snapshot['start_time'],
        'end_time': snapshot['end_time'],
        'workout': snapshot['workout'],
        'crew': snapshot['crew'],
    }


def get_details_lines(details):
    return [
        f'Barca: {details["boat"]}',
        f'Slot: {details["slot_date"]:%Y-%m-%d} {details["start_time"]:%H:%M}-{details["end_time"]:%H:%M}',
        f'Allenamento: {details["workout"] or "-"}',
        f'Equipaggio: {details["crew"]}',
    ]


def get_snapshot_details_lines(snapshot):
    return get_details_lines(get_snapshot_details(snapshot))


def build_booking_event_email(booking, event_type, previous_booking=None):
    event_label = EVENT_LABELS[event_type]
    current_details = get_booking_details(booking)
    previous_details = get_snapshot_details(previous_booking) if previous_booking else None
    cancelled_details = previous_details if event_type == 'cancelled' and previous_details else None
    subject = f'Prenotazione {event_label}: {booking.boat.name} il {booking.slot.date:%Y-%m-%d}'

    if cancelled_details:
        message = '\n'.join([
            'Una prenotazione è stata cancellata.',
            '',
            'Prenotazione cancellata:',
            *get_details_lines(cancelled_details),
        ])
    else:
        lines = [
            f'Una prenotazione è stata {event_label}.',
            '',
            'Prenotazione corrente:',
            *get_details_lines(current_details),
        ]

        if previous_details:
            lines.extend([
                '',
                'Prenotazione precedente:',
                *get_details_lines(previous_details),
            ])

        message = '\n'.join(lines)

    html_message = render_to_string('bookings/emails/booking_event.html', {
        'event_label': event_label,
        'booking': current_details,
        'previous_booking': previous_details,
        'cancelled_booking': cancelled_details,
    })
    return subject, message, html_message


def send_multipart_email(subject, message, html_message, recipients):
    email = EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    email.attach_alternative(html_message, 'text/html')
    email.send(fail_silently=False)


def notify_booking_event(booking, event_type, previous_booking=None):
    if event_type not in EVENT_LABELS:
        raise ValueError(f'Unsupported booking notification event: {event_type}')

    recipients = get_booking_notification_recipients(booking, previous_booking)
    if not recipients:
        logger.info('Skipping booking notification: no recipients configured.')
        return False

    subject, message, html_message = build_booking_event_email(booking, event_type, previous_booking)
    try:
        send_multipart_email(subject, message, html_message, recipients)
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


def build_welcome_email(user):
    subject = 'Benvenuto in SCP Helper'
    display_name = user.get_full_name() or user.get_username()
    message = '\n'.join([
        f'Ciao {display_name},',
        '',
        'Il tuo account su SCP Helper è stato creato.',
        'Puoi accedere con il tuo nome utente e la password che ti è stata fornita.',
        '',
        'Se non ti aspettavi questa email, ignorala oppure contatta l\'amministratore del club.',
    ])
    html_message = render_to_string('bookings/emails/welcome.html', {
        'display_name': display_name,
        'username': user.get_username(),
    })
    return subject, message, html_message


def send_welcome_email(user):
    if not user.email:
        return False

    subject, message, html_message = build_welcome_email(user)
    try:
        send_multipart_email(subject, message, html_message, [user.email])
    except Exception:
        logger.exception('Failed to send welcome email for user %s.', user.pk)
        return False

    return True
