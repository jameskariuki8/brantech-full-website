// Contacts: everyone outside the company we may email, grouped into
// segments that campaigns send to. The left list picks a view (all, a
// segment, where people came from); the table shows the people in it.

const CONTACTS = {
    summary: null,
    view: 'all',
    q: '',
    page: 1,
    count: 0,
    items: [],
    selected: new Set(),
    allMatching: false,
    searchTimer: null,
    editing: null,
};

const CONTACT_STATUS_STYLE = {
    subscribed: 'text-gray-400',
    unsubscribed: 'text-orange-300',
    manual: 'text-orange-300',
    bounced: 'text-red-400',
    complained: 'text-red-400',
};

const CONTACT_VIEW_NOTES = {
    all: 'Unsubscribed and bounced people stay listed so you know who they are, but they are never emailed.',
    none: 'People who are not in any segment yet.',
    unsub: 'Unsubscribed, bounced, marked the email as spam, or stopped by staff. Campaigns skip them.',
    'src:inquiry': 'Added automatically when someone uses the contact form.',
    'src:appointment': 'Added automatically when someone books a call.',
    'src:account': 'Added automatically when a customer creates an account.',
    'src:import': 'Brought in from a file or a pasted list.',
    'src:manual': 'Added one at a time from this page.',
};

function _contactJson(url, method, body) {
    return fetchJson(url, {
        method,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify(body || {}),
    });
}

function _segments() {
    return (CONTACTS.summary && CONTACTS.summary.segments) || [];
}

function _viewSegment() {
    return CONTACTS.view.startsWith('seg:')
        ? _segments().find(s => String(s.id) === CONTACTS.view.slice(4)) || null
        : null;
}

function _contactFilters() {
    const v = CONTACTS.view;
    const f = {};
    if (v === 'none') f.segment = 'none';
    else if (v === 'unsub') f.status = 'unsubscribed';
    else if (v.startsWith('seg:')) f.segment = v.slice(4);
    else if (v.startsWith('src:')) f.source = v.slice(4);
    if (CONTACTS.q) f.q = CONTACTS.q;
    return f;
}

// --- loading ------------------------------------------------------------

async function loadContacts() {
    await Promise.all([loadContactSummary(), loadContactPage()]);
}

async function loadContactSummary() {
    try {
        CONTACTS.summary = await fetchJson(`${API_BASE}/messaging/contacts/summary/`);
    } catch (e) {
        toastApiError(e, 'Contacts could not be loaded.');
        return;
    }
    // A segment deleted elsewhere: fall back to everyone.
    if (CONTACTS.view.startsWith('seg:') && !_viewSegment()) {
        CONTACTS.view = 'all';
        CONTACTS.page = 1;
        loadContactPage();
    }
    renderContactViews();
    renderContactHeader();
}

async function loadContactPage() {
    const params = new URLSearchParams({ ..._contactFilters(), page: CONTACTS.page });
    let data;
    try {
        data = await fetchJson(`${API_BASE}/messaging/contacts/?${params}`);
    } catch (e) {
        if (CONTACTS.page > 1) { CONTACTS.page = 1; return loadContactPage(); }
        toastApiError(e, 'Contacts could not be loaded.');
        return;
    }
    CONTACTS.items = data.results;
    CONTACTS.count = data.count;
    renderContactRows();
    renderContactBulkBar();
}

function _switchView(view) {
    CONTACTS.view = view;
    CONTACTS.page = 1;
    CONTACTS.selected.clear();
    CONTACTS.allMatching = false;
    renderContactViews();
    renderContactHeader();
    loadContactPage();
}

// --- left list ----------------------------------------------------------

function _viewButton(view, label, count, extra = '') {
    const active = CONTACTS.view === view;
    return `<div class="group flex items-center rounded-lg ${active ? 'bg-white/[0.07] text-white' : 'text-gray-400 hover:bg-white/[0.03] hover:text-white'}">
        <button type="button" data-contact-view="${escapeHtml(view)}" class="flex-1 min-w-0 flex items-center justify-between gap-2 px-3 py-2 text-left">
            <span class="truncate">${escapeHtml(label)}</span>
            <span class="text-xs ${active ? 'text-gray-300' : 'text-gray-600'}">${(count || 0).toLocaleString()}</span>
        </button>${extra}
    </div>`;
}

