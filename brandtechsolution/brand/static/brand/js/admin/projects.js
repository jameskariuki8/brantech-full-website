async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/projects/`, { credentials: 'same-origin' });
        const payload = await response.json();
        // /api/projects/ is paginated and answers {results, pagination}; a bare
        // array read made the list permanently show "No projects found", the
        // same bug loadBlogs() had.
        const projects = Array.isArray(payload) ? payload : (payload.results || []);
        const container = document.getElementById('projectsList');
        if (!container) return;
        if (!projects.length) {
            container.innerHTML = `<div class="text-center py-10 text-gray-600">No projects found. Add one!</div>`;
            return;
        }
        container.innerHTML = projects.map(project => `
            <div class="bg-dark-card border border-dark-border p-5 rounded-lg flex flex-col md:flex-row justify-between items-start gap-4 hover:border-brand-green/30 transition-colors group">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <span class="text-xs font-bold text-brand-blue px-2 py-1 bg-blue-900/20 rounded">PROJECT</span>
                        ${project.featured ? '<span class="text-xs font-bold text-brand-green px-2 py-1 bg-green-900/20 rounded">FEATURED</span>' : ''}
                    </div>
                    <h3 class="text-xl font-bold text-white mb-1">${project.title}</h3>
                    <p class="text-sm text-gray-400 mb-2">${project.short_description || ''}</p>
                    <a href="${project.project_url || '#'}" target="_blank" class="text-xs text-brand-blue hover:underline">${project.project_url || 'No Live Link'}</a>
                </div>
                <div class="flex gap-2">
                    <button onclick="editProject(${project.id})" class="p-2 text-blue-400 hover:bg-blue-900/30 rounded-lg transition-colors"><i class="fas fa-edit"></i></button>
                    <button onclick="deleteItem('projects', ${project.id})" class="p-2 text-red-400 hover:bg-red-900/30 rounded-lg transition-colors"><i class="fas fa-trash"></i></button>
                </div>
            </div>
        `).join('');
    } catch (e) { console.error(e); }
}

async function editProject(id) {
    try {
        const p = await fetch(`${API_BASE}/projects/${id}/`).then(r => r.json());
        const form = document.getElementById('addProjectForm');
        form.title.value = p.title || '';
        if (form.short_description && p.short_description) form.short_description.value = p.short_description;
        form.description.value = p.description || '';
        form.project_url.value = p.project_url || '';
        form.github_url.value = p.github_url || '';
        form.featured.checked = p.featured;

        document.querySelector('#projectForm h3').textContent = 'Edit Project';
        const btn = document.querySelector('#projectForm button[type="submit"]');
        btn.textContent = 'Update Project';

        form.onsubmit = async (e) => { e.preventDefault(); await updateItem('projects', id, e.target); };
        showAddForm('project');
    } catch (e) { console.error(e); }
}

// Bind initial submit
// The section is only rendered for holders of manage_projects, so the form
// may legitimately be absent.
const addProjectFormEl = document.getElementById('addProjectForm');
if (addProjectFormEl) {
    addProjectFormEl.onsubmit = async (e) => { e.preventDefault(); await addItem('projects', e.target); };
}
