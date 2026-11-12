"""Business settings use cases: profile, opening hours and the service catalogue."""

from __future__ import annotations

from datetime import time
from itertools import pairwise

from citabot.domain.errors import ValidationError
from citabot.domain.models import Business, OpeningHours, Service, TimeRange

from .ports import BusinessRepository, UnitOfWork

ALLOWED_SLOT_MINUTES = (15, 20, 30, 45, 60)
MAX_SERVICE_NAME = 24  # WhatsApp list rows show at most 24 characters


class BusinessService:
    def __init__(self, uow: UnitOfWork, businesses: BusinessRepository) -> None:
        self._uow = uow
        self._businesses = businesses

    def get(self, business_id: int) -> Business:
        return self._businesses.get(business_id)

    def update(
        self,
        business_id: int,
        name: str,
        welcome_message: str,
        slot_minutes: int,
        opening_hours: dict[int, list[tuple[str, str]]],
    ) -> Business:
        name, welcome_message = name.strip(), welcome_message.strip()
        if not 1 <= len(name) <= 80:
            raise ValidationError("El nombre del negocio es obligatorio (máximo 80 caracteres).")
        if not 1 <= len(welcome_message) <= 500:
            raise ValidationError("El mensaje de bienvenida es obligatorio (máximo 500 caracteres).")
        if slot_minutes not in ALLOWED_SLOT_MINUTES:
            raise ValidationError(f"El intervalo debe ser uno de {ALLOWED_SLOT_MINUTES} minutos.")
        hours = _parse_opening_hours(opening_hours)
        with self._uow:
            business = self._businesses.get(business_id)
            business.name = name
            business.welcome_message = welcome_message
            business.slot_minutes = slot_minutes
            business.opening_hours = hours
            self._businesses.save(business)
            return business

    def list_services(self, business_id: int) -> list[Service]:
        return self._businesses.list_services(business_id)

    def get_service(self, business_id: int, service_id: int) -> Service:
        return self._businesses.get_service(business_id, service_id)

    def add_service(self, business_id: int, name: str, duration_minutes: int, price: str | None) -> Service:
        name, price = _validate_service(name, duration_minutes, price)
        with self._uow:
            return self._businesses.add_service(business_id, name, duration_minutes, price)

    def update_service(
        self, business_id: int, service_id: int, name: str, duration_minutes: int, price: str | None
    ) -> Service:
        name, price = _validate_service(name, duration_minutes, price)
        with self._uow:
            service = self._businesses.get_service(business_id, service_id)
            service.name, service.duration_minutes, service.price = name, duration_minutes, price
            self._businesses.save_service(service)
            return service

    def remove_service(self, business_id: int, service_id: int) -> None:
        """Soft delete: past appointments keep pointing at the service."""
        with self._uow:
            service = self._businesses.get_service(business_id, service_id)
            service.active = False
            self._businesses.save_service(service)


def _validate_service(name: str, duration_minutes: int, price: str | None) -> tuple[str, str | None]:
    name = name.strip()
    price = (price or "").strip() or None
    if not 1 <= len(name) <= MAX_SERVICE_NAME:
        raise ValidationError(f"El nombre del servicio es obligatorio (máximo {MAX_SERVICE_NAME}).")
    if not 5 <= duration_minutes <= 480 or duration_minutes % 5:
        raise ValidationError("La duración debe estar entre 5 y 480 minutos, en múltiplos de 5.")
    if price and len(price) > 30:
        raise ValidationError("El precio admite máximo 30 caracteres.")
    return name, price


def _parse_opening_hours(raw: dict[int, list[tuple[str, str]]]) -> OpeningHours:
    hours: OpeningHours = {}
    for weekday, ranges in raw.items():
        if weekday not in range(7):
            raise ValidationError("Día de la semana inválido.")
        parsed: list[TimeRange] = []
        for start, end in ranges:
            try:
                current = TimeRange(time.fromisoformat(start), time.fromisoformat(end))
            except ValueError as exc:
                raise ValidationError("Cada franja necesita una hora de inicio anterior al cierre.") from exc
            parsed.append(current)
        parsed.sort(key=lambda r: r.start)
        if any(a.end > b.start for a, b in pairwise(parsed)):
            raise ValidationError("Las franjas de un mismo día no pueden solaparse.")
        if parsed:
            hours[weekday] = parsed
    return hours