function _heading(text, extra = '') {
    return `<div class="flex items-center justify-between px-3 pt-4 pb-1.5">
        <span class="text-[11px] font-semibold uppercase tracking-wider text-gray-600">${text}</span>${extra}
    </div>`;
}

function renderContactViews() {
    const s = CONTACTS.summary;
    const box = document.getElementById('contactViews');
    if (!s || !box) return;
    const segments = s.segments.length
        ? s.segments.map(seg => _viewButton(`seg:${seg.id}`, seg.name, seg.count)).join('')
        : `<p class="px-3 py-2 text-xs text-gray-500">None yet. Make one for each kind of person you email, such as Clients or Leads.</p>`;
    box.innerHTML = `
        ${_viewButton('all', 'All contacts', s.total)}
        ${_viewButton('none', 'Not in a segment', s.unsegmented)}
        ${_viewButton('unsub', 'Not emailed', s.unsubscribed)}
        ${_heading('Segments', `<button type="button" data-contact-act="new-segment" class="text-gray-500 hover:text-white text-xs px-1.5 py-0.5 rounded hover:bg-white/5" title="New segment" aria-label="New segment"><i class="fas fa-plus"></i></button>`)}
        ${segments}
        ${_heading('Came from')}
        ${s.origins.map(o => _viewButton(`src:${o.key}`, o.label, o.count)).join('')}`;
}

function renderContactHeader() {
    const seg = _viewSegment();
    const s = CONTACTS.summary;
    let title = 'All contacts';
    let note = CONTACT_VIEW_NOTES[CONTACTS.view] || '';
    if (CONTACTS.view === 'none') title = 'Not in a segment';
    if (CONTACTS.view === 'unsub') title = 'Not emailed';
    if (CONTACTS.view.startsWith('src:') && s) {
        const origin = s.origins.find(o => `src:${o.key}` === CONTACTS.view);
        title = origin ? origin.label : title;
    }
    if (seg) {
        title = seg.name;
        note = seg.description || 'A segment. Tick people anywhere in contacts and use Add to segment to put them here.';
    }
    document.getElementById('contactViewTitle').textContent = title;
    document.getElementById('contactViewNote').textContent = note;

    const actions = [];
    if (seg) {
        if (typeof window.startCampaignForSegment === 'function' && window.can && window.can('manage_campaigns')) {
            actions.push(`<button type="button" data-contact-act="campaign-segment" class="px-3 py-1.5 text-xs rounded-lg bg-brand-green/10 text-brand-green hover:bg-brand-green/20">Email this segment</button>`);
        }
        actions.push(`<button type="button" data-contact-act="rename-segment" class="px-3 py-1.5 text-xs rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Rename</button>`);
        actions.push(`<button type="button" data-contact-act="delete-segment" class="px-3 py-1.5 text-xs rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-900/10">Delete</button>`);
    }
    document.getElementById('contactViewActions').innerHTML = actions.join('');
}

// --- table --------------------------------------------------------------

function _segmentChips(ids) {
    const byId = Object.fromEntries(_segments().map(s => [s.id, s.name]));
    return ids.map(id => byId[id]).filter(Boolean)
        .map(name => `<span class="inline-block text-[11px] px-2 py-0.5 rounded-full bg-white/5 text-gray-300 mr-1 mb-1">${escapeHtml(name)}</span>`)
        .join('');
}

