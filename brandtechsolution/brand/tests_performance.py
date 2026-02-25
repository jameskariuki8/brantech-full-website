"""
Tests for performance optimizations.
"""
from django.test import TestCase, RequestFactory
from django.core.paginator import Paginator
from brand.models import BlogPost, Project
from brand.api_views import paginate_queryset
from brand.performance_utils import cache_query_result
from django.core.cache import cache
import json


class PaginationTests(TestCase):
    """Tests for API pagination functionality."""
    
    def setUp(self):
        self.factory = RequestFactory()
        # Create test blog posts
        for i in range(25):
            BlogPost.objects.create(
                title=f'Test Post {i}',
                excerpt=f'Excerpt {i}',
                content=f'Content {i}',
                category='Test'
            )
    
    def test_paginate_queryset_default_page(self):
        """Test pagination returns first page by default."""
        queryset = BlogPost.objects.all()
        request = self.factory.get('/api/posts/')
        
        paginated_items, pagination_meta = paginate_queryset(queryset, request, page_size=10)
        
        self.assertEqual(len(list(paginated_items)), 10)
        self.assertEqual(pagination_meta['page'], 1)
        self.assertEqual(pagination_meta['total_pages'], 3)
        self.assertEqual(pagination_meta['total_items'], 25)
        self.assertTrue(pagination_meta['has_next'])
        self.assertFalse(pagination_meta['has_previous'])
    
    def test_paginate_queryset_specific_page(self):
        """Test pagination with specific page number."""
        queryset = BlogPost.objects.all()
        request = self.factory.get('/api/posts/?page=2')
        
        paginated_items, pagination_meta = paginate_queryset(queryset, request, page_size=10)
        
        self.assertEqual(pagination_meta['page'], 2)
        self.assertTrue(pagination_meta['has_next'])
        self.assertTrue(pagination_meta['has_previous'])
    
    def test_paginate_queryset_last_page(self):
        """Test pagination on last page."""
        queryset = BlogPost.objects.all()
        request = self.factory.get('/api/posts/?page=3')
        
        paginated_items, pagination_meta = paginate_queryset(queryset, request, page_size=10)
        
        self.assertEqual(len(list(paginated_items)), 5)  # Last page has 5 items
        self.assertEqual(pagination_meta['page'], 3)
        self.assertFalse(pagination_meta['has_next'])
        self.assertTrue(pagination_meta['has_previous'])
    
    def test_paginate_queryset_invalid_page(self):
        """Test pagination with invalid page number."""
        queryset = BlogPost.objects.all()
        request = self.factory.get('/api/posts/?page=999')
        
        # Should return last page
        paginated_items, pagination_meta = paginate_queryset(queryset, request, page_size=10)
        
        self.assertEqual(pagination_meta['page'], 3)  # Last page
    
    def test_paginate_queryset_custom_page_size(self):
        """Test pagination with custom page size."""
        queryset = BlogPost.objects.all()
        request = self.factory.get('/api/posts/')
        
        paginated_items, pagination_meta = paginate_queryset(queryset, request, page_size=5)
        
        self.assertEqual(len(list(paginated_items)), 5)
        self.assertEqual(pagination_meta['page_size'], 5)
        self.assertEqual(pagination_meta['total_pages'], 5)


