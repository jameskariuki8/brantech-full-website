let TEMPLATE_CACHE = [];

async function loadCampaigns() {
    // Populate template dropdown
    TEMPLATE_CACHE = await fetch(`${API_BASE}/messaging/templates/`, { credentials: 'same-origin' }).then(r => r.json());
    const sel = document.getElementById('campaignTemplate');
    if (sel) sel.innerHTML = `<option value="">— none —</option>` + TEMPLATE_CACHE.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');

    if (!getEmailEditor('campaign')) createEmailEditor('campaign');

    const items = await fetch(`${API_BASE}/messaging/campaigns/`, { credentials: 'same-origin' }).then(r => r.json());
    const container = document.getElementById('campaignsList');
    // send_campaigns is separate from manage_campaigns, so a marketer who can
    // build a campaign but not send it should see why the button is absent
    // rather than find it silently missing. Cosmetic only - the campaign
    // send/pause/resume endpoints enforce the capability themselves.
    const canSend = typeof window.can === 'function' ? window.can('send_campaigns') : false;
    const statusColor = { draft: 'text-gray-400 bg-white/5', queued: 'text-brand-blue bg-blue-900/20', sending: 'text-yellow-400 bg-yellow-900/20', sent: 'text-brand-green bg-green-900/20', paused: 'text-orange-400 bg-orange-900/20', failed: 'text-red-400 bg-red-900/20' };
    container.innerHTML = items.length ? items.map(c => `
        <div class="bg-dark-card border border-dark-border p-5 rounded-lg">
            <div class="flex justify-between items-start gap-4">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <span class="text-xs font-bold px-2 py-1 rounded uppercase ${statusColor[c.status] || ''}">${escapeHtml(c.status)}</span>
                    </div>
                    <h3 class="text-lg font-bold text-white">${escapeHtml(c.name)}</h3>
                    <p class="text-sm text-gray-400">${escapeHtml(c.subject)}</p>
                    <p class="text-xs text-gray-500 mt-2">${c.sent_count}/${c.total} sent${c.failed_count ? ` · ${c.failed_count} failed` : ''}</p>
                </div>
                <div class="flex flex-col gap-2 w-48">
                    <button type="button" data-action="open-recipients" data-campaign-id="${c.id}" data-campaign-name="${escapeHtml(c.name)}" class="bg-dark-card border border-dark-border hover:border-brand-blue text-white text-xs px-3 py-1.5 rounded">View recipients (${c.total})</button>
                    ${c.status === 'draft' ? `
                        <label class="text-xs text-gray-400">Audience:</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="inquiries"> Inquiries</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="users"> Users</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="appointments"> Appointments</label>
                        <textarea id="manual-${c.id}" placeholder="paste emails, comma/space separated" class="bg-[#06090F] border border-dark-border rounded px-2 py-1 text-xs text-white" rows="2"></textarea>
                        <input type="file" id="import-${c.id}" onchange="importEmails(event)" data-c="${c.id}" class="text-xs text-gray-400" accept=".csv,.txt,.xlsx,.pdf,.docx">
                        <button onclick="buildRecipients(${c.id})" class="bg-dark-card border border-dark-border hover:border-brand-blue text-white text-xs px-3 py-1.5 rounded">Build recipients</button>
                        ${canSend
                            ? `<button onclick="queueCampaign(${c.id})" class="bg-brand-green hover:bg-green-500 text-black text-xs font-semibold px-3 py-1.5 rounded">Queue send (${c.total})</button>`
                            : `<span class="text-xs text-gray-500 italic">Ready — awaiting an administrator to send</span>`}
                    ` : ``}
                    ${(c.status === 'queued' || c.status === 'sending') && canSend ? `
                        <button onclick="pauseCampaign(${c.id})" class="bg-dark-card border border-orange-500 hover:bg-orange-900/20 text-orange-400 text-xs font-semibold px-3 py-1.5 rounded">Pause</button>
                    ` : ``}
                    ${c.status === 'paused' && canSend ? `
                        <button onclick="resumeCampaign(${c.id})" class="bg-brand-green hover:bg-green-500 text-black text-xs font-semibold px-3 py-1.5 rounded">Resume</button>
                    ` : ``}
                </div>
            </div>
        </div>`).join('') : `<div class="text-center py-10 text-gray-600">No campaigns yet.</div>`;
}

