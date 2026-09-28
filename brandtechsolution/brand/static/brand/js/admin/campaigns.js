// Campaigns: who gets a template, from which address, and when. The email
// itself is written under Templates; nothing here edits content.

const CAMPAIGN = {
    items: [],
    templates: [],
    overview: null,
    selectedId: null,
    filter: 'all',
    timer: null,
    // campaign id -> segment ids to tick in its audience step, when it was
    // started from a segment under Contacts.
    preselectSegments: {},
    pendingSegment: null,
};

const CAMPAIGN_STATUS_STYLE = {
    draft: 'text-gray-300 bg-white/5',
    scheduled: 'text-brand-blue bg-blue-900/20',
    queued: 'text-brand-blue bg-blue-900/20',
    sending: 'text-yellow-300 bg-yellow-900/20',
    paused: 'text-orange-300 bg-orange-900/20',
    sent: 'text-brand-green bg-green-900/20',
    failed: 'text-red-400 bg-red-900/20',
};

function _jsonPost(url, body) {
    return fetchJson(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify(body || {}),
    });
}

function _isScheduled(c) {
    return c.status === 'queued' && c.send_at && new Date(c.send_at) > new Date();
}

function _statusKey(c) {
    return _isScheduled(c) ? 'scheduled' : c.status;
}

function _statusLabel(c) {
    const key = _statusKey(c);
    return key.charAt(0).toUpperCase() + key.slice(1);
}

function _when(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString(undefined, {
        weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });
}

function _matchesFilter(c) {
    const key = _statusKey(c);
    switch (CAMPAIGN.filter) {
        case 'draft': return key === 'draft';
        case 'scheduled': return key === 'scheduled' || key === 'queued';
        case 'active': return key === 'sending' || key === 'paused';
        case 'done': return key === 'sent' || key === 'failed';
        default: return true;
    }
}

function _selected() {
    return CAMPAIGN.items.find(c => c.id === CAMPAIGN.selectedId) || null;
}

// --- loading ------------------------------------------------------------

async function loadCampaigns() {
    try {
        const [items, overview, templates] = await Promise.all([
            fetchJson(`${API_BASE}/messaging/campaigns/`),
            fetchJson(`${API_BASE}/messaging/campaigns/overview/`),
            fetchJson(`${API_BASE}/messaging/templates/`).catch(() => []),
        ]);
        CAMPAIGN.items = items;
        CAMPAIGN.overview = overview;
        CAMPAIGN.templates = templates;
    } catch (e) {
        toastApiError(e, 'Campaigns could not be loaded.');
        return;
    }
    renderCampaignMonth();
    renderCampaignList();
    renderCampaignDetail();
    _scheduleRefresh();
}

// While anything is queued or sending, keep the numbers moving without a
// reload. Drafts are never re-rendered by this, so typing is not disturbed.
function _scheduleRefresh() {
    clearTimeout(CAMPAIGN.timer);
    const live = CAMPAIGN.items.some(c => c.status === 'queued' || c.status === 'sending');
    if (!live) return;
    CAMPAIGN.timer = setTimeout(async () => {
        const section = document.getElementById('campaigns');
        if (!section || section.classList.contains('hidden')) return;
        try {
            CAMPAIGN.items = await fetchJson(`${API_BASE}/messaging/campaigns/`);
            CAMPAIGN.overview = await fetchJson(`${API_BASE}/messaging/campaigns/overview/`);
        } catch (e) { return; }
        renderCampaignMonth();
        renderCampaignList();
        const sel = _selected();
        if (sel && sel.status !== 'draft') renderCampaignDetail();
        _scheduleRefresh();
    }, 8000);
}

// --- header meter -------------------------------------------------------

