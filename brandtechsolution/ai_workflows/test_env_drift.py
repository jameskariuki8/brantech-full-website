"""The two .env files, and noticing when they disagree.

This exists because the failure it catches is invisible by construction: a key
rotated in the repo-root .env while a local `manage.py` kept reading a stale
one from `brandtechsolution/.env`. Nothing raised, nothing logged, and every
symptom pointed at the provider instead of at the file.
"""
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from brandtechsolution.config import (
    SHARED_CREDENTIALS, credential_drift, fingerprint, read_env_file,
)


class _Settings:
    """Stands in for the loaded config, with only the fields drift reads."""

    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)

    def __getattr__(self, name):
        return ""


class FingerprintTests(SimpleTestCase):

    def test_a_fingerprint_does_not_contain_the_secret(self):
        secret = "AIzaSyExampleKeyMaterialThatMustNotLeak"
        digest = fingerprint(secret)
        self.assertEqual(len(digest), 8)
        self.assertNotIn(digest, secret)
        self.assertNotIn(secret[:8], digest)

    def test_the_same_secret_always_fingerprints_the_same(self):
        self.assertEqual(fingerprint("abc"), fingerprint("abc"))
        self.assertNotEqual(fingerprint("abc"), fingerprint("abd"))

    def test_an_absent_secret_is_named_rather_than_hashed(self):
        self.assertEqual(fingerprint(""), "unset")


class ReadEnvFileTests(SimpleTestCase):

    def _write(self, body):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        path = Path(self._dir.name) / ".env"
        path.write_text(body, encoding="utf-8")
        return path

    def test_it_reads_pairs_and_ignores_comments_and_blanks(self):
        values = read_env_file(self._write(
            "# a comment\n\nGOOGLE_API_KEY=abc\n  OPENAI_API_KEY = def \n"
        ))
        self.assertEqual(values["GOOGLE_API_KEY"], "abc")
        self.assertEqual(values["OPENAI_API_KEY"], "def")

    def test_it_strips_the_quotes_a_dotenv_file_may_carry(self):
        values = read_env_file(self._write('GOOGLE_API_KEY="abc"\nOTHER=\'def\'\n'))
        self.assertEqual(values["GOOGLE_API_KEY"], "abc")
        self.assertEqual(values["OTHER"], "def")

    def test_a_missing_file_is_empty_rather_than_an_error(self):
        # This runs during settings import. A malformed or absent file must
        # degrade to "cannot tell" rather than stopping Django from starting.
        self.assertEqual(read_env_file(Path("/nonexistent/.env")), {})

    def test_a_line_without_an_equals_sign_is_skipped(self):
        self.assertEqual(read_env_file(self._write("junk\nA=1\n")), {"A": "1"})


class CredentialDriftTests(SimpleTestCase):

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name) / ".env"

    def test_a_key_that_differs_is_reported_with_both_fingerprints(self):
        self.root.write_text("GOOGLE_API_KEY=the-new-paid-key\n")
        drift = credential_drift(
            settings=_Settings(google_api_key="the-old-stale-key"),
            root_env_file=self.root,
        )
        self.assertEqual(len(drift), 1)
        key, live, stated = drift[0]
        self.assertEqual(key, "GOOGLE_API_KEY")
        self.assertEqual(live, fingerprint("the-old-stale-key"))
        self.assertEqual(stated, fingerprint("the-new-paid-key"))

    def test_a_key_that_agrees_is_silent(self):
        self.root.write_text("GOOGLE_API_KEY=same\n")
        self.assertEqual(
            credential_drift(settings=_Settings(google_api_key="same"),
                             root_env_file=self.root),
            [],
        )

    def test_no_root_file_means_nothing_to_compare(self):
        # The normal case inside a container built from that file.
        self.assertEqual(
            credential_drift(settings=_Settings(google_api_key="x"),
                             root_env_file=Path("/nonexistent/.env")),
            [],
        )

    def test_a_key_present_in_only_one_place_is_a_gap_not_a_conflict(self):
        # Reporting these would fire permanently on every deployment that
        # simply has not configured a second provider.
        self.root.write_text("OPENAI_API_KEY=\nANTHROPIC_API_KEY=set-here\n")
        self.assertEqual(
            credential_drift(
                settings=_Settings(openai_api_key="set-locally", anthropic_api_key=""),
                root_env_file=self.root,
            ),
            [],
        )

    def test_environment_specific_settings_are_not_compared(self):
        # These two files describe two environments and are *supposed* to
        # disagree here. A warning that fires on an expected difference is one
        # people learn to scroll past.
        self.root.write_text(
            "DATABASE_USER=docker\nDEBUG=False\nALLOWED_HOSTS=teklora.co.ke\n"
        )
        drift = credential_drift(
            settings=_Settings(database_user="local", debug=True),
            root_env_file=self.root,
        )
        self.assertEqual(drift, [])
        for name in ("DATABASE_USER", "DEBUG", "ALLOWED_HOSTS"):
            self.assertNotIn(name, SHARED_CREDENTIALS)

    def test_every_drift_report_is_fingerprints_only(self):
        secret_live, secret_file = "live-secret-value", "file-secret-value"
        self.root.write_text(f"GOOGLE_API_KEY={secret_file}\n")
        drift = credential_drift(
            settings=_Settings(google_api_key=secret_live), root_env_file=self.root,
        )
        rendered = repr(drift)
        self.assertNotIn(secret_live, rendered)
        self.assertNotIn(secret_file, rendered)


class DriftCheckTests(SimpleTestCase):
    """The system check that carries the finding to a terminal."""

    def test_it_warns_when_there_is_drift(self):
        from unittest.mock import patch

        from ai_workflows.checks import check_env_file_drift

        with patch("brandtechsolution.config.credential_drift",
                   return_value=[("GOOGLE_API_KEY", "aaaaaaaa", "bbbbbbbb")]):
            messages = check_env_file_drift(None)

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].id, "ai_workflows.W002")
        self.assertIn("GOOGLE_API_KEY", messages[0].msg)
        self.assertIn("aaaaaaaa", messages[0].msg)

    def test_it_is_silent_when_the_files_agree(self):
        from unittest.mock import patch

        from ai_workflows.checks import check_env_file_drift

        with patch("brandtechsolution.config.credential_drift", return_value=[]):
            self.assertEqual(check_env_file_drift(None), [])

    def test_a_broken_check_does_not_stop_startup(self):
        from unittest.mock import patch

        from ai_workflows.checks import check_env_file_drift

        with patch("brandtechsolution.config.credential_drift",
                   side_effect=OSError("disk is gone")):
            self.assertEqual(check_env_file_drift(None), [])
