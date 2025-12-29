from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import datetime, timedelta, date, time
from .models import Appointment
import json


class AppointmentModelTest(TestCase):
    """Test Appointment model"""
    
    def setUp(self):
        self.appointment = Appointment.objects.create(
            email="test@example.com",
            phone="1234567890",
            full_name="Test User",
            title="Test Appointment",
            description="Test description",
            date=date.today() + timedelta(days=1),
            time=time(10, 0),
            estimated_duration=60,
            status="pending"
        )
    
    def test_appointment_creation(self):
        """Test that an appointment can be created"""
        self.assertEqual(self.appointment.email, "test@example.com")
        self.assertEqual(self.appointment.title, "Test Appointment")
        self.assertEqual(self.appointment.status, "pending")
    
    def test_appointment_str(self):
        """Test appointment string representation"""
        self.assertEqual(str(self.appointment), "Test Appointment")
    
    def test_calculate_end_time(self):
        """Test end time calculation"""
        end_time = self.appointment.calculate_end_time()
        expected = (datetime.combine(self.appointment.date, self.appointment.time) + 
                   timedelta(minutes=60)).time()
        self.assertEqual(end_time, expected)
    
    def test_email_unique_constraint(self):
        """Test that email must be unique"""
        with self.assertRaises(Exception):
            Appointment.objects.create(
                email="test@example.com",
                phone="9876543210",
                full_name="Another User",
                title="Another Appointment",
                description="Description",
                date=date.today() + timedelta(days=2),
                time=time(11, 0),
                estimated_duration=30
            )
    
    def test_phone_unique_constraint(self):
        """Test that phone must be unique"""
        with self.assertRaises(Exception):
            Appointment.objects.create(
                email="different@example.com",
                phone="1234567890",
                full_name="Another User",
                title="Another Appointment",
                description="Description",
                date=date.today() + timedelta(days=2),
                time=time(11, 0),
                estimated_duration=30
            )


