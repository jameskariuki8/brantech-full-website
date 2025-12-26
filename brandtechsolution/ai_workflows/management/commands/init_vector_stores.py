"""
Management command to initialize vector stores for RAG
"""
from django.core.management.base import BaseCommand
from ai_workflows.tools import BlogRetrieverTool, ProjectRetrieverTool


class Command(BaseCommand):
    help = 'Initialize vector stores for blog posts and projects'

    def handle(self, *args, **options):
        self.stdout.write('Initializing vector stores...')
        
        # Initialize blog retriever
        self.stdout.write('Initializing blog posts vector store...')
        try:
            blog_retriever = BlogRetrieverTool()
            self.stdout.write(
                self.style.SUCCESS('✓ Blog posts vector store initialized successfully')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Error initializing blog posts vector store: {str(e)}')
            )
        
        # Initialize project retriever
        self.stdout.write('Initializing projects vector store...')
        try:
            project_retriever = ProjectRetrieverTool()
            self.stdout.write(
                self.style.SUCCESS('✓ Projects vector store initialized successfully')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Error initializing projects vector store: {str(e)}')
            )
        
        self.stdout.write(self.style.SUCCESS('\nVector stores initialization complete!'))

