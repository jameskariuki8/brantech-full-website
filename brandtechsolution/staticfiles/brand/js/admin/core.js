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

function showSection(sectionName, clickedElement) {
    // Main content sections
    document.querySelectorAll('.section').forEach(section => { section.classList.add('hidden'); });
    const targetSection = document.getElementById(sectionName);
    if (targetSection) targetSection.classList.remove('hidden');

    // Sidebar highlighting
    document.querySelectorAll('.nav-item').forEach(link => { link.classList.remove('active'); });
    if (clickedElement) {
        clickedElement.classList.add('active');
    } else {
        const matchingLink = document.getElementById(`nav-${sectionName}`);
        if (matchingLink) matchingLink.classList.add('active');
    }

    // Close mobile menu on navigate
    const sbar = document.getElementById('sidebar');
    const ovr = document.getElementById('mobileOverlay');
    if (window.innerWidth < 1024 && sbar && ovr) {
        sbar.classList.add('-translate-x-full');
        ovr.classList.add('hidden');
    }

    // Load data
    if (sectionName === 'blogs') loadBlogs();
    if (sectionName === 'projects') loadProjects();
    // Events removed
    if (sectionName === 'dashboard') loadDashboard();
    if (sectionName === 'inbox') loadInbox();
    if (sectionName === 'templates') loadTemplates();
    if (sectionName === 'campaigns') loadCampaigns();
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

let topBlogsChartInstance = null;
let appointmentsChartInstance = null;
let inquiriesChartInstance = null;
let campaignsChartInstance = null;

async function loadDashboard() {
    try {
        const res = await fetch(`${API_BASE}/admin/stats/`, { credentials: 'same-origin' });
        const data = await res.json();

        // Populate metrics
        document.getElementById('blogCount').textContent = data.metrics.total_blogs ?? 0;
        document.getElementById('blogViewsCount').textContent = data.metrics.total_blog_views ?? 0;
        document.getElementById('projectCount').textContent = data.metrics.total_projects ?? 0;
        document.getElementById('eventCount').textContent = data.metrics.total_events ?? 0;
        document.getElementById('templateCount').textContent = data.metrics.total_templates ?? 0;
        document.getElementById('campaignCount').textContent = data.metrics.total_campaigns ?? 0;
        document.getElementById('inquiryCount').textContent = data.metrics.total_inquiries ?? 0;
        document.getElementById('appointmentCount').textContent = data.metrics.total_appointments ?? 0;
        
        const likesEl = document.getElementById('likesCount');
        if (likesEl) likesEl.textContent = data.metrics.total_likes ?? 0;
        const commentsEl = document.getElementById('commentsCount');
        if (commentsEl) commentsEl.textContent = data.metrics.total_comments ?? 0;

        // Dark theme chart settings
        const fontSettings = {
            family: 'Inter, sans-serif',
            color: '#9ca3af'
        };

        const chartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#9ca3af',
                        boxWidth: 12,
                        padding: 15,
                        font: { family: 'Inter, sans-serif', size: 11 }
                    }
                }
            }
        };

        // 1. Top Blogs Bar Chart
        if (topBlogsChartInstance) topBlogsChartInstance.destroy();
        const topBlogsCtx = document.getElementById('topBlogsChart')?.getContext('2d');
        if (topBlogsCtx) {
            topBlogsChartInstance = new Chart(topBlogsCtx, {
                type: 'bar',
                data: {
                    labels: data.charts.top_blogs.map(b => b.title),
                    datasets: [{
                        label: 'Views',
                        data: data.charts.top_blogs.map(b => b.views),
                        backgroundColor: 'rgba(0, 122, 255, 0.8)',
                        borderColor: '#007AFF',
                        borderWidth: 1,
                        borderRadius: 6
                    }]
                },
                options: {
                    ...chartOptions,
                    indexAxis: 'y',
                    plugins: {
                        ...chartOptions.plugins,
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: { color: '#9ca3af', font: { family: 'Inter' } }
                        },
                        y: {
                            grid: { display: false },
                            ticks: { color: '#9ca3af', font: { family: 'Inter' } }
                        }
                    }
                }
            });
        }

        // 2. Appointments Breakdown (Doughnut Chart)
        if (appointmentsChartInstance) appointmentsChartInstance.destroy();
        const appointmentsCtx = document.getElementById('appointmentsChart')?.getContext('2d');
        if (appointmentsCtx) {
            const labels = Object.keys(data.charts.appointments).map(s => s.toUpperCase());
            const values = Object.values(data.charts.appointments);
            const hasData = values.some(v => v > 0);

            appointmentsChartInstance = new Chart(appointmentsCtx, {
                type: 'doughnut',
                data: {
                    labels: hasData ? labels : ['NO DATA'],
                    datasets: [{
                        data: hasData ? values : [1],
                        backgroundColor: hasData ? [
                            'rgba(234, 179, 8, 0.8)',  // pending (Yellow)
                            'rgba(59, 130, 246, 0.8)', // confirmed (Blue)
                            'rgba(16, 185, 129, 0.8)', // completed (Green)
                            'rgba(239, 68, 68, 0.8)',   // cancelled (Red)
                            'rgba(168, 85, 247, 0.8)'  // rescheduled (Purple)
                        ] : ['rgba(255, 255, 255, 0.05)'],
                        borderColor: '#0D121D',
                        borderWidth: 2
                    }]
                },
                options: chartOptions
            });
        }

        // 3. Inquiries Breakdown (Pie Chart)
        if (inquiriesChartInstance) inquiriesChartInstance.destroy();
        const inquiriesCtx = document.getElementById('inquiriesChart')?.getContext('2d');
        if (inquiriesCtx) {
            const labels = Object.keys(data.charts.inquiries).map(s => s.toUpperCase());
            const values = Object.values(data.charts.inquiries);
            const hasData = values.some(v => v > 0);

            inquiriesChartInstance = new Chart(inquiriesCtx, {
                type: 'pie',
                data: {
                    labels: hasData ? labels : ['NO DATA'],
                    datasets: [{
                        data: hasData ? values : [1],
                        backgroundColor: hasData ? [
                            'rgba(249, 115, 22, 0.8)', // new (Orange)
                            'rgba(107, 114, 128, 0.8)', // read (Gray)
                            'rgba(6, 182, 212, 0.8)',  // replied (Cyan)
                            'rgba(16, 185, 129, 0.8)'  // archived (Green)
                        ] : ['rgba(255, 255, 255, 0.05)'],
                        borderColor: '#0D121D',
                        borderWidth: 2
                    }]
                },
                options: chartOptions
            });
        }

        // 4. Campaigns Overview (Doughnut Chart)
        if (campaignsChartInstance) campaignsChartInstance.destroy();
        const campaignsCtx = document.getElementById('campaignsChart')?.getContext('2d');
        if (campaignsCtx) {
            const labels = Object.keys(data.charts.campaigns).map(s => s.toUpperCase());
            const values = Object.values(data.charts.campaigns);
            const hasData = values.some(v => v > 0);

            campaignsChartInstance = new Chart(campaignsCtx, {
                type: 'doughnut',
                data: {
                    labels: hasData ? labels : ['NO DATA'],
                    datasets: [{
                        data: hasData ? values : [1],
                        backgroundColor: hasData ? [
                            'rgba(107, 114, 128, 0.8)', // draft (Gray)
                            'rgba(234, 179, 8, 0.8)',  // queued (Yellow)
                            'rgba(14, 165, 233, 0.8)', // sending (Light Blue)
                            'rgba(16, 185, 129, 0.8)', // sent (Green)
                            'rgba(168, 85, 247, 0.8)', // paused (Purple)
                            'rgba(239, 68, 68, 0.8)'   // failed (Red)
                        ] : ['rgba(255, 255, 255, 0.05)'],
                        borderColor: '#0D121D',
                        borderWidth: 2
                    }]
                },
                options: chartOptions
            });
        }

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
    if (window.location.pathname.startsWith('/admin-panel/')) {
        // Intercept sidebar clicks on /admin-panel/ to prevent reload
        document.querySelectorAll('.nav-item').forEach(link => {
            const href = link.getAttribute('href');
            if (href && href.includes('?section=')) {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    const urlParams = new URLSearchParams(href.split('?')[1]);
                    const section = urlParams.get('section');
                    if (section) {
                        showSection(section, link);
                        // Update browser URL without reload
                        history.pushState(null, '', href);
                    }
                });
            }
        });

        // Load correct section from URL query param or default to dashboard
        const urlParams = new URLSearchParams(window.location.search);
        const section = urlParams.get('section') || 'dashboard';
        const activeLink = document.getElementById(`nav-${section}`);
        showSection(section, activeLink);
    }
});
