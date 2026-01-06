# Brantech Solution Fullstack Project

This repository contains the Django web application for **Brantech Solution** — a dynamic and scalable platform for web development and digital innovation projects.

## 🚀 Features

- **Portfolio Website**: Showcase services, projects, and company information
- **Blog System**: Content management for blog posts with categories, tags, and featured posts
- **Appointment Booking**: Full appointment management system with availability checking
- **AI Chatbot**: Intelligent chatbot powered by Google Gemini with RAG (Retrieval-Augmented Generation) capabilities
- **Admin Panel**: Comprehensive admin interface for managing content
- **REST API**: Full API endpoints for blog posts and projects

## 🛠️ Project Setup Guide

### Prerequisites

- Python 3.8+
- PostgreSQL (optional, SQLite is used by default)
- Virtual environment (recommended)

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/jameskariuki8/brantech-full-website.git
cd brantech-full-website/brandtechsolution
```

### 2️⃣ Create and Activate Virtual Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Linux/Mac:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate
```

### 3️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

### 4️⃣ Environment Configuration

Copy the example environment file and configure it:

```bash
cp env.example .env
```

Edit `.env` file with your configuration:

```bash
# Required settings
SECRET_KEY=your-secret-key-here
GOOGLE_API_KEY=your-google-api-key-here
DATABASE_USER=your-db-user
DATABASE_PASSWORD=your-db-password

# Optional settings
DEBUG=True
ALLOWED_HOSTS=["127.0.0.1","localhost"]
```

**Note**: Generate a new SECRET_KEY for production:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 5️⃣ Database Setup

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Create superuser (optional)
python manage.py createsuperuser
```

### 6️⃣ Initialize Vector Stores (for AI Chatbot)

The AI chatbot uses vector embeddings for blog posts and projects. Initialize the vector stores:

```bash
python manage.py init_vector_stores
```

This command creates vector embeddings for all existing blog posts and projects in the database.

### 7️⃣ Run the Development Server

```bash
python manage.py runserver
```

Visit: **http://127.0.0.1:8000/**

## 📁 Project Structure

```
brandtechsolution/
├── brand/              # Main website app (home, blog, projects, etc.)
├── appointments/       # Appointment booking system
├── ai_workflows/       # AI chatbot with LangChain/Gemini integration
├── brandtechsolution/  # Django project settings
├── media/              # User-uploaded files (images, etc.)
├── staticfiles/        # Collected static files
├── chroma_db/          # Vector database for RAG
└── manage.py           # Django management script
```

## 🔌 API Endpoints

### Blog Posts API

- `GET /api/posts/` - List all blog posts
- `POST /api/posts/` - Create a new blog post (authenticated)
- `GET /api/posts/<id>/` - Get a specific blog post
- `POST /api/posts/<id>/` - Update a blog post (authenticated)
- `DELETE /api/posts/<id>/` - Delete a blog post (authenticated)

### Projects API

- `GET /api/projects/` - List all projects
- `POST /api/projects/` - Create a new project (authenticated)
- `GET /api/projects/<id>/` - Get a specific project
- `POST /api/projects/<id>/` - Update a project (authenticated)
- `DELETE /api/projects/<id>/` - Delete a project (authenticated)

### AI Chatbot API

- `POST /api/ai/chat/` - Chat endpoint (authenticated)
- `POST /api/ai/chat/` - Chat endpoint (public, uses session)
- `GET /api/ai/chat/history/` - Get conversation history
- `POST /api/ai/chat/clear/` - Clear conversation history

### Appointments API

- `GET /appointments/` - List appointments (staff only)
- `POST /appointments/create/` - Create a new appointment
- `POST /appointments/check-availability/` - Check time slot availability
- `GET /appointments/get/` - Get appointment details
- `GET /appointments/admin/manage/<id>/` - Admin appointment management

## 🧪 Running Tests

```bash
# Run all tests
python manage.py test

# Run tests for a specific app
python manage.py test brand
python manage.py test appointments
python manage.py test ai_workflows
```

## 🚀 Deployment

### Production Checklist

1. Set `DEBUG=False` in `.env`
2. Set a strong `SECRET_KEY`
3. Configure `ALLOWED_HOSTS` with your domain
4. Set up PostgreSQL database
5. Configure email settings for production
6. Collect static files: `python manage.py collectstatic`
7. Set up proper media file serving
8. Configure environment variables on your server

### Environment Variables for Production

```bash
DEBUG=False
SECRET_KEY=your-production-secret-key
ALLOWED_HOSTS=["yourdomain.com","www.yourdomain.com"]
DATABASE_ENGINE=postgresql
DATABASE_NAME=brantech
DATABASE_USER=your-db-user
DATABASE_PASSWORD=your-db-password
DATABASE_HOST=localhost
DATABASE_PORT=5432
GOOGLE_API_KEY=your-google-api-key
```

## 📚 Documentation

- [AI Workflows README](brandtechsolution/ai_workflows/README.md) - Detailed documentation for the AI chatbot integration
- [LangChain Integration Docs](docs/langchain-quick-start-guide.md) - Quick start guide for LangChain

## 🛠️ Technology Stack

- **Backend**: Django 5.2.7
- **Database**: PostgreSQL / SQLite
- **AI/ML**: LangChain, LangGraph, Google Gemini
- **Vector Store**: ChromaDB
- **Frontend**: HTML, CSS, JavaScript
- **API**: Django REST Framework

## 📝 License

This project is proprietary software for Brantech Solution.

## 🤝 Contributing

This is a private project. For contributions, please contact the project maintainers.

## 📧 Support

For issues or questions, please contact the development team.

---

**Status**: ✅ Production Ready - Website is fully functional and working correctly.