function renderCampaignMonth() {
    const m = CAMPAIGN.overview && CAMPAIGN.overview.month;
    const box = document.getElementById('campaignMonth');
    if (!m || !box) return;
    box.classList.remove('hidden');
    const pct = v => `${m.cap ? Math.min(100, (v / m.cap) * 100) : 100}%`;
    document.getElementById('campaignMonthText').textContent = `${m.used.toLocaleString()} of ${m.cap.toLocaleString()}`;
    document.getElementById('campaignMonthUsed').style.width = pct(m.used);
    document.getElementById('campaignMonthBooked').style.width = pct(Math.min(m.committed, Math.max(m.cap - m.used, 0)));
    document.getElementById('campaignMonthNote').textContent = m.committed
        ? `${m.committed.toLocaleString()} booked by queued campaigns, ${m.headroom.toLocaleString()} free`
        : `${m.headroom.toLocaleString()} recipients free`;
}

// --- list ---------------------------------------------------------------

function renderCampaignList() {
    document.querySelectorAll('#campaignFilters .campaign-filter').forEach(btn => {
        const active = btn.dataset.filter === CAMPAIGN.filter;
        btn.className = `campaign-filter px-3 py-1 rounded-md text-xs font-medium ${active ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'}`;
    });
    const list = document.getElementById('campaignsList');
    const items = CAMPAIGN.items.filter(_matchesFilter);
    if (!items.length) {
        list.innerHTML = `<div class="text-center py-12 px-6 text-sm text-gray-500">${CAMPAIGN.items.length ? 'Nothing here.' : 'No campaigns yet. Start one from a template.'}</div>`;
        return;
    }
    list.innerHTML = items.map(c => {
        const key = _statusKey(c);
        let line = c.template_name ? escapeHtml(c.template_name) : 'Own content';
        if (key === 'scheduled') line = `Sends ${escapeHtml(_when(c.send_at))}`;
        if (key === 'sending' || key === 'paused') line = `${c.sent_count} of ${c.total} sent`;
        if (key === 'sent' || key === 'failed') line = `${c.sent_count} sent${c.stats.bounced ? `, ${c.stats.bounced} bounced` : ''}`;
        const active = c.id === CAMPAIGN.selectedId;
        return `<button type="button" data-campaign-id="${c.id}" class="w-full text-left px-4 py-3 ${active ? 'bg-white/[0.06]' : 'hover:bg-white/[0.03]'}">
            <div class="flex items-center justify-between gap-2">
                <span class="font-medium text-sm text-white truncate">${escapeHtml(c.name)}</span>
                <span class="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase shrink-0 ${CAMPAIGN_STATUS_STYLE[key] || ''}">${_statusLabel(c)}</span>
            </div>
            <div class="flex items-center justify-between gap-2 mt-1 text-xs text-gray-500">
                <span class="truncate">${line}</span>
                <span class="shrink-0">${c.total} recipient${c.total === 1 ? '' : 's'}</span>
            </div>
        </button>`;
    }).join('');
}

function selectCampaign(id) {
    CAMPAIGN.selectedId = id;
    renderCampaignList();
    renderCampaignDetail();
}

// --- detail -------------------------------------------------------------

function _card(title, body, step) {
    return `<section class="border border-dark-border rounded-xl">
        <header class="px-4 sm:px-5 py-3 border-b border-dark-border flex items-center gap-3">
            ${step ? `<span class="w-6 h-6 rounded-full bg-white/5 text-xs text-gray-300 flex items-center justify-center font-semibold">${step}</span>` : ''}
            <h4 class="text-sm font-semibold text-white">${title}</h4>
        </header>
        <div class="p-4 sm:p-5">${body}</div>
    </section>`;
}

function _stat(label, value, cls = 'text-white') {
    return `<div class="bg-white/[0.03] border border-white/5 rounded-lg px-4 py-3">
        <div class="text-xl font-bold ${cls}">${value}</div>
        <div class="text-xs text-gray-500 mt-0.5">${label}</div>
    </div>`;
}

function _senderOptions(selected) {
    const senders = (CAMPAIGN.overview && CAMPAIGN.overview.senders) || [];
    const opts = senders.map(s => `<option value="${escapeHtml(s.value)}" ${s.value === selected ? 'selected' : ''}>${escapeHtml(s.label)} &lt;${escapeHtml(s.address)}&gt;</option>`);
    if (selected && !senders.some(s => s.value === selected)) {
        opts.push(`<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)}</option>`);
    }
    return opts.join('');
}

