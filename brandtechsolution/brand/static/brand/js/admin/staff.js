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

// Each paginated list: where its rows go, which button reveals its next page,
// how one row renders, and what to show when it is empty.
const STAFF_LISTS = {
    invitations: {
        path: '/invitations/',
        container: 'staffInvitesList',
        more: 'staffInvitesMore',
        empty: '',
        row: inv => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center gap-4">
            <div>
                <div class="text-white font-medium">${escapeHtml(inv.email)}</div>
                <div class="text-xs text-gray-500">Invited &middot; ${escapeHtml(inv.roles.join(', ') || 'no roles')}</div>
            </div>
            <div class="flex items-center gap-3">
                <span class="text-xs px-2 py-1 rounded bg-yellow-500/10 text-yellow-400">Pending</span>
                <button type="button" data-action="resend-invite" data-id="${escapeHtml(inv.id)}"
                    class="text-xs text-brand-blue hover:text-blue-400">Resend</button>
                <button type="button" data-action="revoke-invite" data-id="${escapeHtml(inv.id)}"
                    class="text-xs text-red-400 hover:text-red-300">Revoke</button>
            </div>
        </div>`,
    },
    people: {
        path: '/people/',
        container: 'staffPeopleList',
        more: 'staffPeopleMore',
        empty: '<p class="text-gray-500 text-sm">Nobody yet.</p>',
        row: p => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center gap-4">
            <div>
                <div class="text-white font-medium">${escapeHtml(p.username)}</div>
                <div class="text-xs text-gray-500">${p.is_superuser
                    ? 'All capabilities &middot; superusers bypass every check'
                    : escapeHtml(p.roles.join(', ') || 'no roles')}</div>
            </div>
            <div class="flex items-center gap-3">
                ${p.is_superuser ? '<span class="text-xs px-2 py-1 rounded bg-purple-500/10 text-purple-400">Superuser</span>' : ''}
                <span class="text-xs px-2 py-1 rounded ${p.is_active ? 'bg-green-500/10 text-green-400' : 'bg-gray-500/10 text-gray-400'}">
                    ${p.is_active ? 'Active' : 'Deactivated'}
                </span>
                <button type="button" data-action="edit-person" data-id="${escapeHtml(p.id)}"
                    class="text-xs text-brand-blue hover:text-blue-400">Edit roles</button>
            </div>
        </div>`,
    },
    activity: {
        path: '/activity/',
        container: 'staffActivityList',
        more: 'staffActivityMore',
        empty: '<p class="text-gray-500 text-sm">Nothing yet.</p>',
        row: entry => `
        <div class="bg-dark-card border border-dark-border rounded-lg px-4 py-3 flex justify-between items-center gap-4">
            <span class="text-sm text-gray-300">${escapeHtml(entry.summary)}</span>
            <span class="text-xs text-gray-600 whitespace-nowrap">
                ${escapeHtml(new Date(entry.created_at).toLocaleString())}
            </span>
        </div>`,
    },
};

// The `next` cursor for each list, so Load more knows where to continue.
const STAFF_CURSORS = { invitations: null, people: null, activity: null };

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
        // Roles first and awaited: both modals build their checkboxes from
        // ROLES / CAPABILITY_GROUPS, and their buttons stay disabled until
        // those are populated.
        await loadRoles();
        if (inviteBtn) inviteBtn.disabled = false;
        if (newRoleBtn) newRoleBtn.disabled = false;
        await Promise.all([loadPeople(), loadActivity()]);
    } catch (e) {
        console.error(e);
        alert(`Could not load staff data: ${e.message}`);
    }
}

async function loadPeople() {
    await Promise.all([loadList('invitations'), loadList('people')]);
}

async function loadActivity() {
    await loadList('activity');
}