class AppointmentViewsTest(TestCase):
    """Test appointment views"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='staffpass123',
            is_staff=True
        )
        self.appointment = Appointment.objects.create(
            email="appointment@example.com",
            phone="1234567890",
            full_name="Appointment User",
            title="Test Appointment",
            description="Test description",
            date=date.today() + timedelta(days=1),
            time=time(10, 0),
            estimated_duration=60,
            status="pending"
        )
    
    def test_appointments_list_requires_login(self):
        """Test that appointments list requires login"""
        response = self.client.get(reverse('appointments:list'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_appointments_list_requires_staff(self):
        """Test that appointments list requires staff status"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('appointments:list'))
        self.assertEqual(response.status_code, 403)  # Forbidden
    
    def test_appointments_list_staff_access(self):
        """Test that staff can access appointments list"""
        self.client.login(username='staff', password='staffpass123')
        response = self.client.get(reverse('appointments:list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/list.html')
    
    def test_create_appointment_success(self):
        """Test successful appointment creation"""
        appointment_date = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        response = self.client.post(
            reverse('appointments:create'),
            data=json.dumps({
                "email": "new@example.com",
                "phone": "9876543210",
                "full_name": "New User",
                "title": "New Appointment",
                "description": "New description",
                "date": appointment_date,
                "time": "14:00",
                "estimated_duration": 45,
                "status": "pending"
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)
        self.assertIn('success', data)
        self.assertTrue(Appointment.objects.filter(email="new@example.com").exists())
    
    def test_create_appointment_duplicate_email(self):
        """Test appointment creation with duplicate email"""
        appointment_date = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        response = self.client.post(
            reverse('appointments:create'),
            data=json.dumps({
                "email": "appointment@example.com",
                "phone": "1111111111",
                "full_name": "Duplicate User",
                "title": "Duplicate Appointment",
                "description": "Description",
                "date": appointment_date,
                "time": "15:00",
                "estimated_duration": 30,
                "status": "pending"
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)
    
    def test_create_appointment_missing_fields(self):
        """Test appointment creation with missing required fields"""
        response = self.client.post(
            reverse('appointments:create'),
            data=json.dumps({
                "email": "incomplete@example.com",
                # Missing other required fields
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
    
    def test_get_appointment_success(self):
        """Test successful appointment retrieval"""
        # View now uses POST (fixed)
        response = self.client.post(
            reverse('appointments:get'),
            data=json.dumps({
                "id": self.appointment.id,
                "email": "appointment@example.com",
                "phone": "1234567890"
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertIn('success', data)
        self.assertIn('appointment', data)
    
    def test_get_appointment_not_found(self):
        """Test appointment retrieval with invalid credentials"""
        response = self.client.post(
            reverse('appointments:get'),
            data=json.dumps({
                "id": 99999,
                "email": "wrong@example.com",
                "phone": "0000000000"
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.content)
        self.assertIn('error', data)
    
    def test_get_appointment_missing_fields(self):
        """Test appointment retrieval with missing fields"""
        response = self.client.post(
            reverse('appointments:get'),
            data=json.dumps({
                "id": self.appointment.id,
                # Missing email and phone
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)
    
    def test_check_availability_available(self):
        """Test availability check for available time slot"""
        appointment_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
        response = self.client.post(
            reverse('appointments:check_availability'),
            data=json.dumps({
                "date": appointment_date,
                "time": "16:00",
                "duration": 30
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['available'])
        self.assertIn('message', data)
    
    def test_check_availability_conflict(self):
        """Test availability check for conflicting time slot"""
        # Create an appointment that will conflict
        conflict_date = date.today() + timedelta(days=4)
        Appointment.objects.create(
            email="conflict@example.com",
            phone="2222222222",
            full_name="Conflict User",
            title="Conflict Appointment",
            description="Description",
            date=conflict_date,
            time=time(14, 0),
            estimated_duration=60,
            status="pending"
        )
        
        response = self.client.post(
            reverse('appointments:check_availability'),
            data=json.dumps({
                "date": conflict_date.strftime("%Y-%m-%d"),
                "time": "14:30",  # Overlaps with existing appointment
                "duration": 30
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertFalse(data['available'])
        self.assertIn('conflicting_appointments', data)
    
    def test_check_availability_past_date(self):
        """Test availability check for past date"""
        past_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        response = self.client.post(
            reverse('appointments:check_availability'),
            data=json.dumps({
                "date": past_date,
                "time": "10:00",
                "duration": 30
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertFalse(data['available'])
        self.assertIn('message', data)
    
    def test_check_availability_invalid_duration(self):
        """Test availability check with invalid duration"""
        appointment_date = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
        response = self.client.post(
            reverse('appointments:check_availability'),
            data=json.dumps({
                "date": appointment_date,
                "time": "10:00",
                "duration": -10  # Invalid negative duration
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)
    
    def test_check_availability_invalid_date_format(self):
        """Test availability check with invalid date format"""
        response = self.client.post(
            reverse('appointments:check_availability'),
            data=json.dumps({
                "date": "invalid-date",
                "time": "10:00",
                "duration": 30
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)
    
    def test_admin_manage_appointment_requires_staff(self):
        """Test that admin manage requires staff status"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(
            reverse('appointments:admin_manage', args=[self.appointment.id])
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_admin_manage_appointment_staff_access(self):
        """Test that staff can access admin manage"""
        self.client.login(username='staff', password='staffpass123')
        response = self.client.get(
            reverse('appointments:admin_manage', args=[self.appointment.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'appointments/admin_manage.html')
    
    def test_admin_manage_appointment_update(self):
        """Test updating appointment via admin manage"""
        self.client.login(username='staff', password='staffpass123')
        response = self.client.post(
            reverse('appointments:admin_manage', args=[self.appointment.id]),
            {
                'title': 'Updated Title',
                'description': 'Updated description',
                'status': 'confirmed',
                'date': (date.today() + timedelta(days=2)).strftime("%Y-%m-%d"),
                'time': '11:00',
                'duration': '90'
            }
        )
        self.assertEqual(response.status_code, 200)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.title, 'Updated Title')
        self.assertEqual(self.appointment.status, 'confirmed')