function _templateOptions(selected) {
    const opts = CAMPAIGN.templates.map(t => `<option value="${t.id}" ${t.id === selected ? 'selected' : ''}>${escapeHtml(t.name)}</option>`);
    if (!selected) opts.unshift('<option value="">Choose a template</option>');
    return opts.join('');
}

function _emailSummary(c) {
    return `<dl class="grid grid-cols-[6rem_1fr] gap-y-2 text-sm">
        <dt class="text-gray-500">Template</dt><dd class="text-gray-200">${escapeHtml(c.template_name || 'Own content')}</dd>
        <dt class="text-gray-500">From</dt><dd class="text-gray-200 break-all">${escapeHtml(c.from_address)}</dd>
        <dt class="text-gray-500">Subject</dt><dd class="text-gray-200">${escapeHtml(c.subject)}</dd>
        ${c.audience && c.audience.length ? `<dt class="text-gray-500">Audience</dt><dd class="text-gray-200">${c.audience.map(escapeHtml).join(', ')}</dd>` : ''}
    </dl>`;
}

function _previewBlock() {
    return `<section class="border border-dark-border rounded-xl overflow-hidden">
        <header class="px-5 py-3 border-b border-dark-border flex items-center justify-between">
            <h4 class="text-sm font-semibold text-white">Email preview</h4>
            <span class="text-xs text-gray-500">Sample values fill the placeholders</span>
        </header>
        <iframe id="campaignPreviewFrame" title="Email preview" sandbox="" class="w-full h-[420px] bg-white block"></iframe>
    </section>`;
}

