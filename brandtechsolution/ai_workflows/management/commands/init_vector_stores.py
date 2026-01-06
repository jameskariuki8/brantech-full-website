"""
Management command to generate and store embeddings for blog posts and projects.
Uses pgvector with Django ORM - embeddings are stored directly in the model tables.
"""
from django.core.management.base import BaseCommand
from ai_workflows.tools import get_embeddings
from brand.models import BlogPost, Project


class Command(BaseCommand):
    help = 'Generate and store embeddings for blog posts and projects in PostgreSQL using pgvector'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate embeddings even for records that already have them',
        )

    def handle(self, *args, **options):
        force = options.get('force', False)
        embeddings = get_embeddings()
        
        self.stdout.write('Generating embeddings for content...\n')
        
        # Process blog posts
        self.stdout.write('Processing blog posts...')
        try:
            if force:
                posts = BlogPost.objects.all()
            else:
                posts = BlogPost.objects.filter(embedding__isnull=True)
            
            total_posts = posts.count()
            if total_posts == 0:
                self.stdout.write(self.style.WARNING('No blog posts to process'))
            else:
                processed = 0
                posts_to_update = []
                
                for post in posts:
                    text = post.get_embedding_text()
                    embedding_vector = embeddings.embed_query(text)
                    post.embedding = embedding_vector
                    posts_to_update.append(post)
                    processed += 1
                    self.stdout.write(f'  [{processed}/{total_posts}] Processed: {post.title}')
                
                # Bulk update for better performance
                if posts_to_update:
                    BlogPost.objects.bulk_update(posts_to_update, ['embedding'], batch_size=100)
                
                self.stdout.write(self.style.SUCCESS(f'✓ Generated embeddings for {processed} blog posts'))
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Error processing blog posts: {str(e)}')
            )
        
        # Process projects
        self.stdout.write('\nProcessing projects...')
        try:
            if force:
                projects = Project.objects.all()
            else:
                projects = Project.objects.filter(embedding__isnull=True)
            
            total_projects = projects.count()
            if total_projects == 0:
                self.stdout.write(self.style.WARNING('No projects to process'))
            else:
                processed = 0
                projects_to_update = []
                
                for project in projects:
                    text = project.get_embedding_text()
                    embedding_vector = embeddings.embed_query(text)
                    project.embedding = embedding_vector
                    projects_to_update.append(project)
                    processed += 1
                    self.stdout.write(f'  [{processed}/{total_projects}] Processed: {project.title}')
                
                # Bulk update for better performance
                if projects_to_update:
                    Project.objects.bulk_update(projects_to_update, ['embedding'], batch_size=100)
                
                self.stdout.write(self.style.SUCCESS(f'✓ Generated embeddings for {processed} projects'))
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Error processing projects: {str(e)}')
            )
        
        self.stdout.write(self.style.SUCCESS('\n✓ Embedding generation complete!'))

