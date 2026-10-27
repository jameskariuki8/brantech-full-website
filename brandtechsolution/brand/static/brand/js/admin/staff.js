// Staff & Groups section. A group is an auth.Group, which the API still
// calls a role, so identifiers below keep the word "role".
//
// Two rules hold everywhere in this file:
//   1. Every value that comes back from the API goes through escapeHtml()
//      before it is interpolated into markup.
//   2. No JavaScript is ever built inside an HTML on* attribute. Attribute
//      entity-decoding happens before JS compilation, so a quote in a role
//      name would break out of the handler. Rows carry data-* attributes and
//      a single delegated listener on #staff reads them.
//
// The staff APIs paginate (StaffPagination, page_size 50), so list responses
// are {count, next, previous, results} and are read via .results.
const STAFF_API = '/api/staff';
let CAPABILITY_GROUPS = [];
let ROLES = [];
// Shared mailboxes, for the group editor and the list under the groups.
const MAIL_SHARED_API = '/api/messaging/mail/shared';
let MAILBOXES = [];

async function apiFetch(url, options = {}) {
    const response = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
        ...options,
    });
    if (!response.ok) {
        let detail = 'Request failed';
        try {
            const body = await response.json();
            // DRF field errors arrive as {"field": ["message", ...]}; show
            // the messages rather than the JSON.
            detail = typeof body === 'string' ? body
                : (body.detail || Object.values(body).flat().join(' ') || 'Request failed');
        } catch (e) { /* response had no JSON body */ }
        throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
}

async function staffFetch(path, options = {}) {
    return apiFetch(`${STAFF_API}${path}`, options);
}

// DRF returns `next` as an absolute URL. Only follow it if it points back at
// this origin, so a misconfigured or spoofed link cannot make the panel send
// its session cookie somewhere else.
function sameOriginNext(next) {
    if (!next) return null;
    try {
        const url = new URL(next, window.location.href);
        return url.origin === window.location.origin ? url.toString() : null;
    } catch (e) { return null; }
}

// Follows `next` and concatenates every page.
//
// ROLES has to be COMPLETE, not merely the first page. roleCheckboxes()
// renders only what is in ROLES, selectedRoleIds() returns only the checked
// boxes, and that array is PATCHed as role_ids, which PersonSerializer treats
// as a FULL REPLACEMENT of the user's groups. auth.Group is a shared table and
// StaffPagination.page_size is 50, so past 50 groups a membership that sorted
// onto page 2 would never be rendered, never be checked, and be silently
// removed by an unrelated edit - with an audit entry recording the removal as
// deliberate. The page cap is a guard against a malformed cursor looping.
async function staffFetchAll(path) {
    let url = `${STAFF_API}${path}`;
    const rows = [];
    for (let page = 0; url && page < 200; page += 1) {
        const data = await apiFetch(url);
        rows.push(...(data.results || []));
        url = sameOriginNext(data.next);
    }
    return rows;
}

// ---------------------------------------------------------------------------
// Access levels.
//
// A person's level is derived, never stored: it is what their roles add up to.
// That keeps the roster honest when a role is edited - nobody has to remember
// to "promote" anyone. Owners are the exception, because is_superuser is a flag
// on the account that bypasses roles entirely (and is only ever set in the
// Django admin, never through this panel).
// ---------------------------------------------------------------------------
const TIERS = {
    owner: {
        label: 'Owner', icon: 'fa-crown',
        badge: 'bg-purple-500/10 text-purple-300 border-purple-500/20',
        summary: 'Holds every capability. Groups do not limit an owner.',
    },
    administrator: {
        label: 'Administrator', icon: 'fa-user-shield',
        badge: 'bg-sky-500/10 text-sky-300 border-sky-500/20',
        summary: 'Can invite people and change groups.',
    },
    member: {
        label: 'Member', icon: 'fa-user',
        badge: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
        summary: 'Can use the parts of the panel their groups open.',
    },
    none: {
        label: 'No access', icon: 'fa-user-slash',
        badge: 'bg-gray-500/10 text-gray-400 border-gray-500/20',
        summary: 'Can sign in, but the panel is empty until they join a group.',
    },
};

// Normal (non-staff) accounts are loaded too, so whoever manages staff can see
// them and invite them in. Opening one sends an invitation (openSignupInvite).
const PEOPLE_FILTERS = [
    { key: 'all', label: 'Everyone', test: () => true },
    { key: 'owner', label: 'Owners', test: p => p.is_staff && personTier(p) === 'owner' },
    { key: 'administrator', label: 'Administrators', test: p => p.is_staff && personTier(p) === 'administrator' },
    { key: 'member', label: 'Members', test: p => p.is_staff && personTier(p) === 'member' },
    { key: 'none', label: 'No access', test: p => p.is_staff && personTier(p) === 'none' },
    { key: 'pending', label: 'Setup pending', test: p => p.is_staff && !p.is_onboarded },
    { key: 'inactive', label: 'Deactivated', test: p => p.is_staff && !p.is_active },
    { key: 'signups', label: 'Not staff yet', test: p => !p.is_staff },
];

const SIGNUP_BADGE = '<span class="text-xs px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/20">Not staff yet</span>';

let PEOPLE = [];
const peopleView = { query: '', filter: 'all' };

// Who is looking. The API still enforces every rule below; reading it here only
// lets the editor say why a control is locked instead of failing on save.
function staffViewer() {
    const root = document.getElementById('staff');
    return {
        id: Number(root ? root.dataset.userId : 0),
        isSuperuser: !!root && root.dataset.userSuperuser === 'true',
    };
}

function capabilityLabels() {
    const labels = {};
    CAPABILITY_GROUPS.forEach(group => group.capabilities.forEach(cap => { labels[cap.codename] = cap.label; }));
    return labels;
}

function capsForRoleNames(names) {
    const held = new Set();
    names.forEach(name => {
        const role = ROLES.find(r => r.name === name);
        if (role) role.capabilities.forEach(code => held.add(code));
    });
    return held;
}

function tierFor(isSuperuser, caps) {
    if (isSuperuser) return 'owner';
    if (caps.has('manage_staff')) return 'administrator';
    return caps.size ? 'member' : 'none';
}

function personTier(person) {
    return tierFor(person.is_superuser, capsForRoleNames(person.roles));
}

function personName(person) {
    return `${person.first_name || ''} ${person.last_name || ''}`.trim() || person.username;
}

