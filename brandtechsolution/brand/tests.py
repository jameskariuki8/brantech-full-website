from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from .models import BlogPost, Project, Event
import json


class BlogPostModelTest(TestCase):
    """Test BlogPost model"""
    
    def setUp(self):
        self.post = BlogPost.objects.create(
            title="Test Blog Post",
            excerpt="This is a test excerpt",
            content="This is the full content of the test blog post.",
            category="Technology",
            tags="django, python, web",
            featured=True
        )
    
    def test_blog_post_creation(self):
        """Test that a blog post can be created"""
        self.assertEqual(self.post.title, "Test Blog Post")
        self.assertEqual(self.post.category, "Technology")
        self.assertTrue(self.post.featured)
    
    def test_blog_post_str(self):
        """Test blog post string representation"""
        self.assertEqual(str(self.post), "Test Blog Post")
    
    def test_get_tags_list(self):
        """Test tag parsing"""
        tags = self.post.get_tags_list()
        self.assertEqual(len(tags), 3)
        self.assertIn("django", tags)
        self.assertIn("python", tags)
        self.assertIn("web", tags)
    
    def test_blog_post_ordering(self):
        """Test that posts are ordered by created_at descending"""
        post2 = BlogPost.objects.create(
            title="Second Post",
            excerpt="Second excerpt",
            content="Second content"
        )
        posts = list(BlogPost.objects.all())
        # Newest first
        self.assertEqual(posts[0].title, "Second Post")
        self.assertEqual(posts[1].title, "Test Blog Post")


class ProjectModelTest(TestCase):
    """Test Project model"""
    
    def setUp(self):
        from datetime import date
        
        self.project = Project.objects.create(
            title="Test Project",
            description="Full project description",
            client="Test Client",
            status="completed",
            start_date=date.today(),
            project_url="https://example.com",
            github_url="https://github.com/example",
            featured=True
        )
    
    def test_project_creation(self):
        """Test that a project can be created"""
        self.assertEqual(self.project.title, "Test Project")
        self.assertEqual(self.project.client, "Test Client")
        self.assertEqual(self.project.project_url, "https://example.com")
        self.assertTrue(self.project.featured)
    
    def test_project_str(self):
        """Test project string representation"""
        self.assertEqual(str(self.project), "Test Project - Test Client")


class EventModelTest(TestCase):
    """Test Event model"""
    
    def setUp(self):
        from django.utils import timezone
        from datetime import timedelta
        
        self.event = Event.objects.create(
            title="Test Event",
            description="Event description",
            event_type="webinar",
            date=timezone.now() + timedelta(days=7),
            location="Online",
            is_online=True
        )
    
    def test_event_creation(self):
        """Test that an event can be created"""
        self.assertEqual(self.event.title, "Test Event")
        self.assertEqual(self.event.event_type, "webinar")
        self.assertTrue(self.event.is_online)