function renderContactRows() {
    const body = document.getElementById('contactsBody');
    const checkAll = document.getElementById('contactCheckAll');
    if (!CONTACTS.items.length) {
        const empty = CONTACTS.q
            ? 'Nobody matches that search.'
            : CONTACTS.view === 'all'
                ? 'No contacts yet. They appear here as people use the contact form or book a call, or you can import a list.'
                : 'Nobody here yet.';
        body.innerHTML = `<tr><td colspan="5" class="px-5 py-14 text-center text-sm text-gray-500">${empty}</td></tr>`;
        checkAll.checked = false;
    } else {
        body.innerHTML = CONTACTS.items.map(c => {
            const checked = CONTACTS.allMatching || CONTACTS.selected.has(c.id);
            return `<tr data-contact-id="${c.id}" class="cursor-pointer hover:bg-white/[0.03] ${checked ? 'bg-brand-blue/5' : ''}">
                <td class="pl-5 pr-2 py-3"><input type="checkbox" class="contact-check accent-[#007AFF]" value="${c.id}" ${checked ? 'checked' : ''} aria-label="Select ${escapeHtml(c.email)}"></td>
                <td class="px-3 py-3 min-w-0">
                    <div class="text-white font-medium truncate max-w-[18rem]">${escapeHtml(c.name || c.email)}</div>
                    <div class="text-xs text-gray-500 truncate max-w-[18rem]">${c.name ? escapeHtml(c.email) : ''}${c.company ? `${c.name ? ' &middot; ' : ''}${escapeHtml(c.company)}` : ''}</div>
                </td>
                <td class="px-3 py-3 hidden md:table-cell">${_segmentChips(c.segments) || '<span class="text-xs text-gray-600">None</span>'}</td>
                <td class="px-3 py-3 hidden xl:table-cell text-xs text-gray-400">${escapeHtml(c.source_label)}<div class="text-gray-600">${escapeHtml(_ago(c.created_at))}</div></td>
                <td class="px-3 py-3 text-xs whitespace-nowrap ${CONTACT_STATUS_STYLE[c.status] || 'text-orange-300'}">${escapeHtml(c.status_label)}</td>
            </tr>`;
        }).join('');
        checkAll.checked = CONTACTS.allMatching || CONTACTS.items.every(c => CONTACTS.selected.has(c.id));
    }
    const start = CONTACTS.count ? (CONTACTS.page - 1) * 50 + 1 : 0;
    const end = (CONTACTS.page - 1) * 50 + CONTACTS.items.length;
    document.getElementById('contactPageInfo').textContent = CONTACTS.count
        ? `${start.toLocaleString()} to ${end.toLocaleString()} of ${CONTACTS.count.toLocaleString()}`
        : '';
    document.getElementById('contactPrev').disabled = CONTACTS.page <= 1;
    document.getElementById('contactNext').disabled = end >= CONTACTS.count;
}

function _selectionSize() {
    return CONTACTS.allMatching ? CONTACTS.count : CONTACTS.selected.size;
}

