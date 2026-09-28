// Templates: where an email is written. A gallery of saved templates, and an
// editor with a live preview beside it. Campaigns pick from these.

let TEMPLATES = [];
let TEMPLATE_PREVIEW_TIMER = null;

function _templateThumb(t) {
    // Scaled-down render of the saved body. sandbox="" with no scripts: the
    // body is sanitised server side, and this is only a picture of it.
    const doc = `<html><body style="margin:0;padding:24px;background:#fff;font-family:Arial,Helvetica,sans-serif;">${t.body_html || ''}</body></html>`;
    return `<div class="relative h-44 overflow-hidden bg-white rounded-t-xl border-b border-dark-border">
        <iframe sandbox="" tabindex="-1" aria-hidden="true" srcdoc="${escapeHtml(doc)}"
            class="absolute top-0 left-0 origin-top-left pointer-events-none"
            style="width:200%;height:200%;transform:scale(.5);border:0"></iframe>
    </div>`;
}

function _ago(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const days = Math.floor((Date.now() - d) / 86400000);
    if (days < 1) return 'today';
    if (days === 1) return 'yesterday';
    if (days < 30) return `${days} days ago`;
    return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

async function loadTemplates() {
    if (!getEmailEditor('template')) {
        createEmailEditor('template', { onChange: scheduleTemplatePreview });
    }
    const container = document.getElementById('templatesList');
    try {
        TEMPLATES = await fetchJson(`${API_BASE}/messaging/templates/`);
    } catch (e) {
        toastApiError(e, 'Templates could not be loaded.');
        return;
    }
    const canCampaign = typeof window.can === 'function' && window.can('manage_campaigns');
    container.innerHTML = TEMPLATES.length ? TEMPLATES.map(t => `
        <article class="bg-dark-card border border-dark-border rounded-xl flex flex-col hover:border-white/20 transition-colors">
            <button type="button" data-tpl-action="edit" data-id="${t.id}" class="text-left" aria-label="Edit ${escapeHtml(t.name)}">
                ${_templateThumb(t)}
            </button>
            <div class="p-4 flex-1 flex flex-col gap-1 min-w-0">
                <h3 class="font-semibold text-white truncate">${escapeHtml(t.name)}</h3>
                <p class="text-sm text-gray-400 truncate">${escapeHtml(t.subject)}</p>
                <p class="text-xs text-gray-500 mt-1">
                    ${t.used_by ? `Used by ${t.used_by} campaign${t.used_by === 1 ? '' : 's'}` : 'Not used yet'}
                    <span class="mx-1">&middot;</span>edited ${_ago(t.updated_at)}
                </p>
            </div>
            <div class="px-3 pb-3 flex items-center gap-1">
                <button type="button" data-tpl-action="edit" data-id="${t.id}" class="px-3 py-1.5 text-xs rounded-lg text-gray-300 hover:text-white hover:bg-white/5">Edit</button>
                <button type="button" data-tpl-action="duplicate" data-id="${t.id}" class="px-3 py-1.5 text-xs rounded-lg text-gray-300 hover:text-white hover:bg-white/5">Duplicate</button>
                ${canCampaign ? `<button type="button" data-tpl-action="campaign" data-id="${t.id}" class="px-3 py-1.5 text-xs rounded-lg text-brand-green hover:bg-green-900/20">Use in campaign</button>` : ''}
                <button type="button" data-tpl-action="delete" data-id="${t.id}" class="ml-auto p-2 text-xs rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-900/20" title="Delete template" aria-label="Delete template"><i class="fas fa-trash"></i></button>
            </div>
        </article>`).join('') : `
        <div class="col-span-full text-center py-16 border border-dashed border-dark-border rounded-xl">
            <p class="text-gray-300 font-medium">No templates yet</p>
            <p class="text-sm text-gray-500 mt-1">Write an email once, then send it with as many campaigns as you like.</p>
        </div>`;
}

function _showTemplateEditor(show) {
    document.getElementById('templateGalleryView').classList.toggle('hidden', show);
    document.getElementById('templateForm').classList.toggle('hidden', !show);
    window.scrollTo({ top: 0 });
}

function openTemplateEditor(t) {
    const form = document.getElementById('addTemplateForm');
    form.reset();
    form.id.value = t && t.id ? t.id : '';
    form.name.value = t ? t.name : '';
    form.subject.value = t ? t.subject : '';
    const editor = getEmailEditor('template');
    if (editor) editor.setValue(t ? (t.body_source || '') : '');
    document.getElementById('templateFormTitle').textContent = t && t.id ? t.name : 'New template';
    const usedBy = document.getElementById('templateUsedBy');
    usedBy.classList.toggle('hidden', !(t && t.used_by));
    if (t && t.used_by) {
        usedBy.textContent = `Saving also updates the ${t.used_by} draft campaign${t.used_by === 1 ? '' : 's'} using this template, if they have not been queued. Queued and sent campaigns keep the version they were sent with.`;
    }
    _showTemplateEditor(true);
    renderTemplatePreview();
}

function closeTemplateEditor() {
    _showTemplateEditor(false);
    document.getElementById('addTemplateForm').reset();
}

function scheduleTemplatePreview() {
    clearTimeout(TEMPLATE_PREVIEW_TIMER);
    TEMPLATE_PREVIEW_TIMER = setTimeout(renderTemplatePreview, 600);
}

function renderTemplatePreview() {
    const editor = getEmailEditor('template');
    if (editor && !document.getElementById('templateForm').classList.contains('hidden')) editor.preview();
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
    const saveBtn = document.querySelector('button[form="addTemplateForm"]');
    saveBtn.disabled = true;
    try {
        await fetchJson(id ? `${API_BASE}/messaging/templates/${id}/` : `${API_BASE}/messaging/templates/`, {
            method: id ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify(payload),
        });
        toast.success('Template saved.');
        closeTemplateEditor();
        loadTemplates();
    } catch (e) {
        toastApiError(e, 'The template could not be saved.');
    } finally {
        saveBtn.disabled = false;
    }
}

async function duplicateTemplate(id) {
    const t = TEMPLATES.find(x => x.id === id);
    if (!t) return;
    try {
        await fetchJson(`${API_BASE}/messaging/templates/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ name: `${t.name} (copy)`, subject: t.subject, body_source: t.body_source }),
        });
        toast.success('Template duplicated.');
        loadTemplates();
    } catch (e) { toastApiError(e, 'The template could not be duplicated.'); }
}

async function deleteTemplate(id) {
    const t = TEMPLATES.find(x => x.id === id);
    const note = t && t.used_by
        ? 'Campaigns that used it keep their own copy of the email.'
        : 'This removes the template permanently.';
    if (!await tkConfirm(note, { title: 'Delete this template?', confirmText: 'Delete', danger: true })) return;
    try {
        await fetchJson(`${API_BASE}/messaging/templates/${id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': CSRF_TOKEN } });
        toast.success('Template deleted.');
    } catch (e) { toastApiError(e, 'The template could not be deleted.'); }
    loadTemplates();
}

// Opened from a campaign: jump straight to editing one template.
window.editTemplateById = async function (id) {
    showSection('templates');
    try {
        openTemplateEditor(await fetchJson(`${API_BASE}/messaging/templates/${id}/`));
    } catch (e) { toastApiError(e, 'The template could not be opened.'); }
};

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addTemplateForm');
    if (!form) return;
    form.addEventListener('submit', saveTemplate);
    document.getElementById('templateNewBtn').addEventListener('click', () => openTemplateEditor(null));
    document.getElementById('templateBackBtn').addEventListener('click', closeTemplateEditor);
    document.getElementById('templateCancelBtn').addEventListener('click', closeTemplateEditor);
    document.getElementById('templatesList').addEventListener('click', (event) => {
        const btn = event.target.closest('[data-tpl-action]');
        if (!btn) return;
        const id = Number(btn.dataset.id);
        const action = btn.dataset.tplAction;
        if (action === 'edit') openTemplateEditor(TEMPLATES.find(t => t.id === id));
        if (action === 'duplicate') duplicateTemplate(id);
        if (action === 'delete') deleteTemplate(id);
        if (action === 'campaign' && typeof window.startCampaignFrom === 'function') window.startCampaignFrom(id);
    });
});