async function loadRoles() {
    const container = document.getElementById('staffRolesList');
    if (!container) return;

    ROLES = await staffFetchAll('/roles/');
    container.innerHTML = ROLES.map(role => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center gap-4">
            <div>
                <div class="text-white font-medium">${escapeHtml(role.name)}</div>
                <div class="text-xs text-gray-500">
                    ${role.member_count} member${role.member_count === 1 ? '' : 's'}
                    &middot; ${role.capabilities.length} capabilit${role.capabilities.length === 1 ? 'y' : 'ies'}
                </div>
            </div>
            <div class="flex items-center gap-3">
                <button type="button" data-action="edit-role" data-id="${escapeHtml(role.id)}"
                    class="text-xs text-brand-blue hover:text-blue-400">Edit</button>
                <button type="button" data-action="delete-role" data-id="${escapeHtml(role.id)}"
                    class="text-xs text-red-400 hover:text-red-300">Delete</button>
            </div>
        </div>`).join('') || '<p class="text-gray-500 text-sm">No roles yet.</p>';
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

function roleCheckboxes(selectedNames) {
    return ROLES.map(role => `
        <label class="flex items-center gap-2 py-1 text-sm text-gray-300">
            <input type="checkbox" value="${escapeHtml(role.id)}"
                ${selectedNames.includes(role.name) ? 'checked' : ''}
                class="role-box rounded bg-[#06090F] border-dark-border">
            ${escapeHtml(role.name)}
        </label>`).join('') || '<p class="text-xs text-gray-500">No roles exist yet.</p>';
}

function openStaffModal(title, bodyHtml) {
    // textContent, not innerHTML: the title carries a role or user name.
    document.getElementById('staffModalTitle').textContent = title;
    document.getElementById('staffModalBody').innerHTML = bodyHtml;
    const modal = document.getElementById('staffModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
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

function wireRoleSave() {
    // The button is re-created by every openStaffModal() call (innerHTML is
    // replaced), so this listener cannot stack on a stale element.
    document.getElementById('saveRoleBtn').addEventListener('click', async (event) => {
        const roleId = event.currentTarget.dataset.roleId;
        const name = document.getElementById('roleName').value.trim();
        if (!name) { alert('Give the role a name.'); return; }
        const payload = JSON.stringify({ name, capabilities: selectedCapabilities() });
        try {
            if (roleId) {
                await staffFetch(`/roles/${roleId}/`, { method: 'PUT', body: payload });
            } else {
                await staffFetch('/roles/', { method: 'POST', body: payload });
            }
            closeStaffModal();
            await Promise.all([loadRoles(), loadPeople(), loadActivity()]);
        } catch (e) { alert(`Could not save the role: ${e.message}`); }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('staff');
    if (!section) return;   // user lacks manage_staff; the section was not rendered

    document.getElementById('staffModalClose').addEventListener('click', closeStaffModal);

    section.querySelectorAll('.staff-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            section.querySelectorAll('.staff-tab').forEach(t => {
                t.classList.remove('text-white', 'border-brand-blue');
                t.classList.add('text-gray-400', 'border-transparent');
            });
            tab.classList.add('text-white', 'border-brand-blue');
            tab.classList.remove('text-gray-400', 'border-transparent');

            section.querySelectorAll('.staff-pane').forEach(p => p.classList.add('hidden'));
            const paneId = {
                people: 'staffPeople', roles: 'staffRoles', activity: 'staffActivity',
            }[tab.dataset.tab];
            document.getElementById(paneId).classList.remove('hidden');
        });
    });

    document.getElementById('inviteBtn').addEventListener('click', () => {
        openStaffModal('Invite person', `
            <div class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-gray-400 mb-2">Email address</label>
                    <input type="email" id="inviteEmail" required
                        class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-white focus:outline-none focus:border-brand-blue">
                </div>
                <div>
                    <label class="block text-sm font-medium text-gray-400 mb-2">Roles</label>
                    ${roleCheckboxes([])}
                </div>
                <button type="button" id="sendInviteBtn"
                    class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
                    Send invitation
                </button>
            </div>`);

        document.getElementById('sendInviteBtn').addEventListener('click', async () => {
            const email = document.getElementById('inviteEmail').value.trim();
            if (!email) { alert('Enter an email address.'); return; }
            try {
                await staffFetch('/invitations/', {
                    method: 'POST',
                    body: JSON.stringify({ email, role_ids: selectedRoleIds() }),
                });
                closeStaffModal();
                await Promise.all([loadPeople(), loadActivity()]);
                alert('Invitation sent.');
            } catch (e) { alert(`Could not send the invitation: ${e.message}`); }
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
                <button type="button" id="saveRoleBtn" data-role-id=""
                    class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
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
                alert(`Could not load more: ${e.message}`);
            } finally {
                button.disabled = false;
            }
        }

        // Every mutation below writes an audit entry, so each refreshes the
        // Activity pane as well as the list it changed - otherwise a user
        // watching Activity sees nothing until they re-enter the section.
        if (button.dataset.action === 'revoke-invite') {
            if (!confirm('Revoke this invitation? The link stops working.')) return;
            try {
                await staffFetch(`/invitations/${id}/`, { method: 'DELETE' });
                await Promise.all([loadPeople(), loadActivity()]);
            } catch (e) { alert(`Could not revoke: ${e.message}`); }
        }

        if (button.dataset.action === 'resend-invite') {
            try {
                await staffFetch(`/invitations/${id}/resend/`, { method: 'POST' });
                await loadActivity();
                alert('Invitation resent.');
            } catch (e) { alert(`Could not resend: ${e.message}`); }
        }

        if (button.dataset.action === 'delete-role') {
            const role = ROLES.find(r => r.id === id);
            if (!confirm(`Delete the role "${role ? role.name : ''}"? Members keep their accounts but lose these capabilities.`)) return;
            try {
                await staffFetch(`/roles/${id}/`, { method: 'DELETE' });
                await Promise.all([loadRoles(), loadPeople(), loadActivity()]);
            } catch (e) { alert(`Could not delete: ${e.message}`); }
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
                    <button type="button" id="saveRoleBtn" data-role-id="${escapeHtml(role.id)}"
                        class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
                        Save changes
                    </button>
                </div>`);
            wireRoleSave();
        }

        if (button.dataset.action === 'edit-person') {
            let person;
            try {
                person = await staffFetch(`/people/${id}/`);
            } catch (e) { alert(`Could not open: ${e.message}`); return; }

            openStaffModal(`Edit ${person.username}`, `
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium text-gray-400 mb-2">Roles</label>
                        ${roleCheckboxes(person.roles)}
                    </div>
                    <label class="flex items-center gap-2 text-sm text-gray-300">
                        <input type="checkbox" id="personActive" ${person.is_active ? 'checked' : ''}
                            class="rounded bg-[#06090F] border-dark-border">
                        Account active
                    </label>
                    <button type="button" id="savePersonBtn"
                        class="w-full bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-3 rounded-lg">
                        Save changes
                    </button>
                </div>`);

            document.getElementById('savePersonBtn').addEventListener('click', async () => {
                try {
                    await staffFetch(`/people/${id}/`, {
                        method: 'PATCH',
                        body: JSON.stringify({
                            role_ids: selectedRoleIds(),
                            is_active: document.getElementById('personActive').checked,
                        }),
                    });
                    closeStaffModal();
                    await Promise.all([loadPeople(), loadRoles(), loadActivity()]);
                } catch (e) { alert(`Could not save: ${e.message}`); }
            });
        }
    });
});
