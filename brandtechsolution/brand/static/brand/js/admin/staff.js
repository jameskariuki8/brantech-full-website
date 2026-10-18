// Staff & Roles section.
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
            detail = typeof body === 'string' ? body : (body.detail || JSON.stringify(body));
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
        summary: 'Holds every capability. Roles do not limit an owner.',
    },
    administrator: {
        label: 'Administrator', icon: 'fa-user-shield',
        badge: 'bg-sky-500/10 text-sky-300 border-sky-500/20',
        summary: 'Can invite people and change roles.',
    },
    member: {
        label: 'Member', icon: 'fa-user',
        badge: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
        summary: 'Can use the parts of the panel their roles open.',
    },
    none: {
        label: 'No access', icon: 'fa-user-slash',
        badge: 'bg-gray-500/10 text-gray-400 border-gray-500/20',
        summary: 'Can sign in, but the panel is empty until they get a role.',
    },
};

// Accounts from the public /signup/ form are loaded too, so they can be found
// and given a role. They stay out of the roster until searched for or picked
// through their own filter, since anyone can create one.
const PEOPLE_FILTERS = [
    { key: 'all', label: 'Everyone', test: p => p.is_staff || !!peopleView.query },
    { key: 'owner', label: 'Owners', test: p => p.is_staff && personTier(p) === 'owner' },
    { key: 'administrator', label: 'Administrators', test: p => p.is_staff && personTier(p) === 'administrator' },
    { key: 'member', label: 'Members', test: p => p.is_staff && personTier(p) === 'member' },
    { key: 'none', label: 'No access', test: p => p.is_staff && personTier(p) === 'none' },
    { key: 'pending', label: 'Setup pending', test: p => p.is_staff && !p.is_onboarded },
    { key: 'inactive', label: 'Deactivated', test: p => p.is_staff && !p.is_active },
    { key: 'signups', label: 'Signed up, not staff', test: p => !p.is_staff },
];

const SIGNUP_BADGE = '<span class="text-xs px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-300 border border-sky-500/20">Signed up, not staff</span>';

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
        class="w-full text-left flex items-start gap-3 p-4 hover:bg-white/[0.03] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-blue ${person.is_active ? '' : 'opacity-60'}">
        <span class="shrink-0 w-10 h-10 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-sm font-semibold text-gray-300 font-heading" aria-hidden="true">${escapeHtml(initialsOf(person))}</span>
        <span class="min-w-0 flex-1">
            <span class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span class="text-white font-medium">${escapeHtml(personName(person))}</span>
                ${person.is_staff ? tierBadge(tierKey) : SIGNUP_BADGE}
                ${person.is_active ? '' : '<span class="text-xs px-2 py-0.5 rounded-full bg-red-500/10 text-red-300 border border-red-500/20">Deactivated</span>'}
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

    ROLES = await staffFetchAll('/roles/');
    const labels = capabilityLabels();
    container.innerHTML = ROLES.map(role => {
        const shown = role.capabilities.slice(0, 6);
        const extra = role.capabilities.length - shown.length;
        return `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex flex-col gap-3">
            <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                    <div class="text-white font-medium font-heading">${escapeHtml(role.name)}</div>
                    ${role.member_count
                        ? `<button type="button" data-action="show-role-members" data-role="${escapeHtml(role.name)}"
                            class="text-xs text-brand-blue hover:text-blue-400">${role.member_count} member${role.member_count === 1 ? '' : 's'}, show who</button>`
                        : '<span class="text-xs text-gray-500">Nobody has this role</span>'}
                </div>
                <div class="flex items-center gap-4 shrink-0">
                    <button type="button" data-action="edit-role" data-id="${escapeHtml(role.id)}"
                        class="text-xs text-brand-blue hover:text-blue-400">Edit</button>
                    <button type="button" data-action="delete-role" data-id="${escapeHtml(role.id)}"
                        class="text-xs text-red-400 hover:text-red-300">Delete</button>
                </div>
            </div>
            <div class="flex flex-wrap gap-1.5">
                ${shown.map(code => `<span class="text-[11px] px-2 py-0.5 rounded bg-white/5 text-gray-300 border border-white/10">${escapeHtml(labels[code] || code)}</span>`).join('')
                    || '<span class="text-xs text-gray-500">No capabilities yet</span>'}
                ${extra > 0 ? `<span class="text-[11px] px-2 py-0.5 rounded text-gray-500">+${extra} more</span>` : ''}
            </div>
        </div>`;
    }).join('') || '<p class="text-gray-500 text-sm">No roles yet.</p>';
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
        const names = role.capabilities.map(code => labels[code] || code);
        const summary = names.length
            ? names.slice(0, 3).join(', ') + (names.length > 3 ? `, and ${names.length - 3} more` : '')
            : 'No capabilities yet';
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
    }).join('') || '<p class="text-xs text-gray-500">No roles exist yet. Create one in the Roles tab first.</p>';
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

