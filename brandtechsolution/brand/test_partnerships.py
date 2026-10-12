from django.test import TestCase, Client
from django.urls import reverse
from django.contrib import admin
from brand.models import PartnershipType, PartnerOrganisation


class PartnershipModelTests(TestCase):
    def setUp(self):
        self.partner_type = PartnershipType.objects.create(
            title='Academic Alliances',
            icon='fas fa-university',
            accent='blue',
            tagline='Connecting students with curriculum.',
            description='Detailed partnership description.',
            benefits='Free cloud hosting\nDirect mentorship\nAPI access',
            requirements='Accredited institution\nFaculty liaison',
            status=PartnershipType.STATUS_OPEN,
            order=1
        )
        self.partner_org = PartnerOrganisation.objects.create(
            name='African Education Lab',
            website='https://example.org',
            sector='Education',
            description='Advancing open educational tech.',
            featured=True,
            order=1
        )

    def test_partnership_type_methods(self):
        self.assertEqual(len(self.partner_type.benefits_list()), 3)
        self.assertEqual(len(self.partner_type.requirements_list()), 2)
        self.assertIn('Academic Alliances', str(self.partner_type))

    def test_partner_organisation_methods(self):
        self.assertEqual(str(self.partner_org), 'African Education Lab')
        self.assertEqual(self.partner_org.get_logo(), '')


class PartnershipViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.open_track = PartnershipType.objects.create(
            title='Technology Integrator Track',
            icon='fas fa-laptop-code',
            tagline='Co-building cloud APIs',
            description='Open track for cloud partners',
            benefits='Shared APIs',
            requirements='E.164 phone support',
            status=PartnershipType.STATUS_OPEN,
            order=1
        )
        self.closed_track = PartnershipType.objects.create(
            title='Legacy Pilot Track',
            icon='fas fa-archive',
            tagline='Pilot completed',
            description='Closed track',
            status=PartnershipType.STATUS_CLOSED,
            order=99
        )
        self.featured_org = PartnerOrganisation.objects.create(
            name='Kenya Open Tech',
            featured=True,
            order=1
        )

    def test_partnerships_page_renders_successfully(self):
        url = reverse('partnerships')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/partnerships.html')
        self.assertContains(response, 'Technology Integrator Track')
        self.assertContains(response, 'Corporate Social Responsibility')
        self.assertContains(response, 'EduShare Africa')
        self.assertContains(response, 'Kenya Open Tech')

    def test_admin_models_registered(self):
        self.assertIn(PartnershipType, admin.site._registry)
        self.assertIn(PartnerOrganisation, admin.site._registry)
