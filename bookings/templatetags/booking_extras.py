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