function renderContactBulkBar() {
    const bar = document.getElementById('contactBulkBar');
    const n = _selectionSize();
    bar.classList.toggle('hidden', n === 0);
    if (!n) { bar.innerHTML = ''; return; }
    const pageAllTicked = CONTACTS.items.length && CONTACTS.items.every(c => CONTACTS.selected.has(c.id));
    const offerAll = !CONTACTS.allMatching && pageAllTicked && CONTACTS.count > CONTACTS.items.length;
    const seg = _viewSegment();
    const addOptions = _segments().filter(s => !seg || s.id !== seg.id)
        .map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
    bar.innerHTML = `
        <span class="text-white font-medium">${n.toLocaleString()} selected</span>
        ${offerAll ? `<button type="button" data-contact-act="select-all-matching" class="text-brand-blue hover:underline text-xs">Select all ${CONTACTS.count.toLocaleString()}</button>` : ''}
        <button type="button" data-contact-act="clear-selection" class="text-gray-500 hover:text-white text-xs">Clear</button>
        <span class="flex-1"></span>
        <select id="contactBulkSegment" class="bg-[#06090F] border border-dark-border rounded-lg px-2 py-1.5 text-xs text-gray-200">
            <option value="">Add to segment</option>${addOptions}<option value="__new">New segment...</option>
        </select>
        ${seg ? `<button type="button" data-contact-act="bulk-remove-segment" class="px-3 py-1.5 text-xs rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Remove from ${escapeHtml(seg.name)}</button>` : ''}
        <button type="button" data-contact-act="bulk-unsubscribe" class="px-3 py-1.5 text-xs rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Stop emailing</button>
        <button type="button" data-contact-act="bulk-delete" class="px-3 py-1.5 text-xs rounded-lg text-gray-500 hover:text-red-400 hover:bg-red-900/10">Delete</button>`;
}

async function _bulk(action, extra = {}) {
    const body = CONTACTS.allMatching
        ? { action, all_matching: true, filters: _contactFilters(), ...extra }
        : { action, ids: Array.from(CONTACTS.selected), ...extra };
    const data = await _contactJson(`${API_BASE}/messaging/contacts/bulk/`, 'POST', body);
    CONTACTS.selected.clear();
    CONTACTS.allMatching = false;
    await loadContacts();
    return data.count;
}

async function _bulkAddToSegment(select) {
    let segmentId = select.value;
    select.value = '';
    if (!segmentId) return;
    try {
        if (segmentId === '__new') {
            const seg = await openSegmentModal(null);
            if (!seg) return;
            segmentId = seg.id;
        }
        const name = (_segments().find(s => String(s.id) === String(segmentId)) || {}).name || 'the segment';
        const n = await _bulk('add_segment', { segment: Number(segmentId) });
        toast.success(`${n.toLocaleString()} added to ${name}.`);
    } catch (e) { toastApiError(e, 'They could not be added to the segment.'); }
}

async function _contactAct(act) {
    const n = _selectionSize();
    const seg = _viewSegment();
    try {
        if (act === 'new-segment') {
            const created = await openSegmentModal(null);
            if (created) _switchView(`seg:${created.id}`);
        } else if (act === 'rename-segment' && seg) {
            await openSegmentModal(seg);
        } else if (act === 'delete-segment' && seg) {
            const ok = await tkConfirm(`The ${seg.count.toLocaleString()} people in it stay in contacts. Campaigns already built from it keep their recipients.`,
                { title: `Delete the ${seg.name} segment?`, confirmText: 'Delete', danger: true });
            if (!ok) return;
            await fetchJson(`${API_BASE}/messaging/segments/${seg.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': CSRF_TOKEN } });
            toast.success('Segment deleted.');
            CONTACTS.view = 'all';
            CONTACTS.page = 1;
            await loadContacts();
        } else if (act === 'campaign-segment' && seg) {
            window.startCampaignForSegment(seg.id);
        } else if (act === 'select-all-matching') {
            CONTACTS.allMatching = true;
            renderContactRows();
            renderContactBulkBar();
        } else if (act === 'clear-selection') {
            CONTACTS.selected.clear();
            CONTACTS.allMatching = false;
            renderContactRows();
            renderContactBulkBar();
        } else if (act === 'bulk-remove-segment' && seg) {
            const count = await _bulk('remove_segment', { segment: seg.id });
            toast.success(`${count.toLocaleString()} removed from ${seg.name}.`);
        } else if (act === 'bulk-unsubscribe') {
            const ok = await tkConfirm('Campaigns will skip them from now on. You can allow emails again from each contact.',
                { title: `Stop emailing ${n.toLocaleString()} ${n === 1 ? 'person' : 'people'}?`, confirmText: 'Stop emailing' });
            if (!ok) return;
            await _bulk('unsubscribe');
            toast.success('They will not be emailed.');
        } else if (act === 'bulk-delete') {
            const ok = await tkConfirm('They are removed from contacts and every segment. Anyone who uses the contact form or books again comes back automatically. Unsubscribes are kept.',
                { title: `Delete ${n.toLocaleString()} contact${n === 1 ? '' : 's'}?`, confirmText: 'Delete', danger: true });
            if (!ok) return;
            await _bulk('delete');
            toast.success('Deleted.');
        }
    } catch (e) { toastApiError(e, 'That did not work.'); }
}

// --- one contact --------------------------------------------------------

function _segmentPicker(containerId, name, chosen) {
    const box = document.getElementById(containerId);
    const segs = _segments();
    box.innerHTML = segs.length ? segs.map(s => `
        <label class="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-white/10 text-sm text-gray-200 cursor-pointer hover:border-white/25 has-[:checked]:border-brand-blue has-[:checked]:bg-brand-blue/10">
            <input type="checkbox" name="${name}" value="${s.id}" class="accent-[#007AFF]" ${chosen.includes(s.id) ? 'checked' : ''}>${escapeHtml(s.name)}
        </label>`).join('')
        : '<p class="text-xs text-gray-500">No segments yet.</p>';
}

function openContactModal(c) {
    CONTACTS.editing = c;
    const form = document.getElementById('contactForm');
    form.reset();
    form.id.value = c ? c.id : '';
    form.email.value = c ? c.email : '';
    form.name.value = c ? c.name : '';
    form.company.value = c ? c.company : '';
    form.phone.value = c ? c.phone : '';
    form.notes.value = c ? c.notes : '';
    const seg = _viewSegment();
    _segmentPicker('contactFormSegments', 'segments', c ? c.segments : (seg ? [seg.id] : []));
    document.getElementById('contactFormTitle').textContent = c ? (c.name || c.email) : 'New contact';
    document.getElementById('contactFormMeta').textContent = c ? `${c.source_label}, added ${_ago(c.created_at)}` : '';
    document.getElementById('contactDeleteBtn').classList.toggle('hidden', !c);

    const status = document.getElementById('contactFormStatus');
    const stop = document.getElementById('contactStopBtn');
    const off = c && c.status !== 'subscribed';
    status.classList.toggle('hidden', !off);
    if (off) {
        status.className = 'text-xs rounded-lg px-3 py-2 text-orange-200 bg-orange-900/20 border border-orange-900/40';
        status.textContent = c.status === 'manual'
            ? 'Staff stopped emails to this person. Campaigns skip them.'
            : `${c.status_label}. Campaigns skip this address, and only they can change that.`;
    }
    stop.classList.toggle('hidden', !c || (off && c.status !== 'manual'));
    stop.textContent = c && c.status === 'manual' ? 'Allow emails again' : 'Stop emailing';
    document.getElementById('contactModal').classList.remove('hidden');
    (c ? form.name : form.email).focus();
}