function initialsOf(person) {
    const words = personName(person).replace(/@.*$/, '').split(/[\s._-]+/).filter(Boolean);
    const letters = words.slice(0, 2).map(w => w[0]).join('');
    return (letters || '?').toUpperCase();
}

function timeAgo(iso) {
    if (!iso) return '';
    const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    const plural = (n, unit) => `${n} ${unit}${n === 1 ? '' : 's'} ago`;
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return plural(Math.floor(seconds / 60), 'minute');
    if (seconds < 86400) return plural(Math.floor(seconds / 3600), 'hour');
    if (seconds < 2592000) return plural(Math.floor(seconds / 86400), 'day');
    if (seconds < 31536000) return plural(Math.floor(seconds / 2592000), 'month');
    return plural(Math.floor(seconds / 31536000), 'year');
}

function tierBadge(tierKey) {
    const tier = TIERS[tierKey];
    return `<span class="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${tier.badge}">
        <i class="fas ${tier.icon} text-[10px]"></i>${tier.label}</span>`;
}

// ---------------------------------------------------------------------------
// Lists
// ---------------------------------------------------------------------------

// The paginated lists that still load a page at a time. People are fetched in
// full (see loadPeople) so search, filter counts and the editor share one list.
const STAFF_LISTS = {
    invitations: {
        path: '/invitations/',
        container: 'staffInvitesList',
        more: 'staffInvitesMore',
        block: 'staffInvitesBlock',
        empty: '',
        row: inv => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
            <div class="min-w-0">
                <div class="text-white font-medium truncate">${escapeHtml(inv.email)}</div>
                <div class="text-xs text-gray-500">Will get ${escapeHtml(inv.roles.join(', ') || 'no roles')}</div>
            </div>
            <div class="flex items-center gap-4">
                <span class="text-xs px-2 py-1 rounded bg-yellow-500/10 text-yellow-400">Pending</span>
                <button type="button" data-action="resend-invite" data-id="${escapeHtml(inv.id)}"
                    class="text-xs text-brand-blue hover:text-blue-400">Resend</button>
                <button type="button" data-action="revoke-invite" data-id="${escapeHtml(inv.id)}"
                    class="text-xs text-red-400 hover:text-red-300">Revoke</button>
            </div>
        </div>`,
    },
    activity: {
        path: '/activity/',
        container: 'staffActivityList',
        more: 'staffActivityMore',
        empty: '<p class="text-gray-500 text-sm">Nothing yet.</p>',
        row: entry => `
        <div class="bg-dark-card border border-dark-border rounded-lg px-4 py-3 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-1 sm:gap-4">
            <span class="text-sm text-gray-300">${escapeHtml(entry.summary)}</span>
            <span class="text-xs text-gray-600 sm:whitespace-nowrap">
                ${escapeHtml(new Date(entry.created_at).toLocaleString())}
            </span>
        </div>`,
    },
};

// The `next` cursor for each list, so Load more knows where to continue.
const STAFF_CURSORS = { invitations: null, activity: null };

async function loadList(key, append = false) {
    const config = STAFF_LISTS[key];
    const container = document.getElementById(config.container);
    if (!container) return;
    if (append && !STAFF_CURSORS[key]) return;

    const data = await apiFetch(append ? STAFF_CURSORS[key] : `${STAFF_API}${config.path}`);
    const rows = (data.results || []).map(config.row).join('');
    if (append) {
        container.insertAdjacentHTML('beforeend', rows);
    } else {
        container.innerHTML = rows || config.empty;
        if (config.block) {
            document.getElementById(config.block).classList.toggle('hidden', !rows);
        }
    }

    STAFF_CURSORS[key] = sameOriginNext(data.next);
    const more = document.getElementById(config.more);
    if (more) more.classList.toggle('hidden', !STAFF_CURSORS[key]);
}

async function loadStaff() {
    const inviteBtn = document.getElementById('inviteBtn');
    const newRoleBtn = document.getElementById('newRoleBtn');
    try {
        if (!CAPABILITY_GROUPS.length) {
            CAPABILITY_GROUPS = await staffFetch('/capabilities/');
        }
        // Roles first and awaited: the roster derives access levels from
        // ROLES, and both modals build their role cards from ROLES and
        // CAPABILITY_GROUPS. Their buttons stay disabled until those exist.
        await loadRoles();
        if (inviteBtn) inviteBtn.disabled = false;
        if (newRoleBtn) newRoleBtn.disabled = false;
        await Promise.all([loadPeople(), loadActivity()]);
    } catch (e) {
        console.error(e);
        toastApiError(e, 'Staff data could not be loaded.');
    }
}

async function loadPeople() {
    const [people] = await Promise.all([staffFetchAll('/people/?include=signups'), loadList('invitations')]);
    PEOPLE = people;
    renderPeople();
}

async function loadActivity() {
    await loadList('activity');
}

// ---------------------------------------------------------------------------
// People roster
// ---------------------------------------------------------------------------

function personMatches(person, query) {
    if (!query) return true;
    const haystack = [personName(person), person.username, person.email, person.primary_role, ...(person.scopes || []), ...person.roles]
        .join(' ').toLowerCase();
    return query.toLowerCase().split(/\s+/).filter(Boolean).every(word => haystack.includes(word));
}

function renderFilters() {
    const container = document.getElementById('staffFilters');
    if (!container) return;
    container.innerHTML = PEOPLE_FILTERS.map(filter => {
        const count = PEOPLE.filter(filter.test).length;
        const active = peopleView.filter === filter.key;
        // An empty filter is noise, but the one in use must stay visible so it can be switched off.
        if (!count && !active && filter.key !== 'all') return '';
        return `<button type="button" data-action="set-filter" data-filter="${filter.key}" aria-pressed="${active}"
            class="px-3 py-1.5 text-xs rounded-full border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-blue ${active
                ? 'border-brand-blue text-white bg-white/5'
                : 'border-dark-border text-gray-400 hover:text-white hover:bg-white/5'}">
            ${filter.label} <span class="ml-1 text-gray-500">${count}</span></button>`;
    }).join('');
}

function personRow(person) {
    const tierKey = personTier(person);
    const lastSeen = person.last_login
        ? `Signed in ${timeAgo(person.last_login)}`
        : 'Never signed in';
    const roleChips = person.is_superuser
        ? '<span class="text-xs text-gray-500">Every capability</span>'
        : (person.roles.length
            ? person.roles.map(r => `<span class="text-[11px] px-2 py-0.5 rounded bg-white/5 text-gray-300 border border-white/10">${escapeHtml(r)}</span>`).join('')
            : '<span class="text-xs text-gray-500">No roles yet</span>');
    return `
    <button type="button" data-action="edit-person" data-id="${escapeHtml(person.id)}"
        class="w-full text-left flex items-start gap-3 p-4 hover:bg-white/[0.03] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-blue ${person.is_active || !person.is_staff ? '' : 'opacity-60'}">
        <span class="shrink-0 w-10 h-10 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-sm font-semibold text-gray-300 font-heading" aria-hidden="true">${escapeHtml(initialsOf(person))}</span>
        <span class="min-w-0 flex-1">
            <span class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="text-white font-medium">${escapeHtml(personName(person))}</span>
                ${person.is_staff ? tierBadge(tierKey) : SIGNUP_BADGE}
                ${person.is_active || !person.is_staff ? '' : '<span class="text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-300 border border-red-500/20">Deactivated</span>'}
                ${person.is_onboarded || !person.is_staff ? '' : '<span class="text-xs px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20">Setup pending</span>'}
            </span>
            <span class="block text-xs text-gray-400 mt-0.5 truncate">${escapeHtml(person.email || person.username)}</span>
            ${(person.scopes || []).length ? `<span class="block text-xs text-gray-500 mt-0.5">${escapeHtml(person.scopes.join(', '))}</span>` : ''}
            <span class="flex flex-wrap items-center gap-1.5 mt-2">${roleChips}</span>
            <span class="block text-xs text-gray-500 mt-2 sm:hidden">${escapeHtml(lastSeen)}</span>
        </span>
        <span class="hidden sm:block shrink-0 text-xs text-gray-500 text-right pt-1">${escapeHtml(lastSeen)}</span>
        <i class="fas fa-chevron-right text-xs text-gray-600 pt-3" aria-hidden="true"></i>
    </button>`;
}

function renderPeople() {
    const container = document.getElementById('staffPeopleList');
    if (!container) return;
    renderFilters();

    const filter = PEOPLE_FILTERS.find(f => f.key === peopleView.filter) || PEOPLE_FILTERS[0];
    const rows = PEOPLE.filter(p => filter.test(p) && personMatches(p, peopleView.query));

    if (rows.length) {
        container.innerHTML = rows.map(personRow).join('');
    } else if (!PEOPLE.length) {
        container.innerHTML = '<p class="p-6 text-sm text-gray-500">Nobody yet. Invite the first person to get started.</p>';
    } else {
        container.innerHTML = `<div class="p-6 text-sm text-gray-400">
            No one matches that.
            <button type="button" data-action="clear-filters" class="ml-1 text-brand-blue hover:text-blue-400">Show everyone</button>
        </div>`;
    }
}

function setPeopleView(patch) {
    Object.assign(peopleView, patch);
    renderPeople();
}

// ---------------------------------------------------------------------------
// Roles
// ---------------------------------------------------------------------------

async function loadRoles() {
    const container = document.getElementById('staffRolesList');
    if (!container) return;

    [ROLES, MAILBOXES] = await Promise.all([staffFetchAll('/roles/'), apiFetch(`${MAIL_SHARED_API}/`)]);
    const labels = capabilityLabels();
    container.innerHTML = ROLES.map(role => {
        const shown = role.capabilities.slice(0, 6);
        const extra = role.capabilities.length - shown.length;
        const faces = role.members.slice(0, 5).map(m => `
            <span class="w-7 h-7 -ml-1.5 first:ml-0 rounded-full bg-white/10 border-2 border-dark-card text-[10px] font-semibold text-gray-200 flex items-center justify-center" title="${escapeHtml(m.name)}">${escapeHtml(initialsOf({ username: m.name }))}</span>`).join('');
        const memberLine = role.members.length
            ? `<button type="button" data-action="show-role-members" data-role="${escapeHtml(role.name)}"
                    class="text-xs text-brand-blue hover:text-blue-400">${role.members.length} member${role.members.length === 1 ? '' : 's'}</button>`
            : '<span class="text-xs text-gray-500">No members yet</span>';
        const invited = role.invited.length
            ? `<span class="text-xs text-gray-500">, ${role.invited.length} invited</span>` : '';
        return `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex flex-col gap-3">
            <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                    <div class="text-white font-medium font-heading truncate">${escapeHtml(role.name)}</div>
                    <div class="flex items-center gap-2 mt-1.5">
                        ${faces ? `<span class="flex">${faces}</span>` : ''}
                        <span>${memberLine}${invited}</span>
                    </div>
                </div>
                <div class="flex items-center gap-4 shrink-0">
                    <button type="button" data-action="edit-role" data-id="${escapeHtml(role.id)}"
                        class="text-xs text-brand-blue hover:text-blue-400">Edit</button>
                    <button type="button" data-action="delete-role" data-id="${escapeHtml(role.id)}"
                        class="text-xs text-red-400 hover:text-red-300">Delete</button>
                </div>
            </div>
            ${role.mailboxes.length ? `<div class="flex flex-wrap gap-1.5">
                ${role.mailboxes.map(name => `<span class="text-[11px] px-2 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20"><i class="fas fa-inbox mr-1"></i>${escapeHtml(name)}@</span>`).join('')}
            </div>` : ''}
            <div class="flex flex-wrap gap-1.5">
                ${shown.map(code => `<span class="text-[11px] px-2 py-0.5 rounded bg-white/5 text-gray-300 border border-white/10">${escapeHtml(labels[code] || code)}</span>`).join('')
                    || '<span class="text-xs text-gray-500">No capabilities</span>'}
                ${extra > 0 ? `<span class="text-[11px] px-2 py-0.5 rounded text-gray-500">+${extra} more</span>` : ''}
            </div>
        </div>`;
    }).join('') || '<p class="text-gray-500 text-sm">No groups yet. Create one to give people access together.</p>';
    renderMailboxes();
}

function renderMailboxes() {
    const list = document.getElementById('staffMailboxList');
    if (!list) return;
    list.innerHTML = MAILBOXES.map(box => `
        <div class="flex flex-wrap sm:flex-nowrap items-center gap-x-4 gap-y-1 px-4 py-3">
            <i class="fas fa-inbox text-gray-500 shrink-0"></i>
            <div class="min-w-0 flex-1">
                <div class="text-sm text-white truncate">${escapeHtml(box.address)}</div>
                <div class="text-xs text-gray-500 truncate">${box.groups.length
                    ? escapeHtml(box.groups.join(', '))
                    : 'In no group. Only people who read every shared mailbox see it.'}</div>
            </div>
            <span class="text-xs text-gray-500 shrink-0">${box.threads} conversation${box.threads === 1 ? '' : 's'}</span>
            <button type="button" data-action="delete-mailbox" data-name="${escapeHtml(box.name)}"
                class="text-xs text-red-400 hover:text-red-300 shrink-0">Delete</button>
        </div>`).join('') || '<p class="px-4 py-3 text-sm text-gray-500">No shared mailboxes. Mail to any unknown address lands in Unmatched.</p>';
}

function mailboxDomain() {
    const any = MAILBOXES[0];
    return any ? any.address.split('@')[1] : 'teklora.co.ke';
}

async function createMailbox(name) {
    const box = await apiFetch(`${MAIL_SHARED_API}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ name }),
    });
    MAILBOXES = [...MAILBOXES, box].sort((a, b) => a.name.localeCompare(b.name));
    return box;
}

