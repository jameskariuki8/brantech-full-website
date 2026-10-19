"""Rate limits on the public endpoints a bot would hammer, other than /login/
(see test_login_throttle.py).

Each test checks that the limit refuses BEFORE the expensive or harmful part
runs: the email, the model call, the password hash.
"""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from brand.test_turnstile import DISABLED, ENABLED, cloudflare_says
from brand.views import PasswordResetView

RESET = '/accounts/password_reset/'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PasswordResetLimitTest(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user('amina', email='amina@example.com', password='pw-12345678')

    def request_reset(self, email='amina@example.com', ip='198.51.100.7', **extra):
        return self.client.post(RESET, {'email': email, **extra}, HTTP_CF_CONNECTING_IP=ip)

    @DISABLED
    def test_a_reset_sends_one_email(self):
        response = self.request_reset()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    @ENABLED
    def test_a_reset_without_the_challenge_sends_nothing(self):
        response = self.request_reset()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    @ENABLED
    def test_a_reset_with_the_challenge_is_sent(self):
        with cloudflare_says({'success': True}):
            self.request_reset(**{'cf-turnstile-response': 'token'})
        self.assertEqual(len(mail.outbox), 1)

    @DISABLED
    def test_one_address_is_refused_past_its_limit(self):
        for n in range(PasswordResetView.PASSWORD_RESET_ADDRESS_LIMIT):
            self.request_reset(email=f'nobody{n}@example.com')
        response = self.request_reset()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(mail.outbox), 0)

    @DISABLED
    def test_one_inbox_stops_receiving_mail_from_many_addresses(self):
        """The page still says the mail is on its way, so the limit does not
        reveal whether the address has an account."""
        limit = PasswordResetView.PASSWORD_RESET_EMAIL_LIMIT
        for n in range(limit + 3):
            response = self.request_reset(ip=f'198.51.100.{n + 10}')
            self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), limit)

    def test_the_sites_own_pages_are_used_not_django_admins(self):
        """admin comes before brand in INSTALLED_APPS, so the bare
        registration/ names resolve to admin's plain templates."""
        self.assertTemplateUsed(self.client.get(RESET), 'brand/auth/password_reset_form.html')
        self.assertTemplateUsed(
            self.client.get(RESET + 'done/'), 'brand/auth/password_reset_done.html',
        )
        response = self.client.get('/accounts/reset/xx/bad-token/')
        self.assertTemplateUsed(response, 'brand/auth/password_reset_confirm.html')
        self.assertContains(response, 'expired or has already been used')
        self.assertTemplateUsed(
            self.client.get('/accounts/reset/done/'), 'brand/auth/password_reset_complete.html',
        )

    def test_the_login_page_links_to_it(self):
        self.assertContains(self.client.get('/login/'), f'href="{RESET}"')


class ChatLimitTest(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(CHAT_RATE_LIMIT_COUNT=2, CHAT_RATE_LIMIT_WINDOW_SECONDS=600)
    def test_chat_is_refused_before_the_model_is_called(self):
        reply = {'response': 'hi', 'metadata': {}}
        with patch('ai_workflows.views.get_chatbot_response', return_value=reply) as model:
            for _ in range(3):
                response = self.client.post(
                    '/api/ai/chat/', json.dumps({'message': 'hello'}),
                    content_type='application/json',
                )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(model.call_count, 2)

    def test_a_failure_does_not_echo_the_exception(self):
        with patch('ai_workflows.views.get_chatbot_response', side_effect=RuntimeError('key=SECRET')):
            response = self.client.post(
                '/api/ai/chat/', json.dumps({'message': 'hello'}),
                content_type='application/json',
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('SECRET', response.json()['error'])


class AppointmentLookupLimitTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_lookups_are_capped_per_address(self):
        body = json.dumps({'id': 1, 'email': 'x@example.com', 'phone': '+254700000000'})
        statuses = [
            self.client.post('/appointments/get/', body, content_type='application/json').status_code
            for _ in range(11)
        ]
        self.assertEqual(statuses[:10], [404] * 10)
        self.assertEqual(statuses[10], 429)

    def test_availability_checks_are_capped_per_address(self):
        body = json.dumps({'date': '2099-01-01', 'time': '10:00', 'duration': 30})
        for _ in range(60):
            self.client.post('/appointments/check-availability/', body, content_type='application/json')
        response = self.client.post('/appointments/check-availability/', body, content_type='application/json')
        self.assertEqual(response.status_code, 429)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ChangePasswordLimitTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('ann', password='old-pass-123', is_staff=True)
        self.client.force_login(self.user)

    def post(self, current):
        return self.client.post(
            '/api/staff/me/password/',
            {'current_password': current, 'new_password': 'a-much-better-one-42'},
            content_type='application/json',
        )

    def test_guessing_the_current_password_is_capped(self):
        for _ in range(5):
            self.assertEqual(self.post('guess').status_code, 400)
        self.assertEqual(self.post('old-pass-123').status_code, 429)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-pass-123'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SignupLimitTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_sign_ups_are_capped_per_address(self):
        for n in range(6):
            response = self.client.post('/signup/', {
                'firstName': 'A', 'lastName': 'B', 'email': f'bot{n}@example.com',
                'password': 'pw-12345678', 'confirmPassword': 'pw-12345678',
            })
        self.assertEqual(response.status_code, 429)
        self.assertEqual(User.objects.filter(email__startswith='bot').count(), 5)