function _draftBody(c) {
    const canSend = CAMPAIGN.overview && CAMPAIGN.overview.can_send;
    const headroom = CAMPAIGN.overview ? CAMPAIGN.overview.month.headroom : 0;
    const email = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                <label class="block text-xs font-medium text-gray-400 mb-1.5" for="cdTemplate">Template</label>
                <div class="flex gap-2">
                    <select id="cdTemplate" class="flex-1 min-w-0 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-blue">${_templateOptions(c.template)}</select>
                    ${c.template ? `<button type="button" data-cd="edit-template" class="px-3 py-2 text-xs rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5 shrink-0">Edit</button>` : ''}
                </div>
            </div>
            <div>
                <label class="block text-xs font-medium text-gray-400 mb-1.5" for="cdFrom">Send from</label>
                <select id="cdFrom" class="w-full bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-blue">${_senderOptions(c.from_mailbox)}</select>
            </div>
        </div>
        <p class="text-sm text-gray-400 mt-4"><span class="text-gray-500">Subject:</span> ${escapeHtml(c.subject)}</p>
        <p class="text-xs text-gray-500 mt-1">Replies arrive in the sending mailbox in Mail. Edits to the template carry over until you queue.</p>`;

    const choices = (CAMPAIGN.overview && CAMPAIGN.overview.audience) || { everyone: 0, segments: [], origins: [] };
    const preselect = CAMPAIGN.preselectSegments[c.id] || [];
    const option = (kind, value, label, count, checked = false) => `
        <label class="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg border border-white/5 hover:border-white/15 cursor-pointer has-[:checked]:border-brand-green/50 has-[:checked]:bg-green-900/10">
            <span class="flex items-center gap-3 min-w-0"><input type="checkbox" class="cd-audience accent-[#10B981]" data-kind="${kind}" value="${escapeHtml(String(value))}" ${checked ? 'checked' : ''}>
            <span class="text-sm text-gray-200 truncate">${escapeHtml(label)}</span></span>
            <span class="text-xs text-gray-500 shrink-0">${count.toLocaleString()}</span>
        </label>`;
    const segmentList = choices.segments.length
        ? `<div class="grid grid-cols-1 sm:grid-cols-2 gap-2">${choices.segments.map(s => option('segment', s.id, s.name, s.count, preselect.includes(s.id))).join('')}</div>`
        : `<p class="text-sm text-gray-500">No segments yet. Group people under Contacts, such as Clients or Leads, and they show up here.</p>`;
    const origins = choices.origins.filter(o => o.count);
    const audience = `
        <div class="flex items-baseline justify-between gap-3 mb-4">
            <p class="text-sm text-gray-300"><span class="text-2xl font-bold text-white mr-1">${c.total.toLocaleString()}</span>recipient${c.total === 1 ? '' : 's'} so far</p>
            <button type="button" data-cd="recipients" class="shrink-0 whitespace-nowrap px-3 py-1.5 text-xs rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Review list</button>
        </div>
        ${c.audience && c.audience.length ? `<p class="text-xs text-gray-500 -mt-2 mb-4">Built from ${c.audience.map(a => `<span class="text-gray-300">${escapeHtml(a)}</span>`).join(', ')}</p>` : ''}
        <p class="text-xs font-medium text-gray-400 mb-2">Segments</p>
        ${segmentList}
        <details class="mt-4 group">
            <summary class="text-xs font-medium text-gray-400 cursor-pointer hover:text-white select-none">Everyone, or by where they came from</summary>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
                ${option('everyone', 1, 'Everyone in contacts', choices.everyone)}
                ${origins.map(o => option('origin', o.key, o.label, o.count)).join('')}
            </div>
        </details>
        <div class="flex flex-wrap items-center justify-between gap-3 mt-4">
            ${window.can && window.can('manage_recipients') ? `<button type="button" data-cd="contacts" class="text-xs text-gray-400 hover:text-white"><i class="fas fa-address-book mr-1.5"></i>Manage contacts and segments</button>` : '<span></span>'}
            <button type="button" data-cd="build" class="bg-white/10 hover:bg-white/15 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50">Add to audience</button>
        </div>
        <p class="text-xs text-gray-500 mt-3">Counts leave out people who unsubscribed or bounced, and so does the audience. Someone in two segments gets one email.</p>`;

    const fits = c.total <= headroom;
    const send = `
        <div class="flex flex-wrap items-center justify-between gap-3 pb-4 mb-4 border-b border-white/5">
            <p class="text-sm text-gray-400">Check it in a real inbox first. The test goes to your own address, marked [Test].</p>
            <button type="button" data-cd="test" class="px-4 py-2 text-sm rounded-lg border border-dark-border text-gray-200 hover:text-white hover:bg-white/5 disabled:opacity-50">Send me a test</button>
        </div>
        ${canSend ? `
        <fieldset class="space-y-2">
            <label class="flex items-center gap-2 text-sm text-gray-200"><input type="radio" name="cdWhen" value="now" checked class="accent-[#10B981]"> As soon as possible</label>
            <label class="flex items-center gap-2 text-sm text-gray-200 flex-wrap"><input type="radio" name="cdWhen" value="later" class="accent-[#10B981]"> At
                <input type="datetime-local" id="cdSendAt" class="bg-[#06090F] border border-dark-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-brand-blue [color-scheme:dark]"></label>
        </fieldset>
        <p class="text-xs mt-3 ${fits ? 'text-gray-500' : 'text-yellow-300'}">
            ${fits ? `Uses ${c.total.toLocaleString()} of the ${headroom.toLocaleString()} recipients left this month.`
                   : `This audience is larger than the ${headroom.toLocaleString()} recipients left this month. Trim it or raise the cap under Mail, Sending limits.`}
            Sending runs at about 50 a minute.
        </p>
        <div class="flex justify-end mt-4">
            <button type="button" data-cd="queue" class="bg-brand-green hover:bg-green-500 text-black font-semibold text-sm px-5 py-2.5 rounded-lg disabled:opacity-50" ${c.total && c.template ? '' : 'disabled'}>Queue campaign</button>
        </div>` : `<p class="text-sm text-gray-400">When it is ready, an administrator with the send permission queues it.</p>`}`;

    return `
        ${_card('The email', email, 1)}
        ${_card('Audience', audience, 2)}
        ${_card('Send', send, 3)}
        ${_previewBlock()}
        <div class="flex justify-end">
            <button type="button" data-cd="delete" class="text-xs text-gray-500 hover:text-red-400 px-3 py-2 rounded-lg hover:bg-red-900/10">Delete draft</button>
        </div>`;
}

function _liveBody(c) {
    const canSend = CAMPAIGN.overview && CAMPAIGN.overview.can_send;
    const key = _statusKey(c);
    const s = c.stats;
    const done = s.sent + s.failed + s.skipped;
    const pct = c.total ? Math.round((done / c.total) * 100) : 0;
    let banner = '';
    let actions = [];
    const notStarted = !c.started_at;

    if (key === 'scheduled') {
        banner = `Scheduled for <span class="text-white font-medium">${escapeHtml(_when(c.send_at))}</span>.`;
    } else if (key === 'queued') {
        banner = 'Queued. Sending starts within a minute.';
    } else if (key === 'sending') {
        banner = `Sending. ${s.pending.toLocaleString()} still to go, about ${Math.max(1, Math.ceil(s.pending / 50))} minute${Math.ceil(s.pending / 50) === 1 ? '' : 's'}.`;
    } else if (key === 'paused') {
        banner = c.note ? escapeHtml(c.note) : 'Paused. Nothing more is sent until it is resumed.';
    } else if (key === 'sent') {
        banner = `Finished ${escapeHtml(_when(c.completed_at))}.`;
    } else if (key === 'failed') {
        banner = 'Every send failed. Open the recipient list to see the errors.';
    }
    if (canSend) {
        if (key === 'scheduled' || key === 'queued' || key === 'sending') actions.push(['pause', 'Pause', 'border-orange-500/60 text-orange-300 hover:bg-orange-900/20']);
        if (key === 'paused') actions.push(['resume', 'Resume', 'bg-brand-green text-black font-semibold hover:bg-green-500 border-transparent']);
        if ((key === 'scheduled' || key === 'queued' || key === 'paused') && notStarted) actions.push(['unqueue', 'Back to draft', 'border-dark-border text-gray-300 hover:bg-white/5']);
    }

    const progress = (key === 'sending' || key === 'paused' || key === 'sent' || key === 'failed') ? `
        <div class="mt-4">
            <div class="flex justify-between text-xs text-gray-500 mb-1"><span>${done.toLocaleString()} of ${c.total.toLocaleString()} processed</span><span>${pct}%</span></div>
            <div class="h-2 rounded-full bg-white/5 overflow-hidden"><div class="h-full rounded-full bg-brand-green transition-all" style="width:${pct}%"></div></div>
        </div>` : '';

    const results = `
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-3">
            ${_stat('Sent', s.sent.toLocaleString(), 'text-brand-green')}
            ${_stat('Delivered', s.delivered.toLocaleString())}
            ${_stat('Bounced', s.bounced.toLocaleString(), s.bounced ? 'text-orange-300' : 'text-white')}
            ${_stat('Marked as spam', s.complained.toLocaleString(), s.complained ? 'text-red-400' : 'text-white')}
            ${_stat('Failed to send', s.failed.toLocaleString(), s.failed ? 'text-red-400' : 'text-white')}
            ${_stat('Skipped', s.skipped.toLocaleString(), 'text-gray-400')}
        </div>
        <p class="text-xs text-gray-500 mt-3">Delivered, bounced and spam figures come from Mailgun and can arrive a few minutes after sending. Bounced and complaining addresses are never emailed again.</p>`;

    return `
        <section class="border border-dark-border rounded-xl p-5">
            <div class="flex flex-wrap items-start justify-between gap-3">
                <p class="text-sm text-gray-300 flex-1 min-w-[12rem]">${banner}</p>
                <div class="flex gap-2">${actions.map(([a, label, cls]) => `<button type="button" data-cd="${a}" class="px-4 py-2 text-sm rounded-lg border ${cls} disabled:opacity-50">${label}</button>`).join('')}</div>
            </div>
            ${progress}
        </section>
        ${_card('Results', results)}
        ${_card('The email', _emailSummary(c))}
        ${_previewBlock()}`;
}

function renderCampaignDetail() {
    const pane = document.getElementById('campaignDetail');
    const listPane = document.getElementById('campaignListPane');
    const c = _selected();
    // Below lg the detail takes the whole card while a campaign is open;
    // from lg up both panes always show.
    listPane.classList.toggle('hidden', !!c);
    pane.classList.toggle('hidden', !c);
    if (!c) {
        pane.innerHTML = `<div class="h-full flex items-center justify-center p-10 text-center">
            <div><p class="text-gray-300 font-medium">Select a campaign</p>
            <p class="text-sm text-gray-500 mt-1">Or start a new one from a template.</p></div></div>`;
        return;
    }
    const key = _statusKey(c);
    pane.innerHTML = `
        <div class="p-3 sm:p-5 lg:p-6 space-y-5 max-w-4xl">
            <div class="flex items-start gap-3">
                <button type="button" data-cd="back" class="lg:hidden text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-white/5" aria-label="Back to campaigns"><i class="fas fa-arrow-left"></i></button>
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                        <h3 class="text-xl font-bold text-white truncate">${escapeHtml(c.name)}</h3>
                        <span class="text-[10px] font-bold px-1.5 py-0.5 rounded uppercase ${CAMPAIGN_STATUS_STYLE[key] || ''}">${_statusLabel(c)}</span>
                    </div>
                    <p class="text-xs text-gray-500 mt-1">Created ${escapeHtml(_when(c.created_at))}${c.created_by_name ? ` by ${escapeHtml(c.created_by_name)}` : ''}</p>
                </div>
                ${c.status !== 'draft' ? `<button type="button" data-cd="recipients" class="px-3 py-1.5 text-xs rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5 shrink-0">Recipients (${c.total})</button>` : ''}
            </div>
            ${c.status === 'draft' ? _draftBody(c) : _liveBody(c)}
        </div>`;
    _renderCampaignPreview(c);
}

async function _renderCampaignPreview(c) {
    const frame = document.getElementById('campaignPreviewFrame');
    if (!frame) return;
    try {
        const data = await _jsonPost(`${API_BASE}/messaging/preview/`, {
            subject: c.subject, body_source: c.body_source || c.body_html,
        });
        if (document.getElementById('campaignPreviewFrame') !== frame) return;
        frame.srcdoc =
            `<html><body style="margin:0;padding:16px;background:#ffffff;">` +
            `<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#6b7280;margin-bottom:12px;">` +
            `From: ${escapeHtml(c.from_address)}<br>Subject: ${escapeHtml(data.subject)}</div>${data.body_html}</body></html>`;
    } catch (e) { /* the preview is a convenience; the rest of the page works */ }
}

