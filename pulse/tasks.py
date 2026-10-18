import logging
from decimal import Decimal

import requests
from celery import shared_task
from django.conf import settings
from django.db import transaction

from .models import NotificationLog, PriceAlert

logger = logging.getLogger(__name__)


def price_meets_threshold(current_price, threshold_price):
    return Decimal(str(current_price)) <= Decimal(str(threshold_price))


@shared_task
def check_prices():
    active_alerts = PriceAlert.objects.filter(status=PriceAlert.Status.ACTIVE)
    routes = active_alerts.values_list('origin', 'destination').distinct()

    for origin, destination in routes:
        route = f'{origin}-{destination}'
        try:
            response = requests.get(
                settings.PRICE_FEED_URL,
                params={'route': route},
                timeout=settings.PRICE_FEED_TIMEOUT,
            )
        except requests.RequestException:
            logger.warning('Price feed unreachable for route %s', route)
            continue
        if response.status_code != 200:
            continue
        try:
            current_price = response.json().get('price')
        except ValueError:
            continue
        if current_price is None:
            continue

        for alert in active_alerts.filter(origin=origin, destination=destination):
            if price_meets_threshold(current_price, alert.threshold_price):
                send_notification.delay(alert.id, current_price)


@shared_task
def send_notification(alert_id, triggered_price):
    with transaction.atomic():
        alert = (
            PriceAlert.objects.select_for_update()
            .filter(id=alert_id, status=PriceAlert.Status.ACTIVE)
            .first()
        )
        # Skip if deleted, deactivated, or already triggered by an earlier task.
        if alert is None:
            return
        message = (
            f'Price alert triggered! {alert.origin}-{alert.destination} '
            f'is now ₹{triggered_price} - below your threshold of '
            f'₹{alert.threshold_price}'
        )
        NotificationLog.objects.create(
            alert=alert, triggered_price=triggered_price, message=message
        )
        alert.status = PriceAlert.Status.TRIGGERED
        alert.save(update_fields=['status'])
