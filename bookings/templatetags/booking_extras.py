from django import template

register = template.Library()

@register.simple_tag
def get_slot_bookings(booking_map, boat_id, day, slot_start, slot_end):
    """Return bookings for a boat/day that overlap the displayed time slot."""
    key = (boat_id, str(day))
    bookings = booking_map.get(key, [])
    return [
        booking for booking in bookings
        if booking.start_time < slot_end and booking.end_time > slot_start
    ]


@register.simple_tag
def user_booking(bookings, user):
    for booking in bookings:
        if booking.athlete_id == user.id:
            return booking
    return None