// --- actions ------------------------------------------------------------

function _replace(updated) {
    const i = CAMPAIGN.items.findIndex(c => c.id === updated.id);
    if (i >= 0) CAMPAIGN.items[i] = updated;
    else CAMPAIGN.items.unshift(updated);
}

async function _patchCampaign(c, data, okText) {
    try {
        _replace(await fetchJson(`${API_BASE}/messaging/campaigns/${c.id}/`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify(data),
        }));
        if (okText) toast.success(okText);
    } catch (e) { toastApiError(e, 'The campaign could not be changed.'); }
    renderCampaignList();
    renderCampaignDetail();
}

async function _busy(btn, work) {
    if (btn) btn.disabled = true;
    try { await work(); } finally { if (btn && btn.isConnected) btn.disabled = false; }
}

async function _campaignAction(action, btn) {
    const c = _selected();
    if (!c) return;
    const base = `${API_BASE}/messaging/campaigns/${c.id}`;

    if (action === 'back') { CAMPAIGN.selectedId = null; renderCampaignList(); renderCampaignDetail(); return; }
    if (action === 'recipients') { openRecipients(c.id, c.name); return; }
    if (action === 'edit-template') { window.editTemplateById && window.editTemplateById(c.template); return; }

    if (action === 'contacts') { showSection('contacts'); history.pushState(null, '', '/admin-panel/?section=contacts'); return; }

    if (action === 'build') {
        const ticked = kind => Array.from(document.querySelectorAll(`.cd-audience[data-kind="${kind}"]:checked`)).map(el => el.value);
        const body = {
            everyone: ticked('everyone').length > 0,
            segments: ticked('segment').map(Number),
            origins: ticked('origin'),
        };
        if (!body.everyone && !body.segments.length && !body.origins.length) { toast.error('Tick a segment first.'); return; }
        await _busy(btn, async () => {
            try {
                const data = await _jsonPost(`${base}/build_recipients/`, body);
                delete CAMPAIGN.preselectSegments[c.id];
                toast.success(`${data.count.toLocaleString()} recipient${data.count === 1 ? '' : 's'} in the audience.`);
                await loadCampaigns();
            } catch (e) { toastApiError(e, 'The audience could not be built.'); }
        });
        return;
    }

    if (action === 'test') {
        await _busy(btn, async () => {
            try {
                const data = await _jsonPost(`${base}/test/`);
                toast.success(`Test sent to ${data.to}.`);
            } catch (e) { toastApiError(e, 'The test could not be sent.'); }
        });
        return;
    }

    if (action === 'queue') {
        const later = document.querySelector('input[name="cdWhen"]:checked')?.value === 'later';
        let sendAt = null;
        if (later) {
            const raw = document.getElementById('cdSendAt').value;
            if (!raw) { toast.error('Choose the date and time to send.'); return; }
            const d = new Date(raw);
            if (d <= new Date()) { toast.error('That time has already passed.'); return; }
            sendAt = d.toISOString();
        }
        const message = sendAt
            ? `It goes to ${c.total.toLocaleString()} recipients on ${_when(sendAt)}. You can take it back to draft until then.`
            : `It goes to ${c.total.toLocaleString()} recipients, starting within a minute.`;
        if (!await tkConfirm(message, { title: sendAt ? 'Schedule this campaign?' : 'Send this campaign?', confirmText: sendAt ? 'Schedule' : 'Send' })) return;
        await _busy(btn, async () => {
            try {
                _replace(await _jsonPost(`${base}/queue/`, sendAt ? { send_at: sendAt } : {}));
                toast.success(sendAt ? 'Campaign scheduled.' : 'Campaign queued.');
                await loadCampaigns();
            } catch (e) { toastApiError(e, 'The campaign could not be queued.'); }
        });
        return;
    }

    if (action === 'unqueue') {
        await _busy(btn, async () => {
            try {
                _replace(await _jsonPost(`${base}/unqueue/`));
                toast.success('Back to draft.');
                await loadCampaigns();
            } catch (e) { toastApiError(e, 'The campaign could not go back to draft.'); }
        });
        return;
    }

    if (action === 'pause' || action === 'resume') {
        const pausing = action === 'pause';
        if (pausing && !await tkConfirm('Sending stops before the next email. Nothing already sent is recalled.', { title: 'Pause this campaign?', confirmText: 'Pause' })) return;
        await _busy(btn, async () => {
            try {
                await _jsonPost(`${base}/${action}/`);
                toast.success(pausing ? 'Campaign paused.' : 'Campaign resumed.');
                await loadCampaigns();
            } catch (e) { toastApiError(e, `The campaign could not be ${pausing ? 'paused' : 'resumed'}.`); }
        });
        return;
    }

    if (action === 'delete') {
        if (!await tkConfirm('The draft and its audience are removed. The template is kept.', { title: 'Delete this draft?', confirmText: 'Delete', danger: true })) return;
        try {
            await fetchJson(`${base}/`, { method: 'DELETE', headers: { 'X-CSRFToken': CSRF_TOKEN } });
            toast.success('Draft deleted.');
            CAMPAIGN.selectedId = null;
            await loadCampaigns();
        } catch (e) { toastApiError(e, 'The draft could not be deleted.'); }
    }
}

