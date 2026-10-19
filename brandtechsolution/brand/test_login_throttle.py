"""Bot protection on /login/ (brand/login_throttle.py).

What these pin down: a bot is refused before any password is hashed, and no
amount of failed guessing locks a real person out of their own account.
"""
from unittest.mock import patch

from django.contrib.auth.hashers import MD5PasswordHasher
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from brand import login_throttle
from brand.test_turnstile import DISABLED, ENABLED, cloudflare_says

ATTACKER = '198.51.100.7'
OWNER = '203.0.113.20'


# These tests make dozens of sign-in attempts; PBKDF2 at full strength would
# spend minutes hashing.
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LoginThrottleTest(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='amina', email='amina@example.com', password='right-pass-1',
        )

    def attempt(self, password, ip=ATTACKER, identifier='amina@example.com', **extra):
        return self.client.post(
            reverse('login'),
            {'email': identifier, 'password': password, **extra},
            HTTP_CF_CONNECTING_IP=ip,
        )

    def fail(self, times, ip=ATTACKER, identifier='amina@example.com'):
        for _ in range(times):
            self.attempt('wrong', ip=ip, identifier=identifier)

    @DISABLED
    def test_a_wrong_password_hashes_once(self):
        """The old flow called authenticate() twice per wrong password."""
        real = MD5PasswordHasher.encode
        with patch.object(MD5PasswordHasher, 'encode', autospec=True, side_effect=real) as encode:
            self.attempt('wrong')
        self.assertEqual(encode.call_count, 1)

    @DISABLED
    def test_an_address_is_blocked_without_hashing(self):
        self.fail(login_throttle.ADDRESS_BLOCK)
        with patch('brand.views.authenticate') as auth:
            response = self.attempt('right-pass-1')
        self.assertEqual(response.status_code, 429)
        auth.assert_not_called()

    @DISABLED
    def test_a_blocked_address_does_not_lock_out_the_owner(self):
        self.fail(login_throttle.ADDRESS_BLOCK)
        response = self.attempt('right-pass-1', ip=OWNER)
        self.assertEqual(response.status_code, 302)

    @ENABLED
    def test_after_failures_an_address_must_pass_the_challenge(self):
        self.fail(login_throttle.ADDRESS_CHALLENGE)
        with patch('brand.views.authenticate') as auth:
            response = self.attempt('right-pass-1')
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'loginTurnstile', status_code=400)
        auth.assert_not_called()

    @ENABLED
    def test_a_guessed_account_challenges_every_address_but_never_locks(self):
        """Guesses spread over many addresses still trip the account limit,
        and the owner gets in by solving the challenge."""
        for n in range(login_throttle.ACCOUNT_CHALLENGE):
            self.fail(1, ip=f'198.51.100.{n + 10}')

        self.assertEqual(self.attempt('right-pass-1', ip=OWNER).status_code, 400)

        with cloudflare_says({'success': True}):
            response = self.attempt(
                'right-pass-1', ip=OWNER, **{'cf-turnstile-response': 'token'},
            )
        self.assertEqual(response.status_code, 302)

    @ENABLED
    def test_a_successful_sign_in_clears_the_account_count(self):
        for n in range(login_throttle.ACCOUNT_CHALLENGE):
            self.fail(1, ip=f'198.51.100.{n + 10}')
        with cloudflare_says({'success': True}):
            self.attempt('right-pass-1', ip=OWNER, **{'cf-turnstile-response': 'token'})
        self.client.logout()
        self.assertEqual(self.attempt('right-pass-1', ip=OWNER).status_code, 302)

    @ENABLED
    def test_every_way_of_naming_an_account_shares_one_count(self):
        for n, identifier in enumerate(['amina', 'AMINA', 'amina@example.com', 'Amina@Example.com', 'amina']):
            self.fail(1, ip=f'198.51.100.{n + 10}', identifier=identifier)
        self.assertEqual(self.attempt('right-pass-1', ip=OWNER).status_code, 400)

    @ENABLED
    def test_a_site_wide_flood_challenges_everyone(self):
        cache.set(login_throttle.SITE_KEY, login_throttle.SITE_CHALLENGE, 60)
        self.assertEqual(self.attempt('right-pass-1', ip=OWNER).status_code, 400)

    @ENABLED
    def test_a_clean_sign_in_needs_no_challenge(self):
        response = self.client.get(reverse('login'), HTTP_CF_CONNECTING_IP=OWNER)
        self.assertNotContains(response, 'loginTurnstile')
        self.assertEqual(self.attempt('right-pass-1', ip=OWNER).status_code, 302)

    @DISABLED
    def test_next_cannot_redirect_off_site(self):
        response = self.attempt('right-pass-1', ip=OWNER, next='https://evil.example/')
        self.assertRedirects(response, '/', fetch_redirect_response=False)

    @DISABLED
    def test_next_still_redirects_on_site(self):
        response = self.attempt('right-pass-1', ip=OWNER, next='/admin-panel/')
        self.assertRedirects(response, '/admin-panel/', fetch_redirect_response=False)

    def test_admin_login_uses_the_guarded_view(self):
        response = self.client.get('/admin/login/?next=/admin/')
        self.assertTemplateUsed(response, 'brand/login.html')
