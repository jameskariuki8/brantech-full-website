const API_BASE = '/api';
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}
const CSRF_TOKEN = getCookie('csrftoken');

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// escapeHtml() makes a value safe as TEXT, but an href is a second context:
// `javascript:alert(1)` contains no character escapeHtml touches, and would
// still execute on click. Anything not plainly http(s) or a relative path
// becomes '#'. Staff-supplied content is not trusted here - a manage_projects
// holder must not be able to plant a payload that runs in an administrator's
// session and calls the staff API with their cookies.
function safeUrl(value) {
    if (!value) return '#';
    const raw = String(value).trim();
    if (/^https?:\/\//i.test(raw)) return raw;
    if (/^\/(?!\/)/.test(raw)) return raw;
    return '#';
}

// Toggle Sidebar
const mobileMenuBtn = document.getElementById('mobileMenuBtn');
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('mobileOverlay');

mobileMenuBtn.addEventListener('click', () => {
    sidebar.classList.toggle('-translate-x-full');
    overlay.classList.toggle('hidden');
});

overlay.addEventListener('click', () => {
    sidebar.classList.add('-translate-x-full');
    overlay.classList.add('hidden');
});

function showSection(sectionName, clickedElement) {
    // Main content sections
    document.querySelectorAll('.section').forEach(section => { section.classList.add('hidden'); });
    const targetSection = document.getElementById(sectionName);
    if (targetSection) targetSection.classList.remove('hidden');

    // Sidebar highlighting
    document.querySelectorAll('.nav-item').forEach(link => { link.classList.remove('active'); });
    if (clickedElement) clickedElement.classList.add('active');

    // Close mobile menu on navigate
    if (window.innerWidth < 1024) {
        sidebar.classList.add('-translate-x-full');
        overlay.classList.add('hidden');
    }

    // Load data
    if (sectionName === 'blogs') loadBlogs();
    if (sectionName === 'projects') loadProjects();
    // Events removed
    if (sectionName === 'dashboard') loadDashboard();
    if (sectionName === 'inbox') loadInbox();
    if (sectionName === 'templates') loadTemplates();
    if (sectionName === 'campaigns') loadCampaigns();
    if (sectionName === 'staff') loadStaff();
    if (sectionName === 'tasks') loadTasks();
}

function showAddForm(type) { document.getElementById(`${type}Form`).classList.remove('hidden'); }
function hideAddForm(type) {
    document.getElementById(`${type}Form`).classList.add('hidden');
    const form = document.getElementById(`add${type.charAt(0).toUpperCase() + type.slice(1)}Form`);
    form.reset();
    if (typeof getEmailEditor === 'function') {
        const editor = getEmailEditor(type);
        if (editor) editor.setValue('');
    }
    // Reset header back to 'Add' state visually if needed, simplified here
}

// /api/posts/ and /api/projects/ answer {results, pagination} where
// pagination.total_items is the true row count. Reading .length off that
// object yields undefined, which is why both dashboard cards read 0. Falls
// back to the page length, and then to a bare array, so an unpaginated
// response still counts.
function payloadCount(payload) {
    if (Array.isArray(payload)) return payload.length;
    if (payload && payload.pagination && typeof payload.pagination.total_items === 'number') {
        return payload.pagination.total_items;
    }
    return (payload && payload.results ? payload.results.length : 0);
}

async function loadDashboard() {
    try {
        const common = { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } };
        const [blogs, projects] = await Promise.all([
            fetch(`${API_BASE}/posts/`, common).then(r => r.json()),
            fetch(`${API_BASE}/projects/`, common).then(r => r.json())
        ]);

        document.getElementById('blogCount').textContent = payloadCount(blogs);
        document.getElementById('projectCount').textContent = payloadCount(projects);



    } catch (error) { console.error('Error loading dashboard:', error); }
}

// CRUD helpers
async function addItem(endpoint, form) {
    const formData = new FormData(form);
    if (formData.has('featured')) { formData.set('featured', formData.get('featured') === 'on' ? 'true' : 'false'); } else { formData.set('featured', 'false'); }
    try {
        const response = await fetch(`${API_BASE}/${endpoint}/`, { method: 'POST', body: formData, credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (response.ok) {
            alert('Saved successfully!');
            form.reset();
            // hideAddForm call moved to specific blocks below to ensure correct ID is used
            if (endpoint === 'posts') { hideAddForm('blog'); loadBlogs(); }
            if (endpoint === 'projects') { hideAddForm('project'); loadProjects(); }
        } else {
            alert('Error saving item');
        }
    } catch (e) { console.error(e); alert('Error'); }
}

async function updateItem(endpoint, id, form) {
    const formData = new FormData(form);
    if (formData.has('featured')) { formData.set('featured', formData.get('featured') === 'on' ? 'true' : 'false'); } else { formData.set('featured', 'false'); }

    try {
        // Use POST for updates to support file uploads (Django doesn't handle multipart PUT well)
        const response = await fetch(`${API_BASE}/${endpoint}/${id}/`, { method: 'POST', body: formData, credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (response.ok) {
            alert('Updated!');
            form.reset();
            form.onsubmit = null; // Remove override

            // Reset UI text
            const type = endpoint === 'posts' ? 'blog' : 'project';
            document.querySelector(`#${type}Form h3`).textContent = type === 'blog' ? 'New Blog Post' : 'New Project Details';
            document.querySelector(`#${type}Form button[type="submit"]`).textContent = type === 'blog' ? 'Save Post' : 'Save Project';

            if (endpoint === 'posts') { hideAddForm('blog'); loadBlogs(); document.getElementById('addBlogForm').onsubmit = async (e) => { e.preventDefault(); await addItem('posts', e.target); }; }
            if (endpoint === 'projects') { hideAddForm('project'); loadProjects(); document.getElementById('addProjectForm').onsubmit = async (e) => { e.preventDefault(); await addItem('projects', e.target); }; }
        } else { alert('Update failed'); }
    } catch (e) { console.error(e); alert('Error'); }
}

async function deleteItem(endpoint, id) {
    if (!confirm('Delete this item permanently?')) return;
    try {
        const res = await fetch(`${API_BASE}/${endpoint}/${id}/`, { method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (res.ok) {
            if (endpoint === 'posts') loadBlogs();
            if (endpoint === 'projects') loadProjects();
        } else { alert('Delete failed'); }
    } catch (e) { console.error(e); }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    // Highlight dashboard initially
    document.querySelector('a[onclick*="dashboard"]').classList.add('active');
});
