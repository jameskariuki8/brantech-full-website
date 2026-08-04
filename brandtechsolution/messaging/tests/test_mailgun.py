"""The Mailgun backend, exercised through Django's mail API.

Nothing in the app calls Mailgun directly -- send_mail(), the outbox and every
other caller go through django.core.mail, which is the point of implementing
this as a backend. So these tests drive it the same way.
"""
from unittest.mock import MagicMock, patch

from django.core import mail
from django.core.mail import EmailMultiAlternatives, send_mail
from django.test import SimpleTestCase, override_settings

from brandtechsolution import mailgun

MAILGUN_SETTINGS = dict(
    EMAIL_BACKEND='brandtechsolution.mailgun.MailgunEmailBackend',
    MAILGUN_API_KEY='key-test',
    MAILGUN_DOMAIN='mg.example.com',
    MAILGUN_BASE_URL='https://api.mailgun.net/v3',
    DEFAULT_FROM_EMAIL='noreply@mg.example.com',
)


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    return response


@override_settings(**MAILGUN_SETTINGS)
class MessagesUrlTest(SimpleTestCase):
    def test_domain_is_appended_to_the_api_root(self):
        self.assertEqual(
            mailgun.messages_url(),
            'https://api.mailgun.net/v3/mg.example.com/messages',
        )

    @override_settings(MAILGUN_BASE_URL='https://api.eu.mailgun.net/v3')
    def test_the_eu_region_host_is_honoured(self):
        self.assertEqual(
            mailgun.messages_url(),
            'https://api.eu.mailgun.net/v3/mg.example.com/messages',
        )

    @override_settings(MAILGUN_BASE_URL='https://api.mailgun.net/v3/mg.example.com/')
    def test_a_base_url_that_already_names_the_domain_is_not_doubled(self):
        """The obvious misconfiguration, and it would only show up as a 404."""
        self.assertEqual(
            mailgun.messages_url(),
            'https://api.mailgun.net/v3/mg.example.com/messages',
        )