// --- new campaign -------------------------------------------------------

function openNewCampaign(templateId) {
    const modal = document.getElementById('campaignNewModal');
    const form = document.getElementById('addCampaignForm');
    form.reset();
    const sel = document.getElementById('campaignTemplate');
    sel.innerHTML = CAMPAIGN.templates.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join('');
    if (templateId) sel.value = String(templateId);
    document.getElementById('campaignNoTemplates').classList.toggle('hidden', CAMPAIGN.templates.length > 0);
    document.getElementById('campaignFrom').innerHTML = _senderOptions('hello');
    modal.classList.remove('hidden');
    document.getElementById('campaignName').focus();
}

function closeNewCampaign() {
    document.getElementById('campaignNewModal').classList.add('hidden');
}

async function createCampaign(event) {
    event.preventDefault();
    const form = event.target;
    const btn = form.querySelector('button[type="submit"]');
    await _busy(btn, async () => {
        try {
            const created = await _jsonPost(`${API_BASE}/messaging/campaigns/`, {
                name: form.name.value,
                template: Number(form.template.value),
                from_mailbox: form.from_mailbox.value,
            });
            closeNewCampaign();
            toast.success('Draft created. Now choose the audience.');
            if (CAMPAIGN.pendingSegment) CAMPAIGN.preselectSegments[created.id] = [CAMPAIGN.pendingSegment];
            CAMPAIGN.pendingSegment = null;
            CAMPAIGN.selectedId = created.id;
            CAMPAIGN.filter = 'all';
            await loadCampaigns();
        } catch (e) { toastApiError(e, 'The campaign could not be created.'); }
    });
}

