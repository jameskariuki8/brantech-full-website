# AI Workflows - Setup Complete

This app integrates LangChain with Google Gemini for AI-powered chatbot and future workflows.

## What's Been Implemented

### ✅ Core Components

1. **Django Models** (`models.py`)
   - `ConversationThread`: Tracks conversation/workflow threads
   - `ConversationCheckpoint`: Stores LangGraph checkpoint data
   - `WorkflowState`: Tracks workflow-specific state

2. **Custom Django Checkpointer** (`checkpointer.py`)
   - Implements LangGraph's `BaseCheckpointSaver` interface
   - Stores all checkpoint data in Django models
   - Enables conversation persistence

3. **Chatbot Agent** (`agents.py`)
   - Uses Google Gemini (`gemini-2.0-flash-exp`)
   - Integrated with RAG tools for blog posts and projects
   - Conversation memory via Django checkpointer

4. **RAG Tools** (`tools.py`)
   - `BlogRetrieverTool`: Searches blog posts using vector similarity
   - `ProjectRetrieverTool`: Searches projects using vector similarity
   - Uses Google Gemini embeddings (`models/embedding-001`)

5. **API Endpoints** (`views.py` & `urls.py`)
   - `POST /api/ai/chat/` - Authenticated chat endpoint
   - `POST /api/ai/chat/public/` - Public chat endpoint
   - `GET /api/ai/chat/history/<thread_id>/` - Get conversation history
   - `DELETE /api/ai/chat/history/<thread_id>/` - Delete conversation history

6. **Admin Interface** (`admin.py`)
   - Full admin interface for all models
   - View and manage conversations and checkpoints

7. **Management Command**
   - `python manage.py init_vector_stores` - Initialize vector stores

## Next Steps

### 1. Run Migrations

```bash
cd brandtechsolution
source .venv/bin/activate  # or venv\Scripts\activate on Windows
python manage.py makemigrations ai_workflows
python manage.py migrate
```

### 2. Initialize Vector Stores

```bash
python manage.py init_vector_stores
```

This will create vector embeddings for all blog posts and projects.

### 3. Update .env File

Make sure your `.env` file in `brandtechsolution/` contains:

```bash
GOOGLE_API_KEY=your_google_api_key_here
CHROMA_PERSIST_DIRECTORY=./chroma_db
GEMINI_CHAT_MODEL=gemini-2.0-flash-exp
GEMINI_EMBEDDING_MODEL=models/embedding-001
LANGSMITH_TRACING=False
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=brantech-ai
```

**Note**: If you want to use a different Gemini model, update `GEMINI_CHAT_MODEL` in your `.env` file. Available models include:
- `gemini-2.0-flash-exp` (default, fast)
- `gemini-1.5-pro` (more capable)
- `gemini-1.5-flash` (balanced)

### 4. Test the API

#### Public Endpoint (No Auth):
```bash
curl -X POST http://localhost:8000/api/ai/chat/public/ \
  -H "Content-Type: application/json" \
  -d '{"message": "What services do you offer?", "thread_id": "test_123"}'
```

#### Authenticated Endpoint:
```bash
curl -X POST http://localhost:8000/api/ai/chat/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"message": "Tell me about your projects", "thread_id": "user_123"}'
```

### 5. Update Frontend

Update `chat-assistant.js` to use the new Django API:

```javascript
// Change from:
this.chatEndpoint = 'https://n8n.bigaddict.shop/webhook/brantech/chatbot';

// To:
this.chatEndpoint = '/api/ai/chat/public/';
```

## Configuration

### Model Configuration

Edit `brandtechsolution/config.py` or set environment variables:

- `GEMINI_CHAT_MODEL`: Chat model name (default: `gemini-2.0-flash-exp`)
- `GEMINI_EMBEDDING_MODEL`: Embedding model name (default: `models/embedding-001`)

### Vector Store

Vector stores are stored in `chroma_db/` directory (configurable via `CHROMA_PERSIST_DIRECTORY`).

To rebuild vector stores after adding new blog posts or projects:
```bash
python manage.py init_vector_stores
```

## API Usage Examples

### Python
```python
import requests

# Public chat
response = requests.post(
    'http://localhost:8000/api/ai/chat/public/',
    json={
        'message': 'What services do you offer?',
        'thread_id': 'my_thread_123'
    }
)
print(response.json())
```

### JavaScript
```javascript
const response = await fetch('/api/ai/chat/public/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
    },
    body: JSON.stringify({
        message: 'What services do you offer?',
        thread_id: 'my_thread_123'
    })
});

const data = await response.json();
console.log(data.response);
```

## Troubleshooting

### Import Errors
- Make sure all dependencies are installed: `pip install -r requirements.txt`
- Verify virtual environment is activated

### Vector Store Errors
- Run `python manage.py init_vector_stores` to initialize
- Check that blog posts and projects exist in database

### API Key Errors
- Verify `GOOGLE_API_KEY` is set in `.env` file
- Check that `.env` file is in `brandtechsolution/` directory

### Model Not Found
- Verify model name in config matches available Gemini models
- Check Google AI Studio for available models

## Architecture

```
User Request
    ↓
Django API Endpoint
    ↓
Chatbot Agent (Gemini)
    ↓
RAG Tools → Vector Store (ChromaDB)
    ↓
Django Checkpointer → Database
    ↓
Response
```

## Future Enhancements

- Blog generation workflow
- Content enhancement tools
- Multi-agent systems
- Streaming responses
- Analytics dashboard