function closeContactModal() {
    document.getElementById('contactModal').classList.add('hidden');
    CONTACTS.editing = null;
}

async function saveContact(event) {
    event.preventDefault();
    const form = event.target;
    const id = form.id.value;
    const payload = {
        email: form.email.value,
        name: form.name.value,
        company: form.company.value,
        phone: form.phone.value,
        notes: form.notes.value,
        segments: Array.from(form.querySelectorAll('input[name="segments"]:checked')).map(el => Number(el.value)),
    };
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
        await _contactJson(id ? `${API_BASE}/messaging/contacts/${id}/` : `${API_BASE}/messaging/contacts/`, id ? 'PATCH' : 'POST', payload);
        toast.success(id ? 'Contact saved.' : 'Contact added.');
        closeContactModal();
        await loadContacts();
    } catch (e) {
        toastApiError(e, 'The contact could not be saved.');
    } finally { btn.disabled = false; }
}

async function _contactSelfAction(which) {
    const c = CONTACTS.editing;
    if (!c) return;
    try {
        if (which === 'delete') {
            const ok = await tkConfirm('They are removed from contacts and every segment. If they unsubscribed, that is kept.',
                { title: 'Delete this contact?', confirmText: 'Delete', danger: true });
            if (!ok) return;
            await fetchJson(`${API_BASE}/messaging/contacts/${c.id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': CSRF_TOKEN } });
            toast.success('Contact deleted.');
        } else {
            const action = c.status === 'manual' ? 'resubscribe' : 'unsubscribe';
            await _contactJson(`${API_BASE}/messaging/contacts/bulk/`, 'POST', { action, ids: [c.id] });
            toast.success(action === 'resubscribe' ? 'They will be emailed again.' : 'They will not be emailed.');
        }
        closeContactModal();
        await loadContacts();
    } catch (e) { toastApiError(e, 'That did not work.'); }
}

// --- segments -----------------------------------------------------------

let _segmentResolve = null;

// Resolves with the saved segment, or null if the dialog is closed.
function openSegmentModal(seg) {
    const form = document.getElementById('segmentForm');
    form.reset();
    form.id.value = seg ? seg.id : '';
    form.name.value = seg ? seg.name : '';
    form.description.value = seg ? seg.description : '';
    document.getElementById('segmentFormTitle').textContent = seg ? 'Rename segment' : 'New segment';
    document.getElementById('segmentModal').classList.remove('hidden');
    form.name.focus();
    return new Promise(resolve => { _segmentResolve = resolve; });
}

function closeSegmentModal(result = null) {
    document.getElementById('segmentModal').classList.add('hidden');
    if (_segmentResolve) { _segmentResolve(result); _segmentResolve = null; }
}

async function saveSegment(event) {
    event.preventDefault();
    const form = event.target;
    const id = form.id.value;
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
        const saved = await _contactJson(
            id ? `${API_BASE}/messaging/segments/${id}/` : `${API_BASE}/messaging/segments/`,
            id ? 'PATCH' : 'POST',
            { name: form.name.value, description: form.description.value },
        );
        toast.success(id ? 'Segment saved.' : `${saved.name} created.`);
        await loadContactSummary();
        closeSegmentModal(saved);
    } catch (e) {
        toastApiError(e, 'The segment could not be saved.');
    } finally { btn.disabled = false; }
}

// --- import -------------------------------------------------------------

function openContactImport() {
    const form = document.getElementById('contactImportForm');
    form.reset();
    const seg = _viewSegment();
    _segmentPicker('contactImportSegments', 'segments', seg ? [seg.id] : []);
    document.getElementById('contactImportModal').classList.remove('hidden');
}

function closeContactImport() {
    document.getElementById('contactImportModal').classList.add('hidden');
}

async function importContacts(event) {
    event.preventDefault();
    const form = event.target;
    const file = form.file.files[0];
    if (!file && !form.text.value.trim()) { toast.error('Choose a file or paste some addresses.'); return; }
    const fd = new FormData();
    if (file) fd.append('file', file); else fd.append('text', form.text.value);
    form.querySelectorAll('input[name="segments"]:checked').forEach(el => fd.append('segments', el.value));
    if (form.new_segment.value.trim()) fd.append('new_segment', form.new_segment.value.trim());
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    try {
        const r = await fetchJson(`${API_BASE}/messaging/contacts/import/`, {
            method: 'POST', headers: { 'X-CSRFToken': CSRF_TOKEN }, body: fd,
        });
        const parts = [`${r.created.toLocaleString()} new`];
        if (r.existing) parts.push(`${r.existing.toLocaleString()} already in contacts`);
        if (r.skipped) parts.push(`${r.skipped.toLocaleString()} skipped`);
        toast.success(`Imported: ${parts.join(', ')}.`);
        closeContactImport();
        await loadContacts();
    } catch (e) {
        toastApiError(e, 'The import failed.');
    } finally { btn.disabled = false; }
}

// --- wiring -------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('contacts');
    if (!section) return;

    document.getElementById('contactNewBtn').addEventListener('click', () => openContactModal(null));
    document.getElementById('contactImportBtn').addEventListener('click', openContactImport);
    document.getElementById('contactForm').addEventListener('submit', saveContact);
    document.getElementById('contactImportForm').addEventListener('submit', importContacts);
    document.getElementById('segmentForm').addEventListener('submit', saveSegment);
    document.getElementById('contactDeleteBtn').addEventListener('click', () => _contactSelfAction('delete'));
    document.getElementById('contactStopBtn').addEventListener('click', () => _contactSelfAction('toggle'));
    section.querySelectorAll('[data-close-contact]').forEach(b => b.addEventListener('click', closeContactModal));
    section.querySelectorAll('[data-close-import]').forEach(b => b.addEventListener('click', closeContactImport));
    section.querySelectorAll('[data-close-segment]').forEach(b => b.addEventListener('click', () => closeSegmentModal(null)));

    document.getElementById('contactPrev').addEventListener('click', () => { CONTACTS.page -= 1; loadContactPage(); });
    document.getElementById('contactNext').addEventListener('click', () => { CONTACTS.page += 1; loadContactPage(); });

    document.getElementById('contactSearch').addEventListener('input', (e) => {
        clearTimeout(CONTACTS.searchTimer);
        CONTACTS.searchTimer = setTimeout(() => {
            CONTACTS.q = e.target.value.trim();
            CONTACTS.page = 1;
            CONTACTS.selected.clear();
            CONTACTS.allMatching = false;
            loadContactPage();
        }, 300);
    });

    section.addEventListener('click', (e) => {
        const view = e.target.closest('[data-contact-view]');
        if (view) { _switchView(view.dataset.contactView); return; }
        const act = e.target.closest('[data-contact-act]');
        if (act) { _contactAct(act.dataset.contactAct); return; }
        if (e.target.closest('.contact-check') || e.target.id === 'contactCheckAll') return;
        const row = e.target.closest('[data-contact-id]');
        if (row) openContactModal(CONTACTS.items.find(c => c.id === Number(row.dataset.contactId)));
    });

    section.addEventListener('change', (e) => {
        if (e.target.classList.contains('contact-check')) {
            const id = Number(e.target.value);
            if (CONTACTS.allMatching) {
                // Unticking one row out of "all matching" falls back to this page.
                CONTACTS.allMatching = false;
                CONTACTS.items.forEach(c => CONTACTS.selected.add(c.id));
            }
            if (e.target.checked) CONTACTS.selected.add(id); else CONTACTS.selected.delete(id);
            renderContactRows();
            renderContactBulkBar();
        } else if (e.target.id === 'contactCheckAll') {
            CONTACTS.allMatching = false;
            CONTACTS.items.forEach(c => e.target.checked ? CONTACTS.selected.add(c.id) : CONTACTS.selected.delete(c.id));
            renderContactRows();
            renderContactBulkBar();
        } else if (e.target.id === 'contactBulkSegment') {
            _bulkAddToSegment(e.target);
        }
    });
});
