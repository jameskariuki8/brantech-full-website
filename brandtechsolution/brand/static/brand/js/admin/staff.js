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

async function staffFetch(path, options = {}) {
    const response = await fetch(`${STAFF_API}${path}`, {
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

async function loadStaff() {
    try {
        if (!CAPABILITY_GROUPS.length) {
            CAPABILITY_GROUPS = await staffFetch('/capabilities/');
        }
        await Promise.all([loadPeople(), loadRoles(), loadActivity()]);
    } catch (e) {
        console.error(e);
        alert(`Could not load staff data: ${e.message}`);
    }
}

async function loadPeople() {
    const container = document.getElementById('staffPeopleList');
    if (!container) return;

    const [people, invitations] = await Promise.all([
        staffFetch('/people/'),
        staffFetch('/invitations/'),
    ]);

    const inviteRows = invitations.results.map(inv => `
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
        </div>`).join('');

    const peopleRows = people.results.map(p => `
        <div class="bg-dark-card border border-dark-border rounded-lg p-4 flex justify-between items-center gap-4">
            <div>
                <div class="text-white font-medium">${escapeHtml(p.username)}</div>
                <div class="text-xs text-gray-500">${escapeHtml(p.roles.join(', ') || 'no roles')}</div>
            </div>
            <div class="flex items-center gap-3">
                ${p.is_superuser ? '<span class="text-xs px-2 py-1 rounded bg-purple-500/10 text-purple-400">Superuser</span>' : ''}
                <span class="text-xs px-2 py-1 rounded ${p.is_active ? 'bg-green-500/10 text-green-400' : 'bg-gray-500/10 text-gray-400'}">
                    ${p.is_active ? 'Active' : 'Deactivated'}
                </span>
                <button type="button" data-action="edit-person" data-id="${escapeHtml(p.id)}"
                    class="text-xs text-brand-blue hover:text-blue-400">Edit roles</button>
            </div>
        </div>`).join('');

    container.innerHTML = (inviteRows + peopleRows) ||
        '<p class="text-gray-500 text-sm">Nobody yet.</p>';
}

async function loadRoles() {
    const container = document.getElementById('staffRolesList');
    if (!container) return;

    const data = await staffFetch('/roles/');
    ROLES = data.results;
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

async function loadActivity() {
    const container = document.getElementById('staffActivityList');
    if (!container) return;

    const data = await staffFetch('/activity/');
    container.innerHTML = data.results.map(entry => `
        <div class="bg-dark-card border border-dark-border rounded-lg px-4 py-3 flex justify-between items-center gap-4">
            <span class="text-sm text-gray-300">${escapeHtml(entry.summary)}</span>
            <span class="text-xs text-gray-600 whitespace-nowrap">
                ${escapeHtml(new Date(entry.created_at).toLocaleString())}
            </span>
        </div>`).join('') || '<p class="text-gray-500 text-sm">Nothing yet.</p>';
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
            await Promise.all([loadRoles(), loadPeople()]);
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
                await loadPeople();
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

        if (button.dataset.action === 'revoke-invite') {
            if (!confirm('Revoke this invitation? The link stops working.')) return;
            try {
                await staffFetch(`/invitations/${id}/`, { method: 'DELETE' });
                await loadPeople();
            } catch (e) { alert(`Could not revoke: ${e.message}`); }
        }

        if (button.dataset.action === 'resend-invite') {
            try {
                await staffFetch(`/invitations/${id}/resend/`, { method: 'POST' });
                alert('Invitation resent.');
            } catch (e) { alert(`Could not resend: ${e.message}`); }
        }

        if (button.dataset.action === 'delete-role') {
            const role = ROLES.find(r => r.id === id);
            if (!confirm(`Delete the role "${role ? role.name : ''}"? Members keep their accounts but lose these capabilities.`)) return;
            try {
                await staffFetch(`/roles/${id}/`, { method: 'DELETE' });
                await Promise.all([loadRoles(), loadPeople()]);
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
