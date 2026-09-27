/* The signed-in user's own profile, opened from the header dropdown.
 * Loaded by admin_base.html, so it cannot lean on core.js: pages like
 * appointments extend the base without loading the panel's scripts. */
(function () {
    'use strict';

    const ME_URL = '/api/staff/me/';
    const PASSWORD_URL = '/api/staff/me/password/';

    const modal = document.getElementById('profileModal');
    const openBtn = document.getElementById('myProfileBtn');
    const profileForm = document.getElementById('profileForm');
    const passwordForm = document.getElementById('passwordForm');
    if (!modal || !openBtn || !profileForm || !passwordForm) return;

    function csrfToken() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
    }

    function send(url, method, body) {
        return fetchJson(url, {
            method,
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
            body: JSON.stringify(body),
        });
    }

    function show() {
        modal.classList.remove('hidden');
        modal.classList.add('flex');
    }

    function hide() {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        passwordForm.reset();
    }

    function fill(me) {
        document.getElementById('profileEmail').textContent = me.email || me.username;
        profileForm.first_name.value = me.first_name || '';
        profileForm.last_name.value = me.last_name || '';
        profileForm.phone.value = me.phone || '';
        const headerName = document.getElementById('headerUserName');
        if (headerName) {
            const full = `${me.first_name || ''} ${me.last_name || ''}`.trim();
            headerName.textContent = full || me.username;
        }
    }

    async function withBusy(form, work) {
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
            await work();
        } catch (err) {
            toastApiError(err);
        } finally {
            button.disabled = false;
        }
    }

    openBtn.addEventListener('click', async () => {
        document.getElementById('userDropdownMenu')?.classList.add('hidden');
        try {
            fill(await fetchJson(ME_URL));
            show();
        } catch (err) {
            toastApiError(err, 'Could not load your profile.');
        }
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal || e.target.closest('[data-profile-close]')) hide();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.classList.contains('hidden')) hide();
    });

    profileForm.addEventListener('submit', (e) => {
        e.preventDefault();
        withBusy(profileForm, async () => {
            fill(await send(ME_URL, 'PATCH', {
                first_name: profileForm.first_name.value.trim(),
                last_name: profileForm.last_name.value.trim(),
                phone: profileForm.phone.value.trim(),
            }));
            toast.success('Profile saved.');
        });
    });

    passwordForm.addEventListener('submit', (e) => {
        e.preventDefault();
        withBusy(passwordForm, async () => {
            await send(PASSWORD_URL, 'POST', {
                current_password: passwordForm.current_password.value,
                new_password: passwordForm.new_password.value,
            });
            passwordForm.reset();
            toast.success('Password changed.');
        });
    });
})();
