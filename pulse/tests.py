from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import NotificationLog, PriceAlert, UserProfile
from .tasks import check_prices, price_meets_threshold, send_notification


def make_alert(user, origin='DEL', destination='BOM', threshold=4500,
               status=PriceAlert.Status.ACTIVE):
    return PriceAlert.objects.create(
        user=user, origin=origin, destination=destination,
        threshold_price=threshold, status=status,
    )


class PriceThresholdTest(TestCase):
    def test_price_below_threshold_triggers_alert(self):
        self.assertTrue(price_meets_threshold(4200, 4500))

    def test_price_above_threshold_does_not_trigger(self):
        self.assertFalse(price_meets_threshold(5000, 4500))

    def test_price_equal_to_threshold_triggers_alert(self):
        self.assertTrue(price_meets_threshold(4500, Decimal('4500.00')))


class CheckPricesTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='testpass123')

    def _feed(self, price, status_code=200):
        resp = MagicMock(status_code=status_code)
        resp.json.return_value = {'route': 'DEL-BOM', 'price': price}
        return resp

    @patch('pulse.tasks.send_notification.delay')
    @patch('pulse.tasks.requests.get')
    def test_fires_only_for_alerts_that_meet_threshold(self, mock_get, mock_delay):
        mock_get.return_value = self._feed(4200)
        hit = make_alert(self.user, threshold=4500)
        make_alert(self.user, threshold=4000)
        make_alert(self.user, threshold=9000, status=PriceAlert.Status.INACTIVE)
        check_prices()
        mock_delay.assert_called_once_with(hit.id, 4200)
        # one feed call per distinct route, not per alert
        self.assertEqual(mock_get.call_count, 1)

    @patch('pulse.tasks.send_notification.delay')
    @patch('pulse.tasks.requests.get')
    def test_feed_failure_is_skipped(self, mock_get, mock_delay):
        make_alert(self.user)
        mock_get.side_effect = requests.ConnectionError()
        check_prices()
        mock_get.side_effect = None
        mock_get.return_value = self._feed(1, status_code=404)
        check_prices()
        mock_delay.assert_not_called()


class SendNotificationTaskTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='testpass123')
        self.alert = make_alert(self.user)

    def test_creates_log_and_marks_alert_triggered(self):
        send_notification(self.alert.id, 4200)
        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.TRIGGERED)
        log = NotificationLog.objects.get()
        self.assertEqual(log.triggered_price, 4200)
        self.assertIn('DEL-BOM', log.message)

    def test_does_not_fire_twice_or_for_inactive_alert(self):
        send_notification(self.alert.id, 4200)
        send_notification(self.alert.id, 4100)
        self.assertEqual(NotificationLog.objects.count(), 1)
        other = make_alert(self.user, status=PriceAlert.Status.INACTIVE)
        send_notification(other.id, 100)
        self.assertEqual(NotificationLog.objects.count(), 1)


class NotificationLogTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.alert = make_alert(self.user)

    def test_notification_log_created_with_correct_message(self):
        log = NotificationLog.objects.create(
            alert=self.alert, triggered_price=4200,
            message='Price dropped to 4200 for DEL-BOM',
        )
        self.assertEqual(log.triggered_price, 4200)
        self.assertEqual(log.alert, self.alert)
        self.assertIn('DEL-BOM', log.message)


class AuthApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_defaults_role_to_user_and_ignores_body_role(self):
        r = self.client.post('/api/auth/register/', {
            'username': 'alice', 'password': 'securepass',
            'email': 'alice@example.com', 'role': 'admin',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['role'], 'user')
        self.assertIn('access', r.json())
        self.assertEqual(User.objects.get(username='alice').profile.role, UserProfile.Role.USER)

    def test_register_duplicate_username_returns_400(self):
        User.objects.create_user(username='alice', password='securepass')
        r = self.client.post('/api/auth/register/', {
            'username': 'alice', 'password': 'securepass'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_login_success_and_failure(self):
        User.objects.create_user(username='alice', password='securepass')
        ok = self.client.post('/api/auth/login/', {
            'username': 'alice', 'password': 'securepass'}, format='json')
        self.assertEqual(ok.status_code, 200)
        self.assertIn('access', ok.json())
        bad = self.client.post('/api/auth/login/', {
            'username': 'alice', 'password': 'wrong'}, format='json')
        self.assertEqual(bad.status_code, 401)


class AlertScopingTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='user1', password='pass12345')
        self.user2 = User.objects.create_user(username='user2', password='pass12345')
        self.a1 = make_alert(self.user1, 'DEL', 'BOM', 4500)
        self.a2 = make_alert(self.user2, 'BLR', 'HYD', 2000)
        self.client = APIClient()

    def test_user_only_sees_own_alerts(self):
        self.client.force_authenticate(self.user1)
        data = self.client.get('/api/alerts/').json()
        self.assertEqual([a['id'] for a in data], [self.a1.id])

    def test_user_cannot_see_other_users_alerts(self):
        self.client.force_authenticate(self.user1)
        origins = [a['origin'] for a in self.client.get('/api/alerts/').json()]
        self.assertNotIn('BLR', origins)

    def test_list_is_empty_list_when_no_alerts(self):
        user3 = User.objects.create_user(username='user3', password='pass12345')
        self.client.force_authenticate(user3)
        r = self.client.get('/api/alerts/')
        self.assertEqual((r.status_code, r.json()), (200, []))

    def test_create_requires_token_and_uses_request_user(self):
        body = {'origin': 'del', 'destination': 'bom', 'threshold_price': '4500',
                'user': self.user2.id}
        self.assertEqual(self.client.post('/api/alerts/', body, format='json').status_code, 401)
        self.client.force_authenticate(self.user1)
        r = self.client.post('/api/alerts/', body, format='json')
        self.assertEqual(r.status_code, 201)
        alert = PriceAlert.objects.get(id=r.json()['id'])
        self.assertEqual(alert.user, self.user1)
        self.assertEqual(alert.origin, 'DEL')

    def test_delete_deactivates_own_alert(self):
        self.client.force_authenticate(self.user1)
        r = self.client.delete(f'/api/alerts/{self.a1.id}/')
        self.assertEqual((r.status_code, r.json()), (200, {'status': 'inactive'}))
        self.a1.refresh_from_db()
        self.assertEqual(self.a1.status, PriceAlert.Status.INACTIVE)

    def test_delete_other_users_or_missing_alert_returns_404(self):
        self.client.force_authenticate(self.user1)
        self.assertEqual(self.client.delete(f'/api/alerts/{self.a2.id}/').status_code, 404)
        self.assertEqual(self.client.delete('/api/alerts/99999/').status_code, 404)
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.status, PriceAlert.Status.ACTIVE)

    def test_missing_and_foreign_alert_responses_are_identical(self):
        self.client.force_authenticate(self.user1)
        foreign = self.client.delete(f'/api/alerts/{self.a2.id}/')
        missing = self.client.delete('/api/alerts/99999/')
        self.assertEqual(foreign.content, missing.content)


class PriceFeedTest(TestCase):
    def test_valid_route_returns_price_in_range(self):
        r = self.client.get('/api/flights/price/', {'route': 'DEL-BOM'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(3000 <= r.json()['price'] <= 7000)

    def test_unknown_route_returns_404(self):
        self.assertEqual(self.client.get('/api/flights/price/', {'route': 'XYZ-ABC'}).status_code, 404)


class AdminSummaryTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username='boss', password='pass12345')
        self.admin.profile.role = UserProfile.Role.ADMIN
        self.admin.profile.save()
        self.user = User.objects.create_user(username='u', password='pass12345')

    def test_regular_user_gets_403(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get('/api/admin/summary/').status_code, 403)

    def test_no_token_gets_401(self):
        self.assertEqual(self.client.get('/api/admin/summary/').status_code, 401)

    def test_admin_sees_stats(self):
        a = make_alert(self.user, 'DEL', 'BOM')
        make_alert(self.user, 'DEL', 'BOM')
        make_alert(self.user, 'BLR', 'HYD', status=PriceAlert.Status.TRIGGERED)
        NotificationLog.objects.create(alert=a, triggered_price=1, message='m')
        self.client.force_authenticate(self.admin)
        r = self.client.get('/api/admin/summary/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(
            (d['total_alerts'], d['active_alerts'], d['triggered_alerts'], d['total_notifications']),
            (3, 2, 1, 1))
        self.assertEqual(d['top_routes'][0], {'route': 'DEL-BOM', 'alert_count': 2})