function capabilityCheckboxes(selected) {
    return CAPABILITY_GROUPS.map(group => `
        <div class="mb-4">
            <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                ${escapeHtml(group.label)}
            </div>
            ${group.capabilities.map(cap => `
                <label class="flex items-center gap-2 py-1 text-sm text-gray-300">
                    <input type="checkbox" value="${escapeHtml(cap.codename)}"
                        ${selected.includes(cap.codename) ? 'checked' : ''}
                        class="capability-box rounded bg-[#06090F] border-dark-border">
                    ${escapeHtml(cap.label)}
                </label>`).join('')}
        </div>`).join('');
}

// One selectable card per role, saying what it grants so nobody has to guess
// from the name. `.role-box` is what selectedRoleIds() reads.
function roleCards(selectedNames, disabled = false) {
    const labels = capabilityLabels();
    return ROLES.map(role => {
        const names = [
            ...role.mailboxes.map(name => `${name}@ mail`),
            ...role.capabilities.map(code => labels[code] || code),
        ];
        const summary = names.length
            ? names.slice(0, 3).join(', ') + (names.length > 3 ? `, and ${names.length - 3} more` : '')
            : 'Grants nothing yet';
        return `
        <label class="flex items-start gap-3 p-3 rounded-lg border border-dark-border ${disabled ? 'opacity-60' : 'cursor-pointer hover:bg-white/[0.03] has-[:checked]:border-brand-blue has-[:checked]:bg-white/[0.03]'}">
            <input type="checkbox" value="${escapeHtml(role.id)}"
                ${selectedNames.includes(role.name) ? 'checked' : ''} ${disabled ? 'disabled' : ''}
                class="role-box mt-1 rounded bg-[#06090F] border-dark-border">
            <span class="min-w-0">
                <span class="block text-sm text-white font-medium">${escapeHtml(role.name)}</span>
                <span class="block text-xs text-gray-400">${escapeHtml(summary)}</span>
            </span>
        </label>`;
    }).join('') || '<p class="text-xs text-gray-500">No groups exist yet. Create one in the Groups tab first.</p>';
}

