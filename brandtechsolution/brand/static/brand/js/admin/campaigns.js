let TEMPLATE_CACHE = [];

async function loadCampaigns() {
    // Populate template dropdown
    TEMPLATE_CACHE = await fetch(`${API_BASE}/messaging/templates/`, { credentials: 'same-origin' }).then(r => r.json());
    const sel = document.getElementById('campaignTemplate');
    if (sel) sel.innerHTML = `<option value="">— none —</option>` + TEMPLATE_CACHE.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');

    const items = await fetch(`${API_BASE}/messaging/campaigns/`, { credentials: 'same-origin' }).then(r => r.json());
    const container = document.getElementById('campaignsList');
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
                    ${c.status === 'draft' ? `
                        <label class="text-xs text-gray-400">Audience:</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="inquiries"> Inquiries</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="users"> Users</label>
                        <label class="text-xs text-gray-300"><input type="checkbox" class="aud" data-c="${c.id}" value="appointments"> Appointments</label>
                        <textarea id="manual-${c.id}" placeholder="paste emails, comma/space separated" class="bg-[#06090F] border border-dark-border rounded px-2 py-1 text-xs text-white" rows="2"></textarea>
                        <input type="file" id="import-${c.id}" onchange="importEmails(event)" data-c="${c.id}" class="text-xs text-gray-400" accept=".csv,.txt,.xlsx,.pdf,.docx">
                        <button onclick="buildRecipients(${c.id})" class="bg-dark-card border border-dark-border hover:border-brand-blue text-white text-xs px-3 py-1.5 rounded">Build recipients</button>
                        <button onclick="queueCampaign(${c.id})" class="bg-brand-green hover:bg-green-500 text-black text-xs font-semibold px-3 py-1.5 rounded">Queue send (${c.total})</button>
                    ` : ``}
                </div>
            </div>
        </div>`).join('') : `<div class="text-center py-10 text-gray-600">No campaigns yet.</div>`;
}

function applyTemplate() {
    const id = document.getElementById('campaignTemplate').value;
    const t = TEMPLATE_CACHE.find(x => String(x.id) === String(id));
    const form = document.getElementById('addCampaignForm');
    if (t) { form.subject.value = t.subject; form.body_html.value = t.body_html; }
}

async function createCampaign(event) {
    event.preventDefault();
    const form = event.target;
    const payload = { name: form.name.value, subject: form.subject.value, body_html: form.body_html.value };
    const res = await fetch(`${API_BASE}/messaging/campaigns/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify(payload),
    });
    if (res.ok) { hideAddForm('campaign'); form.reset(); loadCampaigns(); } else { alert('Create failed'); }
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
        alert(`Imported ${data.count} email(s).`);
    } else { alert('Import failed'); }
}

async function buildRecipients(id) {
    const sources = Array.from(document.querySelectorAll(`.aud[data-c="${id}"]:checked`)).map(c => c.value);
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/build_recipients/`, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ sources, manual_emails: _manualEmails(id) }),
    });
    const data = await res.json();
    if (res.ok) { alert(`${data.count} recipient(s) ready.`); loadCampaigns(); } else { alert(data.detail || 'Failed'); }
}

async function queueCampaign(id) {
    if (!confirm('Queue this campaign for sending?')) return;
    const res = await fetch(`${API_BASE}/messaging/campaigns/${id}/queue/`, {
        method: 'POST', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    const data = await res.json();
    if (res.ok) { alert('Queued! Sending will begin shortly.'); loadCampaigns(); } else { alert(data.detail || 'Failed'); }
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addCampaignForm');
    if (form) form.addEventListener('submit', createCampaign);
});