class CachingTests(TestCase):
    """Tests for caching utilities."""
    
    def setUp(self):
        # Clear cache before each test
        cache.clear()
        
        # Create test data
        for i in range(5):
            BlogPost.objects.create(
                title=f'Post {i}',
                excerpt=f'Excerpt {i}',
                content=f'Content {i}',
                category='Test',
                featured=(i % 2 == 0)
            )
    
    def test_cache_query_result_caches_results(self):
        """Test that cache decorator caches query results."""
        call_count = {'count': 0}
        
        @cache_query_result(timeout=60, key_prefix='test')
        def get_featured_posts():
            call_count['count'] += 1
            return list(BlogPost.objects.filter(featured=True))
        
        # First call - should execute query
        result1 = get_featured_posts()
        self.assertEqual(call_count['count'], 1)
        self.assertEqual(len(result1), 3)
        
        # Second call - should return cached result
        result2 = get_featured_posts()
        self.assertEqual(call_count['count'], 1)  # No additional call
        self.assertEqual(len(result2), 3)
        
        # Results should be equal
        self.assertEqual([p.id for p in result1], [p.id for p in result2])
    
    def test_cache_respects_timeout(self):
        """Test that cache expires after timeout."""
        @cache_query_result(timeout=1, key_prefix='test_timeout')
        def get_posts():
            return list(BlogPost.objects.all())
        
        # First call
        result1 = get_posts()
        self.assertEqual(len(result1), 5)
        
        # Add a new post
        BlogPost.objects.create(
            title='New Post',
            excerpt='New Excerpt',
            content='New Content',
            category='Test'
        )
        
        # Cached result should still return 5
        result2 = get_posts()
        self.assertEqual(len(result2), 5)
        
        # After cache expires (wait > timeout), should return 6
        import time
        time.sleep(1.5)
        result3 = get_posts()
        self.assertEqual(len(result3), 6)
    
    def test_cache_different_args(self):
        """Test that cache differentiates between different arguments."""
        @cache_query_result(timeout=60, key_prefix='test_args')
        def get_posts_by_category(category):
            return list(BlogPost.objects.filter(category=category))
        
        # Create posts with different categories
        BlogPost.objects.create(title='Tech', excerpt='e', content='c', category='Technology')
        BlogPost.objects.create(title='Design', excerpt='e', content='c', category='Design')
        
        result1 = get_posts_by_category('Technology')
        result2 = get_posts_by_category('Design')
        
        self.assertEqual(len(result1), 1)
        self.assertEqual(len(result2), 1)
        self.assertNotEqual(result1[0].id, result2[0].id)


class DatabaseIndexTests(TestCase):
    """Tests to verify database indexes are working."""
    
    def test_blogpost_indexes_exist(self):
        """Verify BlogPost model has expected indexes."""
        from django.db import connection
        
        # Get table indexes
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'brand_blogpost'
                AND indexname LIKE 'brand_blogpost_%_idx'
            """)
            indexes = [row[0] for row in cursor.fetchall()]
        
        expected_indexes = [
            'brand_blogpost_created_idx',
            'brand_blogpost_updated_idx',
            'brand_blogpost_featured_idx',
            'brand_blogpost_category_idx',
        ]
        
        for expected_index in expected_indexes:
            self.assertIn(expected_index, indexes, 
                         f"Index {expected_index} not found in database")
    
    def test_appointment_indexes_exist(self):
        """Verify Appointment model has expected indexes."""
        from django.db import connection
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT indexname FROM pg_indexes 
                WHERE tablename = 'appointments_appointment'
                AND indexname LIKE 'appt_%_idx'
            """)
            indexes = [row[0] for row in cursor.fetchall()]
        
        expected_indexes = [
            'appt_date_idx',
            'appt_status_idx',
            'appt_date_status_idx',
            'appt_created_idx',
        ]
        
        for expected_index in expected_indexes:
            self.assertIn(expected_index, indexes,
                         f"Index {expected_index} not found in database")


class PerformanceRegressionTests(TestCase):
    """Tests to ensure performance optimizations don't break functionality."""
    
    def setUp(self):
        self.factory = RequestFactory()
    
    def test_api_posts_endpoint_format(self):
        """Test that API endpoint returns correct format with pagination."""
        from brand.api_views import post_list
        
        # Create test posts
        for i in range(3):
            BlogPost.objects.create(
                title=f'Test {i}',
                excerpt=f'Excerpt {i}',
                content=f'Content {i}',
                category='Test'
            )
        
        request = self.factory.get('/api/posts/')
        response = post_list(request)
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        
        # Check structure
        self.assertIn('results', data)
        self.assertIn('pagination', data)
        
        # Check pagination metadata
        pagination = data['pagination']
        self.assertIn('page', pagination)
        self.assertIn('page_size', pagination)
        self.assertIn('total_pages', pagination)
        self.assertIn('total_items', pagination)
        self.assertIn('has_next', pagination)
        self.assertIn('has_previous', pagination)
        
        # Check results
        self.assertEqual(len(data['results']), 3)
        self.assertIn('id', data['results'][0])
        self.assertIn('title', data['results'][0])
