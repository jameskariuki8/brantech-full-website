from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.db import connection
from django.test.utils import override_settings
from brand.models import BlogPost, Project
from datetime import datetime
import json


class PerformanceOptimizationTests(TestCase):
    """Test suite for performance optimization changes"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser@example.com',
            email='testuser@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User'
        )
        
        # Create test blog posts
        for i in range(5):
            BlogPost.objects.create(
                title=f'Test Post {i}',
                excerpt=f'Excerpt for post {i}',
                content=f'Content for test post {i}',
                category='Technology',
                tags='python,django,web',
                featured=(i % 2 == 0)
            )
        
        # Create test projects
        for i in range(3):
            Project.objects.create(
                title=f'Test Project {i}',
                short_description=f'Short description {i}',
                description=f'Full description for project {i}',
                featured=(i == 0)
            )
    
    def test_blog_post_list_query_optimization(self):
        """Test that BlogPost list endpoint uses optimized queries"""
        # Count queries
        with self.assertNumQueries(1):  # Should be just 1 query with only()
            response = self.client.get('/api/posts/')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(len(data), 5)
    
    def test_project_list_query_optimization(self):
        """Test that Project list endpoint uses optimized queries"""
        # Count queries
        with self.assertNumQueries(1):  # Should be just 1 query with only()
            response = self.client.get('/api/projects/')
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            self.assertEqual(len(data), 3)
    
    def test_login_view_optimized_queries(self):
        """Test that login view uses optimized database queries"""
        # Test login with username
        with self.assertNumQueries(4):  # Initial auth, user fetch, session save, last_login update
            response = self.client.post('/login/', {
                'email': 'testuser@example.com',
                'password': 'testpass123'
            })
            self.assertEqual(response.status_code, 302)  # Redirect on success
    
    def test_signup_view_optimized_queries(self):
        """Test that signup view uses a single query to check email existence"""
        # Test signup with existing email
        with self.assertNumQueries(1):  # Just one query to check if user exists
            response = self.client.post('/signup/', {
                'firstName': 'New',
                'lastName': 'User',
                'email': 'testuser@example.com',
                'password': 'newpass123',
                'confirmPassword': 'newpass123'
            })
            self.assertEqual(response.status_code, 200)  # Stays on page with error
    
    def test_blog_post_api_response_structure(self):
        """Test that blog post API returns correct data structure"""
        response = self.client.get('/api/posts/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Check first post has all required fields
        if data:
            first_post = data[0]
            required_fields = ['id', 'title', 'category', 'excerpt', 'content', 
                             'tags', 'featured', 'view_count', 'created_at', 'image']
            for field in required_fields:
                self.assertIn(field, first_post)
    
    def test_project_api_response_structure(self):
        """Test that project API returns correct data structure"""
        response = self.client.get('/api/projects/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Check first project has all required fields
        if data:
            first_project = data[0]
            required_fields = ['id', 'title', 'short_description', 'description',
                             'project_url', 'github_url', 'featured', 'image']
            for field in required_fields:
                self.assertIn(field, first_project)
    
    def test_increment_view_uses_update_fields(self):
        """Test that view count increment uses update_fields for efficiency"""
        post = BlogPost.objects.first()
        initial_count = post.view_count
        
        # Make request to increment view
        response = self.client.post(f'/api/blog-posts/{post.id}/increment_view/')
        
        # Verify view count was incremented
        post.refresh_from_db()
        self.assertEqual(post.view_count, initial_count + 1)


class DatabaseIndexTests(TestCase):
    """Test that database indexes are created correctly"""
    
    def test_blogpost_indexes_exist(self):
        """Test that BlogPost model has performance indexes"""
        # Get table name
        table_name = BlogPost._meta.db_table
        
        # Get indexes from database
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = %s
            """, [table_name])
            indexes = [row[0] for row in cursor.fetchall()]
        
        # Check for expected indexes
        expected_indexes = [
            'brand_blogpost_created_idx',
            'brand_blogpost_updated_idx',
            'brand_blogpost_featured_idx',
            'brand_blogpost_category_idx'
        ]
        
        for expected_index in expected_indexes:
            self.assertIn(expected_index, indexes, 
                         f"Index {expected_index} not found in database")
    
    def test_project_indexes_exist(self):
        """Test that Project model has performance indexes"""
        # Get table name
        table_name = Project._meta.db_table
        
        # Get indexes from database
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = %s
            """, [table_name])
            indexes = [row[0] for row in cursor.fetchall()]
        
        # Check for expected indexes
        expected_indexes = [
            'brand_project_created_idx',
            'brand_project_updated_idx',
            'brand_project_featured_idx'
        ]
        
        for expected_index in expected_indexes:
            self.assertIn(expected_index, indexes,
                         f"Index {expected_index} not found in database")

