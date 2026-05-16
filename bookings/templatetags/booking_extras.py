from django import template


register = template.Library()


@register.simple_tag
def get_slot_booking(booking_map, boat_id, slot_id):
    return booking_map.get((boat_id, slot_id))


@register.simple_tag
def athlete_in_booking(booking, athlete):
    if not booking or not athlete:
        return False
    return any(member.pk == athlete.pk for member in booking.crew.all())


# Italian date helpers
@register.filter
def it_day_abbr(value):
    """Return the Italian 3-letter weekday abbreviation for a date.

    Monday -> 'Lun', Tuesday -> 'Mar', ...
    """
    if not value:
        return ''
    try:
        weekday = value.weekday()
    except Exception:
        return ''
    abbr = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
    return abbr[weekday]


@register.filter
def ddmmyyyy(value):
    """Format a date as DD/MM/YYYY."""
    if not value:
        return ''
    try:
        return value.strftime('%d/%m/%Y')
    except Exception:
        return ''
