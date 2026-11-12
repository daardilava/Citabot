"""Appointment use cases: availability, booking, cancelling."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from citabot.domain.errors import SlotUnavailableError, ValidationError
from citabot.domain.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    Business,
    Service,
)
from citabot.domain.scheduling import available_slots

from .ports import (
    AppointmentRepository,
    BusinessRepository,
    Clock,
    ContactRepository,
    UnitOfWork,
)


class BookingService:
    """MVP assumption: one bookable resource (one chair/agenda) per business."""

    def __init__(
        self,
        uow: UnitOfWork,
        businesses: BusinessRepository,
        appointments: AppointmentRepository,
        contacts: ContactRepository,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._businesses = businesses
        self._appointments = appointments
        self._contacts = contacts
        self._clock = clock

    def slots_for(self, business: Business, service: Service, day: date) -> list[datetime]:
        day_start = datetime.combine(day, datetime.min.time())
        booked = self._appointments.list_between(
            business.id, day_start, day_start + timedelta(days=1), only_confirmed=True
        )
        return available_slots(
            day=day,
            opening=business.ranges_for(day.weekday()),
            slot_minutes=business.slot_minutes,
            duration_minutes=service.duration_minutes,
            busy=[(a.starts_at, a.ends_at) for a in booked],
            now=self._clock.now(),
        )

    def next_days_with_slots(
        self, business: Business, service: Service, count: int = 4, horizon_days: int = 21
    ) -> list[date]:
        today = self._clock.now().date()
        days: list[date] = []
        for offset in range(horizon_days):
            day = today + timedelta(days=offset)
            if self.slots_for(business, service, day):
                days.append(day)
                if len(days) == count:
                    break
        return days

    def book(
        self,
        business_id: int,
        contact_id: int,
        service_id: int,
        starts_at: datetime,
        source: AppointmentSource,
    ) -> Appointment:
        # The availability check and the insert share one transaction, so two
        # customers cannot take the same slot.
        with self._uow:
            business = self._businesses.get(business_id)
            service = self._businesses.get_service(business_id, service_id)
            if not service.active:
                raise ValidationError("El servicio no está activo.")
            if starts_at not in self.slots_for(business, service, starts_at.date()):
                raise SlotUnavailableError("Ese horario ya no está disponible.")
            return self._appointments.add(
                business_id=business_id,
                contact_id=contact_id,
                service_id=service_id,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=service.duration_minutes),
                source=source,
                now=self._clock.now(),
            )

    def book_from_dashboard(
        self, business_id: int, phone: str, name: str, service_id: int, starts_at: datetime
    ) -> Appointment:
        """A teammate books on behalf of a customer (phone call, walk-in)."""
        phone, name = phone.strip(), name.strip()
        if not phone or not 1 <= len(name) <= 80:
            raise ValidationError("El nombre y el teléfono del cliente son obligatorios.")
        with self._uow:
            contact = self._contacts.find_by_phone(business_id, phone)
            if contact is None:
                contact = self._contacts.add(business_id, phone, name, self._clock.now())
            elif not contact.name:
                contact.name = name
                self._contacts.save(contact)
            return self.book(business_id, contact.id, service_id, starts_at, AppointmentSource.DASHBOARD)

    def set_status(self, business_id: int, appointment_id: int, status: AppointmentStatus) -> Appointment:
        with self._uow:
            appointment = self._appointments.get(business_id, appointment_id)
            if appointment.status is AppointmentStatus.CANCELLED and status is not appointment.status:
                raise ValidationError("Una cita cancelada no se puede reactivar; crea una nueva.")
            appointment.status = status
            self._appointments.save(appointment)
            return appointment

    def get(self, business_id: int, appointment_id: int) -> Appointment:
        return self._appointments.get(business_id, appointment_id)

    def upcoming_for_contact(self, contact_id: int) -> list[Appointment]:
        return self._appointments.list_upcoming_for_contact(contact_id, self._clock.now())

    def list_between(self, business_id: int, start: datetime, end: datetime) -> list[Appointment]:
        return self._appointments.list_between(business_id, start, end)
