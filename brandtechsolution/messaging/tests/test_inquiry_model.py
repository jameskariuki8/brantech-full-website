from django.test import TestCase
from messaging.models import Inquiry


class InquiryModelTests(TestCase):
    def test_new_inquiry_defaults_to_new_status(self):
        inq = Inquiry.objects.create(
            name="Ada Lovelace", email="ada@example.com", message="Hello"
        )
        self.assertEqual(inq.status, "new")
        self.assertEqual(inq.phone, "")

    def test_ordering_is_newest_first(self):
        first = Inquiry.objects.create(name="A", email="a@x.com", message="m")
        second = Inquiry.objects.create(name="B", email="b@x.com", message="m")
        self.assertEqual(list(Inquiry.objects.all()), [second, first])
