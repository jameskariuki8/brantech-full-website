// Campaign recipients modal: inspect, search, add and remove the individual
// addresses a campaign will mail, and flag ones that look undeliverable.

const RECIPIENTS = { campaignId: null, page: 1, search: '', hasNext: false, hasPrev: false };
let RECIPIENTS_SEARCH_TIMER = null;

const VALIDITY_BADGE = {
    valid: { label: 'valid', cls: 'text-brand-green bg-green-900/20' },
    unknown: { label: 'unchecked', cls: 'text-gray-400 bg-white/5' },
    invalid_syntax: { label: 'malformed', cls: 'text-red-400 bg-red-900/20' },
    invalid_domain: { label: 'dead domain', cls: 'text-red-400 bg-red-900/20' },
};

const SEND_BADGE = {
    pending: 'text-gray-400 bg-white/5',
    sending: 'text-yellow-400 bg-yellow-900/20',
    sent: 'text-brand-green bg-green-900/20',
    failed: 'text-red-400 bg-red-900/20',
    skipped: 'text-orange-400 bg-orange-900/20',
};

function openRecipients(campaignId, campaignName) {
    RECIPIENTS.campaignId = campaignId;
    RECIPIENTS.page = 1;
    RECIPIENTS.search = '';
    document.getElementById('recipientsSearch').value = '';
    document.getElementById('recipientsSubtitle').textContent = campaignName || '';
    document.getElementById('recipientsSummary').classList.add('hidden');
    document.getElementById('recipientsModal').classList.remove('hidden');
    loadRecipients();
}

function closeRecipients() {
    document.getElementById('recipientsModal').classList.add('hidden');
    RECIPIENTS.campaignId = null;
    // Removals and additions move campaign.total, which the card displays.
    loadCampaigns();
}

async function loadRecipients() {
    if (!RECIPIENTS.campaignId) return;
    const params = new URLSearchParams({
        campaign: RECIPIENTS.campaignId,
        page: RECIPIENTS.page,
    });
    if (RECIPIENTS.search) params.set('search', RECIPIENTS.search);

    const res = await fetch(`${API_BASE}/messaging/recipients/?${params}`, { credentials: 'same-origin' });
    const container = document.getElementById('recipientsList');
    if (!res.ok) {
        container.innerHTML = `<div class="p-4 text-sm text-red-400">Could not load recipients.</div>`;
        return;
    }
    const data = await res.json();

    container.innerHTML = data.results.length ? data.results.map(r => {
        const validity = VALIDITY_BADGE[r.validation_status] || VALIDITY_BADGE.unknown;
        const sendCls = SEND_BADGE[r.status] || 'text-gray-400 bg-white/5';
        return `
        <div class="flex items-center justify-between gap-3 px-3 py-2">
            <div class="min-w-0">
                <p class="text-sm text-white truncate">${escapeHtml(r.email)}</p>
                ${r.name ? `<p class="text-xs text-gray-500 truncate">${escapeHtml(r.name)}</p>` : ''}
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <span class="text-[10px] font-bold px-2 py-0.5 rounded uppercase ${sendCls}">${escapeHtml(r.status)}</span>
                <span class="text-[10px] font-bold px-2 py-0.5 rounded uppercase ${validity.cls}">${validity.label}</span>
                <button type="button" onclick="removeRecipient(${r.id})"
                    class="text-gray-500 hover:text-red-400 px-2 py-1 rounded hover:bg-white/5"
                    aria-label="Remove recipient"><i class="fas fa-times"></i></button>
            </div>
        </div>`;
    }).join('') : `<div class="p-4 text-sm text-gray-600 text-center">No recipients match.</div>`;

    RECIPIENTS.hasNext = Boolean(data.next);
    RECIPIENTS.hasPrev = Boolean(data.previous);
    document.getElementById('recipientsPageInfo').textContent =
        `${data.count} recipient(s) · page ${RECIPIENTS.page}`;
    document.getElementById('recipientsPrev').disabled = !RECIPIENTS.hasPrev;
    document.getElementById('recipientsNext').disabled = !RECIPIENTS.hasNext;
    document.getElementById('recipientsPrev').classList.toggle('opacity-40', !RECIPIENTS.hasPrev);
    document.getElementById('recipientsNext').classList.toggle('opacity-40', !RECIPIENTS.hasNext);
}

function recipientsPage(delta) {
    if (delta > 0 && !RECIPIENTS.hasNext) return;
    if (delta < 0 && !RECIPIENTS.hasPrev) return;
    RECIPIENTS.page += delta;
    loadRecipients();
}

async function addRecipient(event) {
    event.preventDefault();
    const form = event.target;
    const res = await fetch(`${API_BASE}/messaging/recipients/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({
            campaign: RECIPIENTS.campaignId,
            email: form.email.value,
            name: form.name.value,
        }),
    });
    if (res.ok) { form.reset(); loadRecipients(); return; }
    const data = await res.json().catch(() => ({}));
    alert(data.detail || (data.email && data.email[0]) || 'Could not add that address.');
}

async function removeRecipient(id) {
    if (!confirm('Remove this address from the campaign?')) return;
    const res = await fetch(`${API_BASE}/messaging/recipients/${id}/`, {
        method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    if (res.ok) { loadRecipients(); return; }
    const data = await res.json().catch(() => ({}));
    alert(data.detail || 'Could not remove that address.');
}

async function checkRecipientDomains() {
    const summary = document.getElementById('recipientsSummary');
    summary.classList.remove('hidden');
    summary.textContent = 'Checking domains…';
    const res = await fetch(`${API_BASE}/messaging/recipients/validate/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ campaign: RECIPIENTS.campaignId }),
    });
    if (!res.ok) { summary.textContent = 'Domain check failed.'; return; }
    const c = await res.json();
    summary.textContent =
        `${c.valid} valid · ${c.invalid_domain} dead domain · ${c.invalid_syntax} malformed · ${c.unknown} unchecked`;
    loadRecipients();
}

async function removeInvalidRecipients() {
    if (!confirm('Remove every address flagged as malformed or dead-domain?')) return;
    const res = await fetch(`${API_BASE}/messaging/recipients/remove_invalid/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ campaign: RECIPIENTS.campaignId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { alert(data.detail || 'Could not remove flagged addresses.'); return; }
    const tail = data.skipped ? ` ${data.skipped} could not be withdrawn (already sent).` : '';
    alert(`Removed ${data.removed} address(es).${tail}`);
    RECIPIENTS.page = 1;
    loadRecipients();
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addRecipientForm');
    if (form) form.addEventListener('submit', addRecipient);

    const search = document.getElementById('recipientsSearch');
    if (search) {
        search.addEventListener('input', () => {
            clearTimeout(RECIPIENTS_SEARCH_TIMER);
            RECIPIENTS_SEARCH_TIMER = setTimeout(() => {
                RECIPIENTS.search = search.value.trim();
                RECIPIENTS.page = 1;
                loadRecipients();
            }, 250);
        });
    }
});
