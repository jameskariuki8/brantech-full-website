/* Mail client for the panel's Inbox section. Every value that came from an
 * email is untrusted: text goes through escapeHtml(), and HTML bodies only
 * ever render inside a sandboxed iframe with scripts off and a CSP that
 * blocks everything but inline styles and remote images. */
(function () {
    'use strict';

    const MAIL_API = `${API_BASE}/messaging/mail`;
    const state = {
        boxes: null,
        box: 'me',
        filter: 'inbox',
        person: '',
        q: '',
        page: 1,
        threads: [],
        openId: null,
        open: null,
    };

    const $ = (id) => document.getElementById(id);

    function post(url, body) {
        return fetchJson(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify(body || {}),
        });
    }

    function when(iso) {
        const d = new Date(iso);
        const now = new Date();
        if (d.toDateString() === now.toDateString()) {
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        const opts = { month: 'short', day: 'numeric' };
        if (d.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
        return d.toLocaleDateString([], opts);
    }

    function fullWhen(iso) {
        const d = new Date(iso);
        const opts = { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' };
        if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
        return d.toLocaleString([], opts);
    }

    function initial(text) {
        return escapeHtml(((text || '?').trim().charAt(0) || '?').toUpperCase());
    }

    // --- mailboxes ------------------------------------------------------

    function boxEntries() {
        const b = state.boxes;
        const entries = [];
        if (b.me) {
            entries.push({ key: 'me', label: 'Inbox', icon: 'fa-inbox', unread: b.me.unread, group: b.me.address });
            entries.push({ key: 'sent', label: 'Sent', icon: 'fa-paper-plane', group: b.me.address });
        }
        b.shared.forEach((s) => entries.push({
            key: s.mailbox,
            label: s.mailbox === 'other' ? 'Unmatched' : `${s.mailbox}@`,
            icon: s.mailbox === 'other' ? 'fa-question' : 'fa-users',
            unread: s.unread,
            group: 'Shared',
            title: s.address,
        }));
        if (b.all_mail) {
            entries.push({ key: 'all', label: 'All mail', icon: 'fa-eye', group: 'Oversight' });
        }
        return entries;
    }

    // The mailboxes live in the sidebar while Mail is open. They reuse the
    // panel nav's classes, so the collapsed sidebar shows them as icons.
    function renderBoxes() {
        const entries = boxEntries();
        let lastGroup = null;
        $('mailBoxes').innerHTML = entries.map((e) => {
            const header = e.group !== lastGroup
                ? `<div class="sidebar-header pt-4 pb-1 px-4 text-[11px] font-semibold uppercase tracking-wider text-gray-600 truncate">${escapeHtml(e.group)}</div>`
                : '';
            lastGroup = e.group;
            const active = e.key === state.box;
            return `${header}
                <button type="button" data-box="${escapeHtml(e.key)}" title="${escapeHtml(e.title || e.label)}"
                    class="nav-item w-full flex items-center px-4 py-2.5 text-sm font-medium rounded-lg text-left transition-colors ${active ? 'active' : 'text-gray-400 hover:text-white hover:bg-white/5'}">
                    <i class="fas ${e.icon} w-6 text-center mr-3"></i>
                    <span class="nav-label flex-1 truncate">${escapeHtml(e.label)}</span>
                    ${e.unread ? `<span class="nav-label text-[11px] font-semibold ml-2 ${active ? '' : 'text-brand-blue'}">${e.unread}</span>` : ''}
                </button>`;
        }).join('');

        const current = entries.find((e) => e.key === state.box);
        $('mailBoxTitle').textContent = current ? current.label : 'Mail';
        const b = state.boxes;
        const shared = b.shared.find((x) => x.mailbox === state.box);
        $('mailBoxAddress').textContent = (state.box === 'me' || state.box === 'sent') && b.me ? b.me.address
            : shared && shared.mailbox !== 'other' ? shared.address
            : '';

        const person = $('mailPerson');
        const showPerson = state.box === 'all';
        person.classList.toggle('hidden', !showPerson);
        $('mailRefresh').classList.toggle('ml-auto', !showPerson);
        if (showPerson && !person.options.length) {
            person.innerHTML = '<option value="">Everyone</option>' + b.people.map((p) =>
                `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
        }

        $('mailNoHandle').classList.toggle('hidden', !!b.me);
        $('mailComposeBtn').disabled = !(b.me || b.shared.some((x) => x.can_send));

        const totalUnread = (b.me ? b.me.unread : 0) + b.shared.reduce((n, x) => n + x.unread, 0);
        updateNavBadge(totalUnread);
    }

    function updateNavBadge(count) {
        const link = $('nav-inbox');
        if (!link) return;
        let badge = $('navInboxBadge');
        if (!badge) {
            badge = document.createElement('span');
            badge.id = 'navInboxBadge';
            badge.className = 'ml-auto text-[11px] font-semibold bg-brand-blue text-white rounded-full px-2 py-0.5';
            link.appendChild(badge);
        }
        badge.textContent = count > 99 ? '99+' : String(count);
        badge.classList.toggle('hidden', !count);
    }

    function closeMobileDrawer() {
        if (window.innerWidth >= 1024) return;
        $('sidebar')?.classList.add('-translate-x-full');
        $('mobileOverlay')?.classList.add('hidden');
    }

    function exitMail() {
        const section = lastPanelSection || 'dashboard';
        showSection(section);
        history.pushState(null, '', `/admin-panel/?section=${encodeURIComponent(section)}`);
    }

    function selectBox(key) {
        closeMobileDrawer();
        if (key === state.box) return;
        state.box = key;
        state.page = 1;
        state.filter = 'inbox';
        closeThread();
        renderBoxes();
        renderFilters();
        loadThreads();
    }

    // --- conversation list ------------------------------------------------

    function renderFilters() {
        const isSent = state.box === 'sent';
        $('mailFilters').querySelectorAll('.mail-filter').forEach((btn) => {
            const active = btn.dataset.filter === state.filter;
            btn.classList.toggle('hidden', isSent);
            btn.className = `mail-filter px-3 py-1 rounded-md text-xs font-medium ${isSent ? 'hidden' : ''} ${active ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-white'}`;
        });
    }

    function threadRow(t) {
        const active = t.id === state.openId;
        const who = t.counterpart_name || t.counterpart_email || '(unknown)';
        const mailboxChip = state.box === 'all'
            ? `<span class="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-gray-400 truncate max-w-[9rem]">${escapeHtml(t.owner ? t.owner : `${t.mailbox}@`)}</span>`
                + (t.deleted ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400">Deleted</span>' : '')
            : '';
        return `
            <li>
                <button type="button" data-thread="${t.id}"
                    class="w-full text-left px-4 py-3 flex gap-3 transition-colors ${active ? 'bg-brand-blue/10' : 'hover:bg-white/[0.03]'}">
                    <span class="w-9 h-9 shrink-0 rounded-full bg-brand-blue/15 text-brand-blue font-semibold text-sm flex items-center justify-center">${initial(who)}</span>
                    <span class="flex-1 min-w-0">
                        <span class="flex items-baseline gap-2">
                            <span class="flex-1 truncate text-sm ${t.unread ? 'font-semibold text-white' : 'text-gray-300'}">${escapeHtml(who)}</span>
                            <span class="text-[11px] shrink-0 ${t.unread ? 'text-brand-blue font-semibold' : 'text-gray-500'}">${escapeHtml(when(t.last_message_at))}</span>
                        </span>
                        <span class="flex items-center gap-2 mt-0.5">
                            ${t.unread ? '<span class="w-1.5 h-1.5 rounded-full bg-brand-blue shrink-0"></span>' : ''}
                            <span class="flex-1 truncate text-[13px] ${t.unread ? 'text-gray-100' : 'text-gray-400'}">${escapeHtml(t.subject || '(no subject)')}</span>
                            ${t.message_count > 1 ? `<span class="text-[11px] text-gray-500 shrink-0">${t.message_count}</span>` : ''}
                            ${t.has_sent ? '<i class="fas fa-reply text-[10px] text-gray-600 shrink-0" title="Replied"></i>' : ''}
                        </span>
                        <span class="flex items-center gap-2 mt-0.5">
                            ${mailboxChip}
                            <span class="flex-1 truncate text-xs text-gray-500">${escapeHtml(t.snippet)}</span>
                        </span>
                    </span>
                </button>
            </li>`;
    }

    function renderThreads() {
        const list = $('mailThreadList');
        if (!state.threads.length) {
            const empty = state.q ? 'Nothing matches your search.'
                : state.filter === 'archived' ? 'Nothing archived.'
                : state.filter === 'unread' ? 'You are all caught up.'
                : state.filter === 'spam' ? 'No spam.'
                : state.box === 'sent' ? 'Nothing sent yet.'
                : 'No mail here yet.';
            list.innerHTML = `<li class="px-6 py-16 text-center text-sm text-gray-600">${escapeHtml(empty)}</li>`;
            return;
        }
        list.innerHTML = state.threads.map(threadRow).join('');
    }

    async function loadThreads(append) {
        if (!state.boxes || (!state.boxes.me && (state.box === 'me' || state.box === 'sent'))) {
            state.threads = [];
            renderThreads();
            return;
        }
        const params = new URLSearchParams({ box: state.box, page: state.page });
        if (state.filter === 'archived') params.set('archived', '1');
        if (state.filter === 'unread') params.set('unread', '1');
        if (state.filter === 'spam') params.set('spam', '1');
        if (state.q) params.set('q', state.q);
        if (state.box === 'all' && state.person) params.set('person', state.person);
        try {
            const data = await fetchJson(`${MAIL_API}/threads/?${params}`);
            state.threads = append ? state.threads.concat(data.results) : data.results;
            $('mailMore').classList.toggle('hidden', !data.next);
            renderThreads();
        } catch (err) {
            toastApiError(err, 'Could not load mail.');
        }
    }

    async function refreshBoxes() {
        try {
            state.boxes = await fetchJson(`${MAIL_API}/mailboxes/`);
        } catch (err) {
            toastApiError(err, 'Could not load your mailboxes.');
            return false;
        }
        const keys = boxEntries().map((e) => e.key);
        if (!keys.includes(state.box)) state.box = keys[0] || 'me';
        renderBoxes();
        return true;
    }

    // --- reader -----------------------------------------------------------

    const IFRAME_HEAD = '<!doctype html><html><head><meta charset="utf-8">'
        + '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src https: data:; style-src \'unsafe-inline\'; font-src https: data:">'
        + '<base target="_blank">'
        + '<style>html,body{margin:0}body{padding:16px;font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;color:#1f2937;background:#fff;overflow-wrap:anywhere}'
        + 'img{max-width:100%;height:auto}table{max-width:100%}'
        + 'body:not(.show-quoted) .gmail_quote,body:not(.show-quoted) blockquote[type=cite],body:not(.show-quoted) #appendonsend,body:not(.show-quoted) .yahoo_quoted{display:none}</style>'
        + '</head><body>';

    function fitFrame(frame) {
        try {
            // The body, not the document: a document is never shorter than
            // the iframe itself, so it would only ever grow.
            frame.style.height = `${Math.ceil(frame.contentDocument.body.getBoundingClientRect().height) + 2}px`;
        } catch (e) { /* cross-origin never happens with allow-same-origin */ }
    }

    // Plain-text replies carry the whole history under "On ... wrote:" or
    // ">" lines. Hide it behind a toggle, as mail clients do.
    function splitQuoted(text) {
        const lines = (text || '').split('\n');
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i].trim();
            if (/^On .+wrote:$/.test(line) || /^-{2,}\s*Original Message\s*-{2,}$/i.test(line)
                || (line.startsWith('>') && lines.slice(i).every((l) => !l.trim() || l.trim().startsWith('>')))) {
                return [lines.slice(0, i).join('\n').trimEnd(), lines.slice(i).join('\n')];
            }
        }
        return [text || '', ''];
    }

    function linkify(escaped) {
        return escaped.replace(/\bhttps?:\/\/[^\s<]+[^\s<.,;:!?)\]'"]/g,
            (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-brand-blue hover:underline break-all">${url}</a>`);
    }

    function addressLine(list) {
        return (list || []).map((a) => escapeHtml(a)).join(', ');
    }

    function messageCard(m, index, total) {
        const outgoing = m.direction === 'out';
        const who = m.from_name || m.from_email;
        const hasHtml = !outgoing && m.body_html;
        let body;
        if (hasHtml) {
            body = `<div class="rounded-lg overflow-hidden bg-white"><iframe data-body="${index}" title="Message body" class="w-full block min-h-[80px]" sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer"></iframe></div>
                <button type="button" data-quoted-html="${index}" class="mt-2 text-xs text-gray-500 hover:text-white"><i class="fas fa-ellipsis"></i> Show quoted text</button>`;
        } else {
            const [main, quoted] = splitQuoted(m.body_text);
            body = `<div class="text-sm text-gray-200 whitespace-pre-wrap break-words leading-relaxed">${linkify(escapeHtml(main))}</div>`
                + (quoted ? `<button type="button" data-quoted="${index}" class="mt-2 px-2 rounded bg-white/5 text-gray-400 hover:text-white text-xs" title="Show quoted text">•••</button>
                    <div data-quoted-body="${index}" class="hidden mt-2 pl-3 border-l-2 border-white/10 text-sm text-gray-500 whitespace-pre-wrap break-words">${linkify(escapeHtml(quoted))}</div>` : '');
        }
        const attachments = (m.attachments || []).length
            ? `<div class="mt-3 flex flex-wrap gap-2">${m.attachments.map((a) =>
                `<span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-400" title="Attachments are not stored yet"><i class="fas fa-paperclip mr-1"></i>${escapeHtml(a.name)}</span>`).join('')}</div>`
            : '';
        const failed = m.status === 'failed' ? '<span class="text-xs text-red-400 ml-2">Not delivered</span>' : '';
        return `
            <article class="rounded-xl border ${outgoing ? 'border-brand-blue/20 bg-brand-blue/[0.04]' : 'border-white/5 bg-[#06090F]/60'} p-4">
                <header class="flex items-start gap-3 mb-3">
                    <span class="w-9 h-9 shrink-0 rounded-full ${outgoing ? 'bg-brand-blue text-white' : 'bg-white/10 text-gray-200'} font-semibold text-sm flex items-center justify-center">${initial(who)}</span>
                    <div class="flex-1 min-w-0">
                        <p class="text-sm text-white truncate"><span class="font-semibold">${escapeHtml(who)}</span>
                            ${m.from_name ? `<span class="text-gray-500 text-xs">&lt;${escapeHtml(m.from_email)}&gt;</span>` : ''}${failed}</p>
                        <p class="text-xs text-gray-500 truncate">to ${addressLine(m.to) || 'you'}${m.cc && m.cc.length ? ` · cc ${addressLine(m.cc)}` : ''}${outgoing && m.sent_by ? ` · sent by ${escapeHtml(m.sent_by)}` : ''}</p>
                    </div>
                    <time class="text-xs text-gray-500 shrink-0" title="${escapeHtml(new Date(m.created_at).toLocaleString())}" datetime="${escapeHtml(m.created_at)}">${escapeHtml(fullWhen(m.created_at))}</time>
                </header>
                ${body}
                ${attachments}
            </article>`;
    }

    function showReaderOnMobile(show) {
        // Below lg only one of list and reader is visible at a time.
        $('mailListPane').classList.toggle('hidden', show);
        $('mailListPane').classList.toggle('lg:flex', true);
        $('mailReader').classList.toggle('hidden', !show);
        $('mailReader').classList.toggle('flex', show);
    }

    function closeThread() {
        state.openId = null;
        state.open = null;
        $('mailThread').classList.add('hidden');
        $('mailThread').classList.remove('flex');
        $('mailEmpty').classList.remove('hidden');
        showReaderOnMobile(false);
        $('mailReader').classList.add('hidden', 'lg:flex');
    }

    function renderThread(t) {
        $('mailEmpty').classList.add('hidden');
        $('mailThread').classList.remove('hidden');
        $('mailThread').classList.add('flex');
        $('mailThreadSubject').textContent = t.subject || '(no subject)';
        const owner = t.owner ? `${t.owner}'s mailbox` : `shared · ${t.address}`;
        $('mailThreadMeta').textContent = `${t.messages.length} message${t.messages.length === 1 ? '' : 's'} · ${owner}`;

        $('mailThreadActions').classList.toggle('hidden', !t.can_act);
        const archiveBtn = $('mailArchiveBtn');
        archiveBtn.title = t.archived ? 'Move to inbox' : 'Archive';
        archiveBtn.setAttribute('aria-label', archiveBtn.title);
        archiveBtn.innerHTML = `<i class="fas ${t.archived ? 'fa-inbox' : 'fa-box-archive'}"></i>`;
        const spamBtn = $('mailSpamBtn');
        spamBtn.title = t.spam ? 'Not spam' : 'Mark as spam';
        spamBtn.setAttribute('aria-label', spamBtn.title);
        spamBtn.innerHTML = `<i class="fas ${t.spam ? 'fa-circle-check' : 'fa-ban'}"></i>`;
        archiveBtn.classList.toggle('hidden', t.spam);

        const container = $('mailMessages');
        container.innerHTML = t.messages.map((m, i) => messageCard(m, i, t.messages.length)).join('');
        t.messages.forEach((m, i) => {
            const frame = container.querySelector(`iframe[data-body="${i}"]`);
            if (!frame) return;
            frame.addEventListener('load', () => fitFrame(frame));
            frame.srcdoc = IFRAME_HEAD + m.body_html + '</body></html>';
        });
        container.scrollTop = container.scrollHeight;

        $('mailReplyBox').classList.toggle('hidden', !t.can_act);
        $('mailReadOnly').classList.toggle('hidden', t.can_act);
        if (t.can_act) {
            const lastIn = [...t.messages].reverse().find((m) => m.direction === 'in');
            const to = lastIn ? lastIn.from_email : t.counterpart_email;
            $('mailReplyTo').textContent = `Reply to ${to}`;
            $('mailReplyFrom').textContent = `From ${t.address}`;
        } else if (t.deleted) {
            $('mailReadOnly').textContent = 'Deleted from its mailbox. Kept here for oversight.';
        } else {
            $('mailReadOnly').textContent = t.owner
                ? `Read-only: this is ${t.owner}'s mailbox. Only they can reply or file it.`
                : 'Read-only: replying from a shared mailbox needs the handle_inquiries capability.';
        }
    }

    async function openThread(id) {
        state.openId = id;
        renderThreads();
        showReaderOnMobile(true);
        try {
            const t = await fetchJson(`${MAIL_API}/threads/${id}/`);
            if (state.openId !== id) return;
            state.open = t;
            renderThread(t);
            const row = state.threads.find((x) => x.id === id);
            if (row && row.unread && !t.unread) {
                row.unread = false;
                renderThreads();
                refreshBoxes();
            }
        } catch (err) {
            toastApiError(err, 'Could not open that conversation.');
        }
    }

    async function setState(changes) {
        const t = state.open;
        if (!t) return;
        try {
            await post(`${MAIL_API}/threads/${t.id}/state/`, changes);
            if ('archived' in changes) {
                toast.success(changes.archived ? 'Archived.' : 'Moved to inbox.');
            }
            closeThread();
            await refreshBoxes();
            loadThreads();
        } catch (err) {
            toastApiError(err);
        }
    }

    async function toggleSpam() {
        const t = state.open;
        if (!t) return;
        if (!t.spam) {
            const ok = await tkConfirm(
                `Future mail from ${t.counterpart_email || 'this sender'} will go straight to Spam, and their contact-form messages will be dropped.`,
                { title: 'Mark as spam?', confirmText: 'Mark as spam', danger: true });
            if (!ok) return;
        }
        try {
            await post(`${MAIL_API}/threads/${t.id}/state/`, { spam: !t.spam });
            toast.success(t.spam ? 'Moved back to the inbox. The sender is unblocked.' : 'Marked as spam. The sender is blocked.');
            closeThread();
            await refreshBoxes();
            loadThreads();
        } catch (err) {
            toastApiError(err);
        }
    }

    async function deleteThread() {
        const t = state.open;
        if (!t) return;
        const ok = await tkConfirm('It disappears from this mailbox. Administrators can still see it under All mail.',
            { title: 'Delete this conversation?', confirmText: 'Delete', danger: true });
        if (!ok) return;
        try {
            await fetchJson(`${MAIL_API}/threads/${t.id}/delete/`, {
                method: 'POST', headers: { 'X-CSRFToken': CSRF_TOKEN },
            });
            toast.success('Deleted.');
            closeThread();
            await refreshBoxes();
            loadThreads();
        } catch (err) {
            toastApiError(err);
        }
    }

    async function withBusy(form, work) {
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
            await work();
        } catch (err) {
            toastApiError(err, 'The message was not sent.');
        } finally {
            button.disabled = false;
        }
    }

    // --- compose ----------------------------------------------------------

    function openCompose() {
        const form = $('mailComposeForm');
        const options = [];
        if (state.boxes.me) options.push(`<option value="me">${escapeHtml(state.boxes.me.address)}</option>`);
        state.boxes.shared.filter((s) => s.can_send).forEach((s) =>
            options.push(`<option value="${escapeHtml(s.mailbox)}">${escapeHtml(s.address)} (shared)</option>`));
        form.elements.from.innerHTML = options.join('');
        if (state.boxes.shared.some((s) => s.mailbox === state.box && s.can_send)) {
            form.elements.from.value = state.box;
        }
        const modal = $('mailComposeModal');
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        form.elements.to.focus();
    }

    function closeCompose(reset) {
        const modal = $('mailComposeModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        if (reset) $('mailComposeForm').reset();
    }

    // --- wiring -----------------------------------------------------------

    let wired = false;
    function wire() {
        if (wired) return;
        wired = true;

        $('mailBoxes').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-box]');
            if (btn) selectBox(btn.dataset.box);
        });
        $('mailExit').addEventListener('click', exitMail);
        $('mailFilters').addEventListener('click', (e) => {
            const btn = e.target.closest('.mail-filter');
            if (!btn || btn.dataset.filter === state.filter) return;
            state.filter = btn.dataset.filter;
            state.page = 1;
            renderFilters();
            loadThreads();
        });
        $('mailPerson').addEventListener('change', (e) => {
            state.person = e.target.value;
            state.page = 1;
            loadThreads();
        });
        $('mailRefresh').addEventListener('click', async () => {
            state.page = 1;
            await refreshBoxes();
            loadThreads();
        });
        let searchTimer = null;
        $('mailSearch').addEventListener('input', (e) => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                state.q = e.target.value.trim();
                state.page = 1;
                loadThreads();
            }, 300);
        });
        $('mailMore').addEventListener('click', () => {
            state.page += 1;
            loadThreads(true);
        });
        $('mailThreadList').addEventListener('click', (e) => {
            const btn = e.target.closest('[data-thread]');
            if (btn) openThread(Number(btn.dataset.thread));
        });
        $('mailBack').addEventListener('click', closeThread);
        $('mailArchiveBtn').addEventListener('click', () => setState({ archived: !state.open.archived }));
        $('mailUnreadBtn').addEventListener('click', () => setState({ unread: true }));
        $('mailSpamBtn').addEventListener('click', toggleSpam);
        $('mailDeleteBtn').addEventListener('click', deleteThread);

        $('mailMessages').addEventListener('click', (e) => {
            const textToggle = e.target.closest('[data-quoted]');
            if (textToggle) {
                $('mailMessages').querySelector(`[data-quoted-body="${textToggle.dataset.quoted}"]`).classList.toggle('hidden');
                return;
            }
            const htmlToggle = e.target.closest('[data-quoted-html]');
            if (htmlToggle) {
                const frame = $('mailMessages').querySelector(`iframe[data-body="${htmlToggle.dataset.quotedHtml}"]`);
                const body = frame.contentDocument.body;
                body.classList.toggle('show-quoted');
                htmlToggle.innerHTML = body.classList.contains('show-quoted')
                    ? '<i class="fas fa-ellipsis"></i> Hide quoted text'
                    : '<i class="fas fa-ellipsis"></i> Show quoted text';
                fitFrame(frame);
            }
        });

        $('mailReplyForm').addEventListener('submit', (e) => {
            e.preventDefault();
            const form = e.target;
            const t = state.open;
            withBusy(form, async () => {
                await post(`${MAIL_API}/threads/${t.id}/reply/`, { body: form.elements.body.value });
                form.reset();
                toast.success('Sent.');
                await openThread(t.id);
                loadThreads();
            });
        });

        $('mailComposeBtn').addEventListener('click', () => {
            closeMobileDrawer();
            openCompose();
        });
        $('mailComposeModal').addEventListener('click', (e) => {
            if (e.target.id === 'mailComposeModal' || e.target.closest('[data-compose-close]')) closeCompose(false);
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !$('mailComposeModal').classList.contains('hidden')) closeCompose(false);
        });
        $('mailComposeForm').addEventListener('submit', (e) => {
            e.preventDefault();
            const form = e.target;
            withBusy(form, async () => {
                const sent = await post(`${MAIL_API}/compose/`, {
                    from: form.elements.from.value,
                    to: form.elements.to.value,
                    cc: form.elements.cc.value,
                    subject: form.elements.subject.value,
                    body: form.elements.body.value,
                });
                closeCompose(true);
                toast.success('Sent.');
                state.box = sent.owner ? 'sent' : sent.mailbox;
                state.filter = 'inbox';
                state.page = 1;
                await refreshBoxes();
                renderFilters();
                await loadThreads();
                openThread(sent.id);
            });
        });
    }

    async function loadInbox() {
        wire();
        renderFilters();
        if (await refreshBoxes()) loadThreads();
    }

    window.loadInbox = loadInbox;

    // Keep the sidebar badge current on every panel page load, not only
    // when the Inbox section is open.
    document.addEventListener('DOMContentLoaded', () => {
        if (!$('inbox')) return;
        fetchJson(`${MAIL_API}/unread/`).then((d) => updateNavBadge(d.unread)).catch(() => {});
    });
})();