@override_settings(**MAILGUN_SETTINGS)
class SendTest(SimpleTestCase):
    def test_a_plain_message_posts_the_expected_fields(self):
        with patch('requests.Session.post', return_value=_ok_response()) as post:
            sent = send_mail(
                'Subject here', 'Body here', None, ['reader@example.com']
            )

        self.assertEqual(sent, 1)
        url, data = post.call_args[0][0], post.call_args[1]['data']
        self.assertEqual(url, 'https://api.mailgun.net/v3/mg.example.com/messages')
        self.assertEqual(data['from'], 'noreply@mg.example.com')
        self.assertEqual(data['to'], ['reader@example.com'])
        self.assertEqual(data['subject'], 'Subject here')
        self.assertEqual(data['text'], 'Body here')

    def test_an_html_alternative_is_sent_alongside_the_text_part(self):
        msg = EmailMultiAlternatives(
            'Subject', 'text fallback', 'from@example.com', ['to@example.com']
        )
        msg.attach_alternative('<p>rich</p>', 'text/html')

        with patch('requests.Session.post', return_value=_ok_response()) as post:
            msg.send()

        data = post.call_args[1]['data']
        self.assertEqual(data['text'], 'text fallback')
        self.assertEqual(data['html'], '<p>rich</p>')

    def test_unsubscribe_headers_survive_as_mailgun_h_parameters(self):
        """Gmail and Yahoo require these from bulk senders.

        The outbox sets them on every campaign message. Dropping them would
        cost deliverability silently -- no error, just more spam folder.
        """
        msg = EmailMultiAlternatives(
            'Subject', 'body', 'from@example.com', ['to@example.com']
        )
        msg.extra_headers['List-Unsubscribe'] = '<https://example.com/u/abc>'
        msg.extra_headers['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'

        with patch('requests.Session.post', return_value=_ok_response()) as post:
            msg.send()

        data = post.call_args[1]['data']
        self.assertEqual(data['h:List-Unsubscribe'], '<https://example.com/u/abc>')
        self.assertEqual(
            data['h:List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click'
        )

    def test_cc_bcc_and_reply_to_are_forwarded(self):
        msg = EmailMultiAlternatives(
            'Subject', 'body', 'from@example.com', ['to@example.com'],
            cc=['cc@example.com'], bcc=['bcc@example.com'],
            reply_to=['reply@example.com'],
        )

        with patch('requests.Session.post', return_value=_ok_response()) as post:
            msg.send()

        data = post.call_args[1]['data']
        self.assertEqual(data['cc'], ['cc@example.com'])
        self.assertEqual(data['bcc'], ['bcc@example.com'])
        self.assertEqual(data['h:Reply-To'], 'reply@example.com')


@override_settings(**MAILGUN_SETTINGS)
class ConnectionReuseTest(SimpleTestCase):
    def test_a_caller_held_connection_pools_one_session_across_the_batch(self):
        """The outbox opens once and sends 50 -- that must be one TLS session.

        A backend that built a fresh requests.post() per message would throw
        away the connection reuse the outbox is written around.
        """
        connection = mail.get_connection()
        connection.open()
        session = connection.session

        messages = [
            EmailMultiAlternatives(
                'Subject', 'body', 'from@example.com', [f'to{i}@example.com'],
                connection=connection,
            )
            for i in range(3)
        ]

        with patch.object(session, 'post', return_value=_ok_response()) as post:
            sent = connection.send_messages(messages)

        self.assertEqual(sent, 3)
        self.assertEqual(post.call_count, 3)
        # Still open: send_messages must not close a session it did not create.
        self.assertIs(connection.session, session)
        connection.close()
        self.assertIsNone(connection.session)


@override_settings(**MAILGUN_SETTINGS)
class FailureTest(SimpleTestCase):
    def test_a_rejected_message_raises_with_mailgun_s_reason(self):
        """The outbox records this against the recipient and shows it in the
        panel, so the reason has to survive rather than become 'failed'."""
        response = MagicMock()
        response.status_code = 400
        response.json.return_value = {'message': 'to parameter is not a valid address'}

        with patch('requests.Session.post', return_value=response):
            with self.assertRaises(RuntimeError) as ctx:
                send_mail('S', 'B', None, ['bad-address'])

        self.assertIn('to parameter is not a valid address', str(ctx.exception))

    def test_fail_silently_reports_nothing_sent_rather_than_raising(self):
        response = MagicMock()
        response.status_code = 500
        response.json.side_effect = ValueError
        response.text = 'upstream exploded'

        with patch('requests.Session.post', return_value=response):
            sent = send_mail('S', 'B', None, ['to@example.com'], fail_silently=True)

        self.assertEqual(sent, 0)

    @override_settings(MAILGUN_API_KEY='', MAILGUN_DOMAIN='')
    def test_an_unconfigured_backend_refuses_instead_of_claiming_success(self):
        """Returning 0 quietly would let the outbox mark recipients sent."""
        with self.assertRaises(RuntimeError):
            send_mail('S', 'B', None, ['to@example.com'])


@override_settings(**MAILGUN_SETTINGS)
class BaseUrlGuardTest(SimpleTestCase):
    """A base URL without a version segment kills every send at once.

    Mailgun answers an unversioned path with a plain-text "404 page not
    found", which reads as a problem with the message rather than the URL.
    """

    @override_settings(MAILGUN_BASE_URL="https://api.mailgun.net")
    def test_a_missing_version_segment_is_a_startup_error(self):
        errors = mailgun.check_mailgun_base_url(None)
        self.assertEqual([e.id for e in errors], ["mailgun.E002"])

    def test_the_versioned_api_root_passes(self):
        self.assertEqual(mailgun.check_mailgun_base_url(None), [])

    @override_settings(MAILGUN_BASE_URL="https://api.eu.mailgun.net/v3")
    def test_the_eu_api_root_passes(self):
        self.assertEqual(mailgun.check_mailgun_base_url(None), [])

    @override_settings(MAILGUN_BASE_URL="https://api.mailgun.net/v3/mg.example.com")
    def test_a_base_url_ending_in_the_domain_passes(self):
        """messages_url() tolerates this form, so the check must too."""
        self.assertEqual(mailgun.check_mailgun_base_url(None), [])

    @override_settings(MAILGUN_API_KEY="", MAILGUN_DOMAIN="")
    def test_an_unconfigured_backend_is_not_flagged(self):
        self.assertEqual(mailgun.check_mailgun_base_url(None), [])

    def test_a_rejection_names_the_url_it_posted_to(self):
        """A 404 is unactionable without knowing which URL produced it."""
        response = MagicMock()
        response.status_code = 404
        response.json.side_effect = ValueError
        response.text = "404 page not found"

        with patch("requests.Session.post", return_value=response):
            with self.assertRaises(RuntimeError) as ctx:
                send_mail("S", "B", None, ["to@example.com"])

        self.assertIn(
            "https://api.mailgun.net/v3/mg.example.com/messages", str(ctx.exception)
        )


class ProductionGuardTest(SimpleTestCase):
    """The console backend prints mail to stdout and reports it as sent."""

    @override_settings(DEBUG=False, EMAIL_BACKEND=mailgun.CONSOLE_BACKEND)
    def test_console_backend_with_debug_off_is_a_startup_error(self):
        errors = mailgun.check_email_configured(None)
        self.assertEqual([e.id for e in errors], ['mailgun.E001'])

    @override_settings(DEBUG=True, EMAIL_BACKEND=mailgun.CONSOLE_BACKEND)
    def test_console_backend_is_fine_in_development(self):
        self.assertEqual(mailgun.check_email_configured(None), [])

    @override_settings(**MAILGUN_SETTINGS)
    def test_a_configured_backend_passes(self):
        with override_settings(DEBUG=False):
            self.assertEqual(mailgun.check_email_configured(None), [])