// From the template gallery: open Campaigns with this template chosen.
window.startCampaignFrom = async function (templateId) {
    CAMPAIGN.pendingSegment = null;
    showSection('campaigns');
    await loadCampaigns();
    openNewCampaign(templateId);
};

// From a segment under Contacts: the new draft's audience step comes up
// with that segment already ticked.
window.startCampaignForSegment = async function (segmentId) {
    showSection('campaigns');
    history.pushState(null, '', '/admin-panel/?section=campaigns');
    await loadCampaigns();
    openNewCampaign();
    CAMPAIGN.pendingSegment = segmentId;
};

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('addCampaignForm');
    if (!form) return;
    form.addEventListener('submit', createCampaign);
    document.getElementById('campaignNewBtn').addEventListener('click', () => {
        CAMPAIGN.pendingSegment = null;
        openNewCampaign();
    });
    document.querySelectorAll('[data-close-new]').forEach(b => b.addEventListener('click', closeNewCampaign));

    document.getElementById('campaignFilters').addEventListener('click', (e) => {
        const btn = e.target.closest('.campaign-filter');
        if (!btn) return;
        CAMPAIGN.filter = btn.dataset.filter;
        renderCampaignList();
    });
    document.getElementById('campaignsList').addEventListener('click', (e) => {
        const btn = e.target.closest('[data-campaign-id]');
        if (btn) selectCampaign(Number(btn.dataset.campaignId));
    });

    // One delegated listener: the detail pane's contents are replaced on
    // every render, the pane itself is not.
    const detail = document.getElementById('campaignDetail');
    detail.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-cd]');
        if (btn) _campaignAction(btn.dataset.cd, btn);
    });
    detail.addEventListener('change', (e) => {
        const c = _selected();
        if (!c) return;
        if (e.target.id === 'cdTemplate' && e.target.value) _patchCampaign(c, { template: Number(e.target.value) }, 'Template changed.');
        if (e.target.id === 'cdFrom') _patchCampaign(c, { from_mailbox: e.target.value }, 'Sender changed.');
        if (e.target.id === 'cdSendAt') {
            const later = document.querySelector('input[name="cdWhen"][value="later"]');
            if (later) later.checked = true;
        }
    });
});
