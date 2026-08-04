async function loadTemplates() {
    const res = await fetch(`${API_BASE}/messaging/templates/`, { credentials: 'same-origin' });
    const items = await res.json();
    const container = document.getElementById('templatesList');
    container.innerHTML = items.length ? items.map(t => `
        <div class="bg-dark-card border border-dark-border p-5 rounded-lg flex justify-between items-start gap-4">
            <div class="flex-1">
                <h3 class="text-lg font-bold text-white">${escapeHtml(t.name)}</h3>
                <p class="text-sm text-gray-400">${escapeHtml(t.subject)}</p>
            </div>
            <div class="flex gap-2">
                <button onclick="editTemplate(${t.id})" class="p-2 text-blue-400 hover:bg-blue-900/30 rounded"><i class="fas fa-edit"></i></button>
                <button onclick="deleteTemplate(${t.id})" class="p-2 text-red-400 hover:bg-red-900/30 rounded"><i class="fas fa-trash"></i></button>
            </div>
        </div>`).join('') : `<div class="text-center py-10 text-gray-600">No templates yet.</div>`;
    if (!getEmailEditor('template')) createEmailEditor('template');
}

async function saveTemplate(event) {
    event.preventDefault();
    const form = event.target;
    const id = form.id.value;
    const editor = getEmailEditor('template');
    const payload = {
        name: form.name.value,
        subject: form.subject.value,
        body_source: editor ? editor.getValue() : '',
    };
    const url = id ? `${API_BASE}/messaging/templates/${id}/` : `${API_BASE}/messaging/templates/`;
    const method = id ? 'PUT' : 'POST';
    const res = await fetch(url, {
        method, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify(payload),
    });
    if (res.ok) { hideAddForm('template'); form.reset(); form.id.value = ''; toast.success('Template saved.'); loadTemplates(); }
    else { toastApiError(await apiErrorFromResponse(res), 'The template could not be saved.'); }
}

async function editTemplate(id) {
    const t = await fetch(`${API_BASE}/messaging/templates/${id}/`, { credentials: 'same-origin' }).then(r => r.json());
    const form = document.getElementById('addTemplateForm');
    form.id.value = t.id; form.name.value = t.name; form.subject.value = t.subject;
    const editor = getEmailEditor('template');
    if (editor) editor.setValue(t.body_source || '');
    showAddForm('template');
}

async function deleteTemplate(id) {
    if (!await tkConfirm('This removes the template permanently.', { title: 'Delete this template?', confirmText: 'Delete', danger: true })) return;
    try {
        await fetchJson(`${API_BASE}/messaging/templates/${id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': CSRF_TOKEN } });
        toast.success('Template deleted.');
    } catch (e) { toastApiError(e, 'The template could not be deleted.'); }
    loadTemplates();
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addTemplateForm');
    if (form) form.addEventListener('submit', saveTemplate);
});
