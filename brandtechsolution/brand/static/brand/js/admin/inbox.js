let currentInboxStatus = 'all';
let inboxSearchQuery = '';
let inboxSearchTimeout = null;
let currentInboxItems = [];

function getCsrfToken() {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, 10) === ('csrftoken=')) {
                cookieValue = decodeURIComponent(cookie.substring(10));
                break;
            }
        }
    }
    return cookieValue || '';
}

async function loadInbox() {
    try {
        const queryParams = new URLSearchParams();
        if (currentInboxStatus && currentInboxStatus !== 'all') {
            queryParams.append('status', currentInboxStatus);
        }
        if (inboxSearchQuery) {
            queryParams.append('q', inboxSearchQuery);
        }

        const url = `${API_BASE}/messaging/inquiries/?${queryParams.toString()}`;
        const res = await fetch(url, { credentials: 'same-origin' });
        
        if (res.status === 403) {
            document.getElementById('inboxList').innerHTML = `
                <div class="text-center py-12 bg-dark-card border border-dark-border rounded-xl text-red-400">
                    <i class="fas fa-lock text-4xl mb-3 opacity-60"></i>
                    <p class="font-bold">Access Restricted</p>
                    <p class="text-xs text-gray-400 mt-1">You require the 'view_inbox' capability to access communications.</p>
                </div>`;
            return;
        }

        const items = await res.json();
        currentInboxItems = items;
        const container = document.getElementById('inboxList');

        // Update Unread Badge
        const unreadCount = items.filter(i => i.status === 'new').length;
        const unreadBadge = document.getElementById('unreadBadge');
        if (unreadBadge) {
            if (unreadCount > 0) {
                unreadBadge.textContent = `${unreadCount} Unread`;
                unreadBadge.classList.remove('hidden');
            } else {
                unreadBadge.classList.add('hidden');
            }
        }

        if (!items.length) {
            container.innerHTML = `
                <div class="text-center py-12 bg-dark-card border border-dark-border rounded-xl text-gray-500">
                    <i class="fas fa-inbox text-4xl mb-3 opacity-40"></i>
                    <p>No messages match your current filter.</p>
                </div>`;
            return;
        }

        const badge = {
            new: 'text-brand-green bg-green-900/30 border border-green-500/30',
            read: 'text-gray-300 bg-white/10 border border-white/10',
            replied: 'text-brand-blue bg-blue-900/30 border border-blue-500/30',
            archived: 'text-gray-500 bg-white/5 border border-white/5'
        };

        container.innerHTML = items.map(i => {
            const initial = (i.name || 'U').charAt(0).toUpperCase();
            const isMailgunDirect = i.message.includes('[Inbound Mailgun Email');
            
            return `
            <div class="bg-dark-card border ${i.status === 'new' ? 'border-brand-blue/40 shadow-blue-500/5' : 'border-dark-border'} p-6 rounded-xl shadow-lg transition-all duration-300">
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-white/5">
                    <div class="flex items-center gap-3">
                        <div class="w-11 h-11 rounded-full ${isMailgunDirect ? 'bg-purple-900/30 border border-purple-500/40 text-purple-400' : 'bg-brand-blue/20 border border-brand-blue/30 text-brand-blue'} font-bold text-lg flex items-center justify-center shrink-0">
                            ${escapeHtml(initial)}
                        </div>
                        <div>
                            <h3 class="text-lg font-bold text-white flex items-center gap-2">
                                ${escapeHtml(i.name)}
                                ${isMailgunDirect ? '<span class="text-[10px] px-2 py-0.5 bg-purple-900/40 border border-purple-500/30 text-purple-300 rounded font-mono">Mailgun Direct</span>' : ''}
                            </h3>
                            <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-400 mt-0.5">
                                <a href="mailto:${escapeHtml(i.email)}" class="hover:text-brand-blue transition-colors flex items-center gap-1.5">
                                    <i class="fas fa-envelope text-brand-blue"></i> ${escapeHtml(i.email)}
                                </a>
                                ${i.phone ? `
                                <a href="tel:${escapeHtml(i.phone)}" class="hover:text-brand-green transition-colors flex items-center gap-1.5">
                                    <i class="fas fa-phone text-brand-green"></i> ${escapeHtml(i.phone)}
                                </a>` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="flex items-center gap-3 self-end md:self-auto">
                        <span class="text-xs font-semibold px-2.5 py-1 rounded-full uppercase ${badge[i.status] || 'text-gray-300 bg-white/5'}">
                            ${escapeHtml(i.status)}
                        </span>
                        <span class="text-gray-500 text-xs flex items-center gap-1">
                            <i class="far fa-clock"></i> ${escapeHtml(new Date(i.created_at).toLocaleString())}
                        </span>
                    </div>
                </div>

                <div class="mt-4 p-4 rounded-lg bg-[#06090F]/90 border border-white/5 text-gray-200 text-sm leading-relaxed whitespace-pre-line font-normal">
                    ${escapeHtml(i.message)}
                </div>

                <!-- Action Toolbar -->
                <div class="mt-4 pt-3 border-t border-white/5 flex flex-wrap justify-between items-center gap-3">
                    <div class="flex items-center gap-2">
                        ${i.status === 'new' ? `
                        <button onclick="markInquiryRead(${i.id})" class="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-gray-300 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5">
                            <i class="fas fa-check text-green-400"></i> Mark Read
                        </button>` : ''}
                        ${i.status !== 'archived' ? `
                        <button onclick="archiveInquiry(${i.id})" class="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-gray-200 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5">
                            <i class="fas fa-archive"></i> Archive
                        </button>` : ''}
                    </div>
                    <button onclick="openReplyModal(${i.id}, '${escapeHtml(i.name)}', '${escapeHtml(i.email)}')" class="px-4 py-1.5 bg-brand-blue hover:bg-blue-600 text-white rounded-lg text-xs font-bold transition-all shadow-md flex items-center gap-1.5">
                        <i class="fas fa-reply"></i> Reply via Email
                    </button>
                </div>
            </div>`;
        }).join('');
    } catch (e) { console.error(e); }
}