function applyTemplate() {
    const id = document.getElementById('campaignTemplate').value;
    const t = TEMPLATE_CACHE.find(x => String(x.id) === String(id));
    const form = document.getElementById('addCampaignForm');
    if (!t) return;
    form.subject.value = t.subject;
    const editor = getEmailEditor('campaign');
    if (editor) editor.setValue(t.body_source || '');
}

async function createCampaign(event) {
    event.preventDefault();
    const form = event.target;
    const editor = getEmailEditor('campaign');
    const payload = {
        name: form.name.value,
        subject: form.subject.value,
        body_source: editor ? editor.getValue() : '',
    };
    const res = await fetch(`${API_BASE}/messaging/campaigns/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify(payload),
    });
    if (res.ok) { hideAddForm('campaign'); form.reset(); toast.success('Campaign created.'); loadCampaigns(); }
    else { toastApiError(await apiErrorFromResponse(res), 'The campaign could not be created.'); }
}

function _manualEmails(id) {
    const el = document.getElementById(`manual-${id}`);
    return el ? el.value.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean) : [];
}

async function importEmails(event) {
    const input = event.target;
    const id = input.dataset.c;
    const fd = new FormData();
    fd.append('file', input.files[0]);
    const res = await fetch(`${API_BASE}/messaging/extract-emails/`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN }, body: fd,
    });
    if (res.ok) {
        const data = await res.json();
        const box = document.getElementById(`manual-${id}`);
        box.value = (box.value ? box.value + '\n' : '') + data.emails.join('\n');
        toast.success(`Imported ${data.count} email(s).`);
    } else { toastApiError(await apiErrorFromResponse(res), 'The email import failed.'); }
}

async function buildRecipients(id) {
    const sources = Array.from(document.querySelectorAll(`.aud[data-c="${id}"]:checked`)).map(c => c.value);
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/build_recipients/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ sources, manual_emails: _manualEmails(id) }),
    });
    const data = await res.json();
    if (res.ok) { toast.success(`${data.count} recipient(s) ready.`); loadCampaigns(); }
    else { toast.error(data.detail || 'The recipient list could not be built.'); }
}

async function queueCampaign(id) {
    if (!await tkConfirm('Queued campaigns begin sending on the next outbox run.', { title: 'Queue this campaign?', confirmText: 'Queue' })) return;
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/queue/`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    const data = await res.json();
    if (res.ok) { toast.success('Queued. Sending begins shortly.'); loadCampaigns(); }
    else { toast.error(data.detail || 'The campaign could not be queued.'); }
}

async function pauseCampaign(id) {
    if (!await tkConfirm('In-flight sending stops before the next email.', { title: 'Pause this campaign?', confirmText: 'Pause' })) return;
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/pause/`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    const data = await res.json();
    if (res.ok) { toast.success('Campaign paused.'); loadCampaigns(); }
    else { toast.error(data.detail || 'The campaign could not be paused.'); }
}

async function resumeCampaign(id) {
    if (!await tkConfirm('Sending resumes from where it stopped.', { title: 'Resume this campaign?', confirmText: 'Resume' })) return;
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/resume/`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    const data = await res.json();
    if (res.ok) { toast.success('Campaign resumed.'); loadCampaigns(); }
    else { toast.error(data.detail || 'The campaign could not be resumed.'); }
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addCampaignForm');
    if (form) form.addEventListener('submit', createCampaign);

    // Delegated listener: #campaignsList is a stable ancestor across
    // loadCampaigns() re-renders (only its innerHTML is replaced), so this
    // is registered once here rather than per-render, which would otherwise
    // stack duplicate handlers and fire the click multiple times.
    const campaignsList = document.getElementById('campaignsList');
    if (campaignsList) {
        campaignsList.addEventListener('click', (event) => {
            const btn = event.target.closest('[data-action="open-recipients"]');
            if (!btn) return;
            openRecipients(Number(btn.dataset.campaignId), btn.dataset.campaignName);
        });
    }
});