function wireRoleSave() {
    // The button is re-created by every openStaffModal() call (innerHTML is
    // replaced), so this listener cannot stack on a stale element.
    document.getElementById('saveRoleBtn').addEventListener('click', async (event) => {
        const roleId = event.currentTarget.dataset.roleId;
        const name = document.getElementById('roleName').value.trim();
        if (!name) { toast.warning('Give the role a name.'); return; }
        const payload = JSON.stringify({ name, capabilities: selectedCapabilities() });
        try {
            if (roleId) {
                await staffFetch(`/roles/${roleId}/`, { method: 'PUT', body: payload });
            } else {
                await staffFetch('/roles/', { method: 'POST', body: payload });
            }
            closeStaffModal();
            await Promise.all([loadRoles(), loadPeople(), loadActivity()]);
        } catch (e) { toastApiError(e, 'The role could not be saved.'); }
    });
}

const PRIMARY_BUTTON = 'w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed';

// Why the editor is read-only for this person, or '' when it is not.
function lockReason(person, viewer) {
    if (viewer.isSuperuser) return '';
    if (person.id === viewer.id) {
        return 'You cannot change your own roles or deactivate your own account. Ask another administrator.';
    }
    if (person.is_superuser) {
        return 'This person is an owner. Only another owner can change their roles or deactivate them.';
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
            ${person.is_onboarded || !person.is_staff ? '' : '<div class="text-xs text-amber-300 mt-1.5">Has not finished setup: contact details, area of work and skills are missing.</div>'}
        </div>
    </div>

    ${person.is_staff ? '' : `<div class="mb-5 rounded-lg border border-sky-500/20 bg-sky-500/5 px-3 py-2.5 text-xs text-sky-200">
        <i class="fas fa-user-plus mr-1.5"></i>This account was made with the public sign-up form, so it cannot open the panel yet.
        Give it a role to make it a staff account. Anyone can sign up, so check the email address really belongs to this person first.</div>`}

    ${locked ? `<div class="mb-5 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2.5 text-xs text-amber-200">
        <i class="fas fa-lock mr-1.5"></i>${escapeHtml(locked)}</div>` : ''}
    ${person.is_superuser && viewer.isSuperuser ? `<div class="mb-5 rounded-lg border border-purple-500/20 bg-purple-500/5 px-3 py-2.5 text-xs text-purple-200">
        <i class="fas fa-crown mr-1.5"></i>This person is an owner. They hold every capability whatever roles are ticked below.</div>` : ''}

    <fieldset class="mb-5">
        <legend class="text-sm font-medium text-white mb-2">Roles</legend>
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
                <span class="block text-xs text-gray-400">Turn this off to stop them signing in. Their roles are kept, so turning it back on restores their access.</span>
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
        const roleIds = selectedRoleIds();
        try {
            await staffFetch(`/people/${person.id}/`, {
                method: 'PATCH',
                body: JSON.stringify({ role_ids: roleIds, is_active: active.checked }),
            });
            closeStaffModal();
            toast.success(!person.is_staff && roleIds.length
                ? `${personName(person)} is now staff. They will finish setup when they next sign in.`
                : 'Changes saved.');
            await Promise.all([loadPeople(), loadRoles(), loadActivity()]);
        } catch (e) {
            save.disabled = false;
            toastApiError(e, 'The changes could not be saved.');
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
                    <legend class="text-sm font-medium text-white mb-1">Roles</legend>
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

    document.getElementById('newRoleBtn').addEventListener('click', () => {
        openStaffModal('New role', `
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-400 mb-2">Role name</label>
                    <input type="text" id="roleName"
                        class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                </div>
                <div>${capabilityCheckboxes([])}</div>
                <button type="button" id="saveRoleBtn" data-role-id="" class="${PRIMARY_BUTTON}">
                    Create role
                </button>
            </div>`);
        wireRoleSave();
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
            if (!await tkConfirm(`Members keep their accounts but lose the capabilities granted by "${role ? role.name : ''}".`, { title: 'Delete this role?', confirmText: 'Delete role', danger: true })) return;
            try {
                await staffFetch(`/roles/${id}/`, { method: 'DELETE' });
                toast.success('Role deleted.');
                await Promise.all([loadRoles(), loadPeople(), loadActivity()]);
            } catch (e) { toastApiError(e, 'The role could not be deleted.'); }
        }

        if (button.dataset.action === 'edit-role') {
            const role = ROLES.find(r => r.id === id);
            if (!role) return;
            openStaffModal(`Edit ${role.name}`, `
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-2">Role name</label>
                        <input type="text" id="roleName" value="${escapeHtml(role.name)}"
                            class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                    </div>
                    <div>${capabilityCheckboxes(role.capabilities)}</div>
                    <button type="button" id="saveRoleBtn" data-role-id="${escapeHtml(role.id)}" class="${PRIMARY_BUTTON}">
                        Save changes
                    </button>
                </div>`);
            wireRoleSave();
        }

        if (button.dataset.action === 'edit-person') {
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