// What a set of roles adds up to: the resulting level and the capabilities
// behind it, grouped the way the role editor groups them.
function accessPreview(caps, isSuperuser) {
    const tierKey = tierFor(isSuperuser, caps);
    const heading = `<div class="flex flex-wrap items-center gap-2 mb-1">${tierBadge(tierKey)}</div>
        <p class="text-xs text-gray-400 mb-3">${escapeHtml(TIERS[tierKey].summary)}</p>`;
    if (isSuperuser) return heading;

    const groups = CAPABILITY_GROUPS
        .map(group => ({ label: group.label, held: group.capabilities.filter(c => caps.has(c.codename)) }))
        .filter(group => group.held.length);
    if (!groups.length) return heading;

    return heading + groups.map(group => `
        <div class="mb-2">
            <div class="text-xs font-medium text-gray-300 mb-1">${escapeHtml(group.label)}</div>
            <ul class="grid gap-x-4 sm:grid-cols-2">
                ${group.held.map(c => `<li class="text-xs text-gray-400 py-0.5"><i class="fas fa-check text-emerald-400 mr-1.5 text-[10px]"></i>${escapeHtml(c.label)}</li>`).join('')}
            </ul>
        </div>`).join('');
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

function openStaffModal(title, bodyHtml) {
    // textContent, not innerHTML: the title carries a role or user name.
    document.getElementById('staffModalTitle').textContent = title;
    document.getElementById('staffModalBody').innerHTML = bodyHtml;
    const modal = document.getElementById('staffModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    modal.firstElementChild.scrollTop = 0;
}

function closeStaffModal() {
    const modal = document.getElementById('staffModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.getElementById('staffModalBody').innerHTML = '';
}

function selectedCapabilities() {
    return Array.from(document.querySelectorAll('.capability-box:checked')).map(b => b.value);
}

function selectedRoleIds() {
    return Array.from(document.querySelectorAll('.role-box:checked')).map(b => Number(b.value));
}

function selectedRoleNames() {
    const ids = new Set(selectedRoleIds());
    return ROLES.filter(r => ids.has(r.id)).map(r => r.name);
}

// Why the viewer cannot add or remove this person from a group, or ''.
function membershipLock(person, viewer) {
    if (viewer.isSuperuser) return '';
    if (person.id === viewer.id) return 'You';
    if (person.is_superuser) return 'Owner';
    return '';
}

function memberRows(role, viewer) {
    const memberIds = new Set((role ? role.members : []).map(m => m.id));
    const staff = PEOPLE.filter(p => p.is_staff && (p.is_active || memberIds.has(p.id)))
        .sort((a, b) => personName(a).localeCompare(personName(b)));
    if (!staff.length) return '<p class="text-xs text-gray-500">No staff accounts yet. Invite people below.</p>';
    return staff.map(person => {
        const lock = membershipLock(person, viewer);
        return `
        <label data-member-row data-search="${escapeHtml(`${personName(person)} ${person.username} ${person.email || ''}`.toLowerCase())}"
            class="flex items-center gap-3 px-3 py-2 rounded-lg ${lock ? 'opacity-60' : 'cursor-pointer hover:bg-white/[0.03]'}">
            <input type="checkbox" value="${escapeHtml(person.id)}" ${memberIds.has(person.id) ? 'checked' : ''} ${lock ? 'disabled' : ''}
                class="member-box rounded bg-[#06090F] border-dark-border">
            <span class="w-7 h-7 shrink-0 rounded-full bg-white/10 text-[10px] font-semibold text-gray-200 flex items-center justify-center">${escapeHtml(initialsOf(person))}</span>
            <span class="min-w-0 flex-1">
                <span class="block text-sm text-white truncate">${escapeHtml(personName(person))}</span>
                <span class="block text-xs text-gray-500 truncate">${escapeHtml(person.email || person.username)}${person.is_active ? '' : ', deactivated'}</span>
            </span>
            ${lock ? `<span class="text-[11px] text-gray-500 shrink-0" title="${lock === 'You' ? 'You cannot change your own groups' : 'Only an owner can change an owner'}">${lock}</span>` : ''}
        </label>`;
    }).join('');
}

function mailboxChips(selected) {
    return MAILBOXES.map(box => `
        <label class="inline-flex items-center gap-2 text-sm pl-2.5 pr-3 py-1.5 rounded-lg border border-dark-border text-gray-300 cursor-pointer hover:bg-white/[0.03] has-[:checked]:border-brand-blue has-[:checked]:text-white">
            <input type="checkbox" value="${escapeHtml(box.name)}" ${selected.includes(box.name) ? 'checked' : ''}
                class="mailbox-box rounded bg-[#06090F] border-dark-border">
            ${escapeHtml(box.address)}
        </label>`).join('') || '<span class="text-xs text-gray-500">No shared mailboxes yet. Create one here.</span>';
}

const FIELD = 'w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue';

function groupEditorHtml(role) {
    const viewer = staffViewer();
    const invited = role && role.invited.length
        ? `<span class="block text-xs text-gray-500 mt-2">Already invited: ${escapeHtml(role.invited.join(', '))}</span>` : '';
    return `
        <div class="space-y-6">
            <div>
                <label for="roleName" class="block text-sm font-medium text-white mb-2">Group name</label>
                <input type="text" id="roleName" value="${escapeHtml(role ? role.name : '')}" placeholder="e.g. HR, Sales, Writers" class="${FIELD}">
            </div>

            <fieldset class="min-w-0">
                <legend class="text-sm font-medium text-white mb-1">Members</legend>
                <span class="block text-xs text-gray-400 mb-2">Ticked people get everything this group grants.</span>
                <input type="search" id="memberSearch" placeholder="Search staff" autocomplete="off"
                    class="w-full mb-2 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brand-blue">
                <div id="memberRows" class="max-h-60 overflow-y-auto rounded-lg border border-dark-border p-1">${memberRows(role, viewer)}</div>
            </fieldset>

            <div>
                <label for="groupInvites" class="block text-sm font-medium text-white mb-1">Invite by email</label>
                <span class="block text-xs text-gray-400 mb-2">For people without an account yet. One address per line; each gets an invitation into this group when you save.</span>
                <textarea id="groupInvites" rows="2" placeholder="new.person@example.com" class="${FIELD} text-sm"></textarea>
                ${invited}
            </div>

            <fieldset class="min-w-0">
                <legend class="text-sm font-medium text-white mb-1">Shared mailboxes</legend>
                <span class="block text-xs text-gray-400 mb-2">Members read this mail and reply from these addresses.</span>
                <div id="mailboxChips" class="flex flex-wrap gap-2">${mailboxChips(role ? role.mailboxes : [])}</div>
                <div class="flex items-stretch gap-2 mt-3">
                    <div class="flex-1 min-w-0 flex items-center bg-[#06090F] border border-dark-border rounded-lg focus-within:border-brand-blue">
                        <input type="text" id="newMailboxName" placeholder="new mailbox" autocomplete="off" aria-label="New mailbox name"
                            class="flex-1 min-w-0 bg-transparent px-3 py-2 text-sm text-white focus:outline-none">
                        <span class="pr-3 text-sm text-gray-500 shrink-0">@${escapeHtml(mailboxDomain())}</span>
                    </div>
                    <button type="button" id="addMailboxBtn" class="px-3 py-2 text-sm rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5 shrink-0">Create</button>
                </div>
            </fieldset>

            <fieldset class="min-w-0">
                <legend class="text-sm font-medium text-white mb-2">Capabilities</legend>
                ${capabilityCheckboxes(role ? role.capabilities : [])}
            </fieldset>

            <button type="button" id="saveRoleBtn" data-role-id="${role ? escapeHtml(role.id) : ''}" class="${PRIMARY_BUTTON}">
                ${role ? 'Save group' : 'Create group'}
            </button>
        </div>`;
}

function openGroupEditor(role) {
    openStaffModal(role ? `Edit ${role.name}` : 'New group', groupEditorHtml(role));

    document.getElementById('memberSearch').addEventListener('input', (event) => {
        const q = event.target.value.trim().toLowerCase();
        document.querySelectorAll('[data-member-row]').forEach(row => {
            row.classList.toggle('hidden', !!q && !row.dataset.search.includes(q));
        });
    });

    const addMailbox = async () => {
        const input = document.getElementById('newMailboxName');
        const name = input.value.trim();
        if (!name) { input.focus(); return; }
        const kept = Array.from(document.querySelectorAll('.mailbox-box:checked')).map(b => b.value);
        try {
            const box = await createMailbox(name);
            document.getElementById('mailboxChips').innerHTML = mailboxChips([...kept, box.name]);
            input.value = '';
            renderMailboxes();
            toast.success(`${box.address} created.`);
        } catch (e) { toastApiError(e, 'The mailbox could not be created.'); }
    };
    document.getElementById('addMailboxBtn').addEventListener('click', addMailbox);
    document.getElementById('newMailboxName').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') { event.preventDefault(); addMailbox(); }
    });

    // The button is re-created by every openStaffModal() call (innerHTML is
    // replaced), so this listener cannot stack on a stale element.
    document.getElementById('saveRoleBtn').addEventListener('click', async (event) => {
        const button = event.currentTarget;
        const roleId = button.dataset.roleId;
        const name = document.getElementById('roleName').value.trim();
        if (!name) { toast.warning('Give the group a name.'); return; }
        const emails = document.getElementById('groupInvites').value
            .split(/[\s,;]+/).map(e => e.trim()).filter(Boolean);
        const payload = JSON.stringify({
            name,
            capabilities: selectedCapabilities(),
            mailboxes: Array.from(document.querySelectorAll('.mailbox-box:checked')).map(b => b.value),
            // Disabled rows are locked, not removed: keep them as they were.
            member_ids: Array.from(document.querySelectorAll('.member-box:checked')).map(b => Number(b.value)),
        });
        button.disabled = true;
        let group;
        try {
            group = roleId
                ? await staffFetch(`/roles/${roleId}/`, { method: 'PUT', body: payload })
                : await staffFetch('/roles/', { method: 'POST', body: payload });
        } catch (e) {
            button.disabled = false;
            toastApiError(e, 'The group could not be saved.');
            return;
        }
        // Each invitation stands alone: one bad address does not undo the
        // group or the other invitations.
        const failed = [];
        for (const email of emails) {
            try {
                await staffFetch('/invitations/', {
                    method: 'POST', body: JSON.stringify({ email, role_ids: [group.id] }),
                });
            } catch (e) { failed.push(`${email}: ${e.message}`); }
        }
        closeStaffModal();
        await Promise.all([loadRoles(), loadPeople(), loadActivity()]);
        if (failed.length) {
            toast.error(`Group saved, but ${failed.length === 1 ? 'one invitation' : 'some invitations'} failed. ${failed.join(' ')}`);
        } else {
            const sent = emails.length ? ` ${emails.length} invitation${emails.length === 1 ? '' : 's'} sent.` : '';
            toast.success(`Group ${roleId ? 'saved' : 'created'}.${sent}`);
        }
    });
}

const PRIMARY_BUTTON = 'w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed';

// Why the editor is read-only for this person, or '' when it is not.
function lockReason(person, viewer) {
    if (viewer.isSuperuser) return '';
    if (person.id === viewer.id) {
        return 'You cannot change your own groups or deactivate your own account. Ask another administrator.';
    }
    if (person.is_superuser) {
        return 'This person is an owner. Only another owner can change their groups or deactivate them.';
    }
    return '';
}

function personEditorHtml(person, viewer) {
    const locked = lockReason(person, viewer);
    const contact = [
        person.phone ? `<a href="https://wa.me/${escapeHtml(person.phone.replace('+', ''))}" target="_blank" rel="noopener"
            class="text-emerald-400 hover:text-emerald-300"><i class="fab fa-whatsapp mr-1"></i>${escapeHtml(person.phone)}</a>` : '',
        person.github_username ? `<a href="https://github.com/${escapeHtml(person.github_username)}" target="_blank" rel="noopener"
            class="text-gray-400 hover:text-white"><i class="fab fa-github mr-1"></i>${escapeHtml(person.github_username)}</a>` : '',
    ].filter(Boolean).join('<span class="mx-2 text-gray-700">/</span>');
    const joined = person.date_joined ? new Date(person.date_joined).toLocaleDateString() : '';
    const lastSeen = person.last_login ? `Signed in ${timeAgo(person.last_login)}` : 'Has never signed in';

    return `
    <div class="flex items-start gap-3 mb-5">
        <span class="shrink-0 w-12 h-12 rounded-full bg-white/5 border border-white/10 flex items-center justify-center font-semibold text-gray-300 font-heading" aria-hidden="true">${escapeHtml(initialsOf(person))}</span>
        <div class="min-w-0">
            <div class="text-white font-medium">${escapeHtml(personName(person))}</div>
            <div class="text-xs text-gray-400 truncate">${escapeHtml(person.email || person.username)}</div>
            ${person.primary_role ? `<div class="text-xs text-gray-500 mt-0.5">${escapeHtml(person.primary_role)}</div>` : ''}
            ${(person.scopes || []).length ? `<div class="text-xs text-gray-500 mt-0.5">Works in ${escapeHtml(person.scopes.join(', '))}</div>` : ''}
            <div class="text-xs text-gray-500 mt-0.5">${escapeHtml(lastSeen)}${joined ? `, joined ${escapeHtml(joined)}` : ''}</div>
            ${contact ? `<div class="text-xs mt-1.5">${contact}</div>` : ''}
            ${person.is_onboarded ? '' : '<div class="text-xs text-amber-300 mt-1.5">Has not finished setup: contact details, area of work and skills are missing.</div>'}
        </div>
    </div>

    ${locked ? `<div class="mb-5 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-xs text-amber-200">
        <i class="fas fa-lock mr-1.5"></i>${escapeHtml(locked)}</div>` : ''}
    ${person.is_superuser && viewer.isSuperuser ? `<div class="mb-5 rounded-lg border border-purple-500/20 bg-purple-500/5 px-3 py-2.5 text-xs text-purple-200">
        <i class="fas fa-crown mr-1.5"></i>This person is an owner. They hold every capability whatever groups are ticked below.</div>` : ''}

    <fieldset class="mb-5">
        <legend class="text-sm font-medium text-white mb-2">Groups</legend>
        <div class="space-y-2">${roleCards(person.roles, !!locked)}</div>
    </fieldset>

    <div class="mb-5 rounded-lg border border-dark-border p-3">
        <div class="text-sm font-medium text-white mb-2">What they can do</div>
        <div id="staffAccessPreview"></div>
    </div>

    <div class="mb-5 rounded-lg border border-dark-border p-3">
        <label class="flex items-start gap-3 ${locked ? 'opacity-60' : 'cursor-pointer'}">
            <input type="checkbox" id="personActive" ${person.is_active ? 'checked' : ''} ${locked ? 'disabled' : ''}
                class="mt-1 rounded bg-[#06090F] border-dark-border">
            <span>
                <span class="block text-sm text-white font-medium">Account active</span>
                <span class="block text-xs text-gray-400">Turn this off to stop them signing in. Their groups are kept, so turning it back on restores their access.</span>
            </span>
        </label>
    </div>

    <div class="sticky bottom-0 -mx-5 sm:-mx-6 -mb-5 px-5 sm:px-6 py-4 bg-dark-card border-t border-dark-border">
        ${locked
            ? `<button type="button" id="closePersonBtn" class="w-full px-5 py-3 rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5">Close</button>`
            : `<button type="button" id="savePersonBtn" disabled class="${PRIMARY_BUTTON}">Save changes</button>`}
    </div>`;
}

function openPersonEditor(person) {
    const viewer = staffViewer();
    openStaffModal(personName(person), personEditorHtml(person, viewer));

    const preview = document.getElementById('staffAccessPreview');
    const active = document.getElementById('personActive');
    const initialRoles = [...person.roles].sort().join('|');
    const body = document.getElementById('staffModalBody');

    const sync = () => {
        preview.innerHTML = accessPreview(capsForRoleNames(selectedRoleNames()), person.is_superuser);
        const save = document.getElementById('savePersonBtn');
        if (save) {
            save.disabled = [...selectedRoleNames()].sort().join('|') === initialRoles
                && active.checked === person.is_active;
        }
    };
    body.addEventListener('change', sync);
    sync();

    const close = document.getElementById('closePersonBtn');
    if (close) close.addEventListener('click', closeStaffModal);

    const save = document.getElementById('savePersonBtn');
    if (!save) return;
    save.addEventListener('click', async () => {
        if (person.is_active && !active.checked) {
            const confirmed = await tkConfirm(
                'They will not be able to sign in or use the panel until you turn the account back on.',
                { title: `Deactivate ${personName(person)}?`, confirmText: 'Deactivate', danger: true },
            );
            if (!confirmed) return;
        }
        save.disabled = true;
        try {
            await staffFetch(`/people/${person.id}/`, {
                method: 'PATCH',
                body: JSON.stringify({ role_ids: selectedRoleIds(), is_active: active.checked }),
            });
            closeStaffModal();
            toast.success('Changes saved.');
            await Promise.all([loadPeople(), loadRoles(), loadActivity()]);
        } catch (e) {
            save.disabled = false;
            toastApiError(e, 'The changes could not be saved.');
        }
    });
}

// A /signup/ account never proved it owns its address, so it is not edited in
// place. It is invited like anyone else, and accepting the emailed link takes
// the account over (staff/signups.py).
function openSignupInvite(person) {
    const email = person.email || person.username;
    const joined = person.date_joined ? new Date(person.date_joined).toLocaleDateString() : '';
    openStaffModal(personName(person), `
    <div class="flex items-start gap-3 mb-5">
        <span class="shrink-0 w-12 h-12 rounded-full bg-white/5 border border-white/10 flex items-center justify-center font-semibold text-gray-300 font-heading" aria-hidden="true">${escapeHtml(initialsOf(person))}</span>
        <div class="min-w-0">
            <div class="text-white font-medium">${escapeHtml(personName(person))}</div>
            <div class="text-xs text-gray-400 truncate">${escapeHtml(email)}</div>
            ${joined ? `<div class="text-xs text-gray-500 mt-0.5">Signed up ${escapeHtml(joined)}</div>` : ''}
        </div>
    </div>
    <div class="mb-5 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2.5 text-xs text-sky-200">
        <i class="fas fa-user-plus mr-1.5"></i>This is a normal account, not staff, so it cannot open the panel.
        Send an invitation to its address. When they accept it from that inbox, this account becomes an active staff account
        with the roles below, and they choose a new password.</div>
    <fieldset class="mb-5">
        <legend class="text-sm font-medium text-white mb-2">Roles</legend>
        <div class="space-y-2">${roleCards([])}</div>
    </fieldset>
    <div class="sticky bottom-0 -mx-5 sm:-mx-6 -mb-5 px-5 sm:px-6 py-4 bg-dark-card border-t border-dark-border">
        <button type="button" id="inviteSignupBtn" class="${PRIMARY_BUTTON}">Send staff invitation</button>
    </div>`);

    const send = document.getElementById('inviteSignupBtn');
    send.addEventListener('click', async () => {
        send.disabled = true;
        try {
            await staffFetch('/invitations/', {
                method: 'POST',
                body: JSON.stringify({ email, role_ids: selectedRoleIds() }),
            });
            closeStaffModal();
            await Promise.all([loadPeople(), loadActivity()]);
            toast.success(`Invitation sent to ${email}.`);
        } catch (e) {
            send.disabled = false;
            toastApiError(e, 'The invitation could not be sent.');
        }
    });
}

function showStaffTab(name) {
    const section = document.getElementById('staff');
    section.querySelectorAll('.staff-tab').forEach(tab => {
        const on = tab.dataset.tab === name;
        tab.classList.toggle('text-white', on);
        tab.classList.toggle('border-brand-blue', on);
        tab.classList.toggle('text-gray-400', !on);
        tab.classList.toggle('border-transparent', !on);
    });
    const paneId = { people: 'staffPeople', roles: 'staffRoles', activity: 'staffActivity' }[name];
    section.querySelectorAll('.staff-pane').forEach(p => p.classList.toggle('hidden', p.id !== paneId));
}

document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('staff');
    if (!section) return;   // user lacks manage_staff; the section was not rendered

    document.getElementById('staffModalClose').addEventListener('click', closeStaffModal);
    const modal = document.getElementById('staffModal');
    modal.addEventListener('click', (event) => { if (event.target === modal) closeStaffModal(); });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !modal.classList.contains('hidden')) closeStaffModal();
    });

    section.querySelectorAll('.staff-tab').forEach(tab => {
        tab.addEventListener('click', () => showStaffTab(tab.dataset.tab));
    });

    document.getElementById('staffSearch').addEventListener('input', (event) => {
        setPeopleView({ query: event.target.value.trim() });
    });

    document.getElementById('inviteBtn').addEventListener('click', () => {
        openStaffModal('Invite person', `
            <div class="space-y-5">
                <div>
                    <label for="inviteEmail" class="block text-sm font-medium text-white mb-2">Email address</label>
                    <input type="email" id="inviteEmail" required
                        class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                </div>
                <fieldset>
                    <legend class="text-sm font-medium text-white mb-1">Groups</legend>
                    <p class="text-xs text-gray-400 mb-2">They get these the moment they accept. You can change them later.</p>
                    <div class="space-y-2">${roleCards([])}</div>
                </fieldset>
                <button type="button" id="sendInviteBtn" class="${PRIMARY_BUTTON}">
                    Send invitation
                </button>
            </div>`);

        document.getElementById('sendInviteBtn').addEventListener('click', async () => {
            const email = document.getElementById('inviteEmail').value.trim();
            if (!email) { toast.warning('Enter an email address.'); return; }
            try {
                await staffFetch('/invitations/', {
                    method: 'POST',
                    body: JSON.stringify({ email, role_ids: selectedRoleIds() }),
                });
                closeStaffModal();
                await Promise.all([loadPeople(), loadActivity()]);
                toast.success('Invitation sent.');
            } catch (e) { toastApiError(e, 'The invitation could not be sent.'); }
        });
    });

    document.getElementById('newRoleBtn').addEventListener('click', () => openGroupEditor(null));

    document.getElementById('newMailboxBtn').addEventListener('click', () => {
        openStaffModal('New shared mailbox', `
            <div class="space-y-4">
                <div>
                    <label for="mailboxName" class="block text-sm font-medium text-white mb-2">Address</label>
                    <div class="flex items-center bg-[#06090F] border border-dark-border rounded-lg focus-within:border-brand-blue">
                        <input type="text" id="mailboxName" placeholder="events" autocomplete="off"
                            class="flex-1 min-w-0 bg-transparent px-4 py-3 text-white focus:outline-none">
                        <span class="pr-4 text-gray-500 shrink-0">@${escapeHtml(mailboxDomain())}</span>
                    </div>
                    <span class="block text-xs text-gray-400 mt-2">Nobody reads it until you add it to a group, apart from people who read every shared mailbox.</span>
                </div>
                <button type="button" id="saveMailboxBtn" class="${PRIMARY_BUTTON}">Create mailbox</button>
            </div>`);
        const input = document.getElementById('mailboxName');
        input.focus();
        const save = async () => {
            try {
                const box = await createMailbox(input.value.trim());
                closeStaffModal();
                renderMailboxes();
                await loadActivity();
                toast.success(`${box.address} created.`);
            } catch (e) { toastApiError(e, 'The mailbox could not be created.'); }
        };
        document.getElementById('saveMailboxBtn').addEventListener('click', save);
        input.addEventListener('keydown', (event) => { if (event.key === 'Enter') save(); });
    });

    // One delegated listener for every row action. #staff is a stable
    // ancestor across re-renders (only inner innerHTML is replaced), so this
    // is registered once rather than per row.
    section.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const id = Number(button.dataset.id);

        if (button.dataset.action === 'set-filter') {
            setPeopleView({ filter: button.dataset.filter });
        }

        if (button.dataset.action === 'clear-filters') {
            document.getElementById('staffSearch').value = '';
            setPeopleView({ query: '', filter: 'all' });
        }

        // From a role card: jump to the people holding it.
        if (button.dataset.action === 'show-role-members') {
            document.getElementById('staffSearch').value = button.dataset.role;
            showStaffTab('people');
            setPeopleView({ query: button.dataset.role, filter: 'all' });
        }

        // Load more: continue from the stored `next` cursor and append.
        // The button is disabled for the duration so a double click cannot
        // fire two appends of the same page.
        if (button.dataset.action === 'load-more') {
            const key = button.dataset.list;
            if (!STAFF_LISTS[key]) return;
            button.disabled = true;
            try {
                await loadList(key, true);
            } catch (e) {
                toastApiError(e, 'The next page could not be loaded.');
            } finally {
                button.disabled = false;
            }
        }

        // Every mutation below writes an audit entry, so each refreshes the
        // Activity pane as well as the list it changed - otherwise a user
        // watching Activity sees nothing until they re-enter the section.
        if (button.dataset.action === 'revoke-invite') {
            if (!await tkConfirm('The invitation link stops working immediately.', { title: 'Revoke this invitation?', confirmText: 'Revoke', danger: true })) return;
            try {
                await staffFetch(`/invitations/${id}/`, { method: 'DELETE' });
                toast.success('Invitation revoked.');
                await Promise.all([loadPeople(), loadActivity()]);
            } catch (e) { toastApiError(e, 'The invitation could not be revoked.'); }
        }

        if (button.dataset.action === 'resend-invite') {
            try {
                await staffFetch(`/invitations/${id}/resend/`, { method: 'POST' });
                await loadActivity();
                toast.success('Invitation resent.');
            } catch (e) { toastApiError(e, 'The invitation could not be resent.'); }
        }

        if (button.dataset.action === 'delete-role') {
            const role = ROLES.find(r => r.id === id);
            if (!await tkConfirm(`Members keep their accounts but lose what "${role ? role.name : ''}" granted, including its shared mailboxes.`, { title: 'Delete this group?', confirmText: 'Delete group', danger: true })) return;
            try {
                await staffFetch(`/roles/${id}/`, { method: 'DELETE' });
                toast.success('Group deleted.');
                await Promise.all([loadRoles(), loadPeople(), loadActivity()]);
            } catch (e) { toastApiError(e, 'The group could not be deleted.'); }
        }

        if (button.dataset.action === 'delete-mailbox') {
            const box = MAILBOXES.find(b => b.name === button.dataset.name);
            if (!box) return;
            const moved = box.threads ? ` Its ${box.threads} conversation${box.threads === 1 ? '' : 's'} move to Unmatched, and so does new mail to it.` : ' New mail to it will land in Unmatched.';
            if (!await tkConfirm(`${box.address} is removed from every group.${moved}`, { title: 'Delete this mailbox?', confirmText: 'Delete mailbox', danger: true })) return;
            try {
                await apiFetch(`${MAIL_SHARED_API}/${encodeURIComponent(box.name)}/`, {
                    method: 'DELETE', headers: { 'X-CSRFToken': CSRF_TOKEN },
                });
                toast.success('Mailbox deleted.');
                await Promise.all([loadRoles(), loadActivity()]);
            } catch (e) { toastApiError(e, 'The mailbox could not be deleted.'); }
        }

        if (button.dataset.action === 'edit-role') {
            const role = ROLES.find(r => r.id === id);
            if (role) openGroupEditor(role);
        }

        if (button.dataset.action === 'edit-person') {
            const row = PEOPLE.find(p => p.id === id);
            if (row && !row.is_staff) { openSignupInvite(row); return; }
            // Fetch fresh rather than reuse the roster row: the editor decides
            // what to lock from it, and the roster may be a few minutes old.
            let person;
            try {
                person = await staffFetch(`/people/${id}/`);
            } catch (e) { toastApiError(e, 'That person could not be opened.'); return; }
            openPersonEditor(person);
        }
    });
});
