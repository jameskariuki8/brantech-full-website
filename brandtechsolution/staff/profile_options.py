"""What a staff member can say about themselves, in one place.

Shared by the onboarding page, which renders them as pills, and by the /me
API, which hands them to the dashboard profile editor so both offer the same
choices. Choices are suggestions: a person may also type their own, so the
stored values are free text and nothing here is enforced on write.
"""

# The parts of the business a person works in. Several may apply: someone can
# run marketing and still do some sales.
SCOPE_CHOICES = [
    "Engineering",
    "Product & Design",
    "Marketing",
    "Sales & Partnerships",
    "Content & Editorial",
    "Customer Support",
    "Operations",
    "Finance & Admin",
    "People & Hiring",
    "Leadership",
]

COMMON_LANGUAGES = [
    "Python", "JavaScript", "TypeScript", "HTML / CSS", "SQL",
    "Dart", "Kotlin", "Java", "Go", "Rust", "C / C++",
    "Bash / Shell", "PHP", "Swift", "Solidity",
]

COMMON_FRAMEWORKS = [
    # Web & Backend Frameworks
    "Django", "FastAPI", "Flask", "Django REST Framework", "Express.js", "Node.js", "Next.js", "React", "Vue.js", "Tailwind CSS", "HTMX",
    # AI, Computer Vision & Audio
    "OpenCV", "PyTorch", "TensorFlow", "Google Gemini API", "LangGraph / LangChain", "OpenAI / Claude APIs", "Whisper / Audio AI", "ChromaDB / Vector RAG", "Ollama / Local LLMs",
    # Automation, Bots & Integrations
    "Playwright", "Browser-Use", "Selenium", "BeautifulSoup / Scrapy", "Evolution API / WhatsApp Automation", "Telegram Bot API", "n8n Workflows", "M-Pesa / Daraja API",
    # Mobile & Desktop UI
    "Flutter", "Android SDK / Kotlin", "PySide6 / PyQt", "Electron", "Tauri",
    # Database, Cloud & DevOps
    "PostgreSQL", "Redis", "SQLite", "MongoDB", "Docker", "Docker Compose", "Nginx", "Linux Server Admin", "Git / GitHub Actions", "Cloudflare Tunnels",
]

ROLE_CHOICES = [
    "Fullstack Engineer",
    "Backend Developer",
    "Frontend Engineer",
    "AI / ML & Computer Vision Engineer",
    "Mobile Developer (Flutter / Android / iOS)",
    "Automation & Bot Specialist",
    "DevOps & Infrastructure Engineer",
    "QA / Automation Testing Engineer",
    "Product / UI/UX Designer",
    "Technical Writer & Content Editor",
    # Non-engineering titles, so the picker fits everyone who works here.
    "Marketing Lead",
    "Digital Marketer / Social Media",
    "Sales & Partnerships Lead",
    "Customer Support Specialist",
    "Operations Manager",
    "Finance & Administration",
    "People & Hiring",
    "Founder / Executive",
]


MAX_LIST_ITEMS = 30
MAX_ITEM_LENGTH = 64


def clean_list(values):
    """Trim, drop blanks, de-duplicate (case-insensitively) and sort."""
    seen = {}
    for value in values:
        item = str(value).strip()[:MAX_ITEM_LENGTH]
        if item:
            seen.setdefault(item.lower(), item)
    return sorted(seen.values(), key=str.lower)[:MAX_LIST_ITEMS]