function filterInboxStatus(status) {
    currentInboxStatus = status;
    const tabs = document.querySelectorAll('.inbox-tab');
    tabs.forEach(tab => {
        if (tab.getAttribute('data-status') === status) {
            tab.className = 'inbox-tab px-3.5 py-1.5 rounded-lg text-xs font-medium bg-brand-blue text-white shadow-sm transition-all';
        } else {
            tab.className = 'inbox-tab px-3.5 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-white hover:bg-white/5 transition-all';
        }
    });
    loadInbox();
}

function handleInboxSearch() {
    clearTimeout(inboxSearchTimeout);
    inboxSearchTimeout = setTimeout(() => {
        const input = document.getElementById('inboxSearch');
        inboxSearchQuery = (input.value || '').trim();
        loadInbox();
    }, 300);
}

function openReplyModal(id, name, email) {
    const modal = document.getElementById('replyModal');
    document.getElementById('replyInquiryId').value = id;
    document.getElementById('replyToLabel').textContent = `To: ${name} <${email}>`;
    document.getElementById('replySubject').value = `Re: Technical Inquiry - Teklora Solutions`;
    document.getElementById('replyMessageBody').value = '';
    modal.classList.remove('hidden');
}

function closeReplyModal() {
    document.getElementById('replyModal').classList.add('hidden');
}

async function submitReply(event) {
    event.preventDefault();
    const id = document.getElementById('replyInquiryId').value;
    const message = document.getElementById('replyMessageBody').value;
    const btn = document.getElementById('replySubmitBtn');

    if (!message.trim()) return;

    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Dispatching...`;

    try {
        const res = await fetch(`${API_BASE}/messaging/inquiries/${id}/reply/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ message })
        });
        
        const data = await res.json();
        if (res.ok && data.ok) {
            closeReplyModal();
            loadInbox();
        } else {
            alert(data.error || 'Failed to dispatch reply.');
        }
    } catch (e) {
        console.error(e);
        alert('Communication error while sending reply.');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fas fa-paper-plane"></i> Dispatch Reply`;
    }
}

async function markInquiryRead(id) {
    try {
        await fetch(`${API_BASE}/messaging/inquiries/${id}/mark_read/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() }
        });
        loadInbox();
    } catch (e) { console.error(e); }
}

async function archiveInquiry(id) {
    try {
        await fetch(`${API_BASE}/messaging/inquiries/${id}/archive/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() }
        });
        loadInbox();
    } catch (e) { console.error(e); }
}