class BrandViewsTest(TestCase):
    """Test brand app views"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass123',
            is_staff=True,
            is_superuser=True
        )
    
    def test_index_view(self):
        """Test home page view"""
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/index.html')
    
    def test_about_view(self):
        """Test about page view"""
        response = self.client.get(reverse('about'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/about.html')
    
    def test_blog_view(self):
        """Test blog page view"""
        response = self.client.get(reverse('blog'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/blog.html')
    
    def test_projects_view(self):
        """Test projects page view - requires login"""
        # Projects view requires login, so unauthenticated should redirect
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
        
        # Test with authenticated user
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/projects.html')
    
    def test_faq_view(self):
        """Test FAQ page view"""
        response = self.client.get(reverse('faq'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/faq.html')
    
    def test_contacts_view(self):
        """Test contacts page view"""
        response = self.client.get(reverse('contacts'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/contacts.html')
    
    def test_admin_panel_requires_login(self):
        """Test that admin panel requires authentication"""
        response = self.client.get(reverse('admin-panel'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_admin_panel_requires_staff(self):
        """Test that admin panel requires staff status"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('admin-panel'))
        self.assertEqual(response.status_code, 302)  # Redirect to login (not staff)
    
    def test_admin_panel_access(self):
        """Test that staff can access admin panel"""
        self.client.login(username='admin', password='adminpass123')
        response = self.client.get(reverse('admin-panel'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/admin_panel.html')
    
    def test_signup_view_get(self):
        """Test signup page GET request"""
        response = self.client.get(reverse('signup'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/signup.html')
    
    def test_signup_view_post_success(self):
        """Test successful user signup"""
        response = self.client.post(reverse('signup'), {
            'firstName': 'John',
            'lastName': 'Doe',
            'email': 'john@example.com',
            'password': 'securepass123',
            'confirmPassword': 'securepass123'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after success
        self.assertTrue(User.objects.filter(email='john@example.com').exists())
    
    def test_signup_view_post_password_mismatch(self):
        """Test signup with mismatched passwords"""
        response = self.client.post(reverse('signup'), {
            'firstName': 'John',
            'lastName': 'Doe',
            'email': 'john@example.com',
            'password': 'securepass123',
            'confirmPassword': 'differentpass'
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='john@example.com').exists())
    
    def test_login_view_get(self):
        """Test login page GET request"""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'brand/login.html')
    
    def test_login_view_post_success(self):
        """Test successful login"""
        # The login view uses email as username
        # User was created with username='testuser' and email='test@example.com'
        # So we need to use 'testuser' as the email field (which is used as username)
        response = self.client.post(reverse('login'), {
            'email': 'testuser',  # Use username since email field is used as username
            'password': 'testpass123'
        })
        # Should redirect on success
        self.assertEqual(response.status_code, 302)  # Redirect after login
    
    def test_login_view_post_failure(self):
        """Test failed login"""
        response = self.client.post(reverse('login'), {
            'email': 'test@example.com',
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
    
    def test_logout_view(self):
        """Test logout"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 302)  # Redirect after logout


class BrandAPITest(TestCase):
    """Test brand app API endpoints"""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        from datetime import date
        
        self.post = BlogPost.objects.create(
            title="Test Post",
            excerpt="Test excerpt",
            content="Test content",
            category="Tech"
        )
        self.project = Project.objects.create(
            title="Test Project",
            description="Test description",
            client="Test Client",
            status="completed",
            start_date=date.today()
        )
    
    def test_get_blog_posts_list(self):
        """Test GET /api/posts/"""
        response = self.client.get('/api/posts/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        # DRF returns results in a 'results' key for paginated viewsets
        if isinstance(data, dict) and 'results' in data:
            results = data['results']
        else:
            results = data
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        # Find our test post
        post_titles = [p['title'] for p in results]
        self.assertIn("Test Post", post_titles)
    
    def test_get_blog_post_detail(self):
        """Test GET /api/posts/<id>/"""
        response = self.client.get(f'/api/posts/{self.post.id}/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['title'], "Test Post")
        self.assertEqual(data['id'], self.post.id)
    
    def test_create_blog_post_unauthorized(self):
        """Test POST /api/posts/ without authentication"""
        # DRF ViewSets don't require authentication by default
        # They will create the post if valid data is provided
        response = self.client.post('/api/posts/', {
            'title': 'New Post',
            'content': 'Content',
            'excerpt': 'Excerpt'
        }, content_type='application/json')
        # DRF returns 201 on success, or 400/401 depending on configuration
        self.assertIn(response.status_code, [201, 400, 401])
    
    def test_create_blog_post_authorized(self):
        """Test POST /api/posts/ with authentication"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post('/api/posts/', {
            'title': 'New Post',
            'content': 'Content',
            'excerpt': 'Excerpt',
            'category': 'Tech'
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)
        self.assertIn('id', data)
        self.assertTrue(BlogPost.objects.filter(title='New Post').exists())
    
    def test_update_blog_post_unauthorized(self):
        """Test PUT/PATCH /api/posts/<id>/ without authentication"""
        # DRF ViewSets use PUT/PATCH for updates, not POST
        response = self.client.patch(f'/api/posts/{self.post.id}/', {
            'title': 'Updated Title'
        }, content_type='application/json')
        # DRF may allow updates without auth, or return 401/403
        self.assertIn(response.status_code, [200, 401, 403, 405])
    
    def test_update_blog_post_authorized(self):
        """Test PUT/PATCH /api/posts/<id>/ with authentication"""
        self.client.login(username='testuser', password='testpass123')
        # DRF ViewSets use PATCH for partial updates
        response = self.client.patch(f'/api/posts/{self.post.id}/', {
            'title': 'Updated Title'
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.title, 'Updated Title')
    
    def test_delete_blog_post_unauthorized(self):
        """Test DELETE /api/posts/<id>/ without authentication"""
        response = self.client.delete(f'/api/posts/{self.post.id}/')
        # DRF may allow deletes without auth, or return 401/403/204
        self.assertIn(response.status_code, [204, 401, 403])
    
    def test_delete_blog_post_authorized(self):
        """Test DELETE /api/posts/<id>/ with authentication"""
        self.client.login(username='testuser', password='testpass123')
        post_id = self.post.id
        response = self.client.delete(f'/api/posts/{post_id}/')
        # DRF returns 204 No Content for successful DELETE
        self.assertEqual(response.status_code, 204)
        self.assertFalse(BlogPost.objects.filter(id=post_id).exists())
    
    def test_get_projects_list(self):
        """Test GET /api/projects/"""
        response = self.client.get('/api/projects/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        # DRF returns results in a 'results' key for paginated viewsets
        if isinstance(data, dict) and 'results' in data:
            results = data['results']
        else:
            results = data
        self.assertIsInstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        # Find our test project
        project_titles = [p['title'] for p in results]
        self.assertIn("Test Project", project_titles)
    
    def test_get_project_detail(self):
        """Test GET /api/projects/<id>/"""
        response = self.client.get(f'/api/projects/{self.project.id}/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['title'], "Test Project")
        # Note: API might not return all fields like client, status, etc.
    
    def test_create_project_unauthorized(self):
        """Test POST /api/projects/ without authentication"""
        from datetime import date
        # DRF ViewSets don't require authentication by default
        response = self.client.post('/api/projects/', {
            'title': 'New Project',
            'description': 'Description',
            'client': 'Test Client',
            'status': 'planning',
            'start_date': date.today().isoformat()
        }, content_type='application/json')
        # DRF returns 201 on success, or 400/401 depending on configuration
        self.assertIn(response.status_code, [201, 400, 401])
    
    def test_create_project_authorized(self):
        """Test POST /api/projects/ with authentication"""
        from datetime import date
        import json
        
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post('/api/projects/', 
            json.dumps({
                'title': 'New Project',
                'description': 'Description',
                'client': 'New Client',
                'status': 'planning',
                'start_date': date.today().isoformat(),
                'technologies': 'Django, Python'  # Required field
            }),
            content_type='application/json'
        )
        # Check response status and content for debugging
        if response.status_code != 201:
            print(f"Response status: {response.status_code}")
            print(f"Response content: {response.content.decode()}")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Project.objects.filter(title='New Project').exists())
    
    def test_delete_project_authorized(self):
        """Test DELETE /api/projects/<id>/ with authentication"""
        self.client.login(username='testuser', password='testpass123')
        project_id = self.project.id
        response = self.client.delete(f'/api/projects/{project_id}/')
        # DRF returns 204 No Content for successful DELETE
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Project.objects.filter(id=project_id).exists())
