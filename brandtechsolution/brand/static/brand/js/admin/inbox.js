async function loadInbox() {
    try {
        const res = await fetch(`${API_BASE}/messaging/inquiries/`, { credentials: 'same-origin' });
        const items = await res.json();
        const container = document.getElementById('inboxList');
        if (!items.length) {
            container.innerHTML = `<div class="text-center py-10 text-gray-600">No messages yet.</div>`;
            return;
        }
        const badge = { new: 'text-brand-green bg-green-900/20', read: 'text-gray-300 bg-white/5', replied: 'text-brand-blue bg-blue-900/20', archived: 'text-gray-500 bg-white/5' };
        container.innerHTML = items.map(i => `
            <div class="bg-dark-card border border-dark-border p-5 rounded-lg">
                <div class="flex justify-between items-start gap-4">
                    <div class="flex-1">
                        <div class="flex items-center gap-2 mb-2">
                            <span class="text-xs font-bold px-2 py-1 rounded uppercase ${badge[i.status] || ''}">${i.status}</span>
                            <span class="text-gray-500 text-xs">${new Date(i.created_at).toLocaleString()}</span>
                        </div>
                        <h3 class="text-lg font-bold text-white">${i.name} <span class="text-sm text-gray-400 font-normal">&lt;${i.email}&gt;</span></h3>
                        ${i.phone ? `<p class="text-xs text-gray-500 mb-1">${i.phone}</p>` : ''}
                        <p class="text-gray-300 text-sm whitespace-pre-line mt-2">${i.message}</p>
                    </div>
                    <div class="flex flex-col gap-2">
                        <button onclick="setInquiryStatus(${i.id}, 'read')" class="p-2 text-gray-400 hover:bg-white/5 rounded" title="Mark read"><i class="fas fa-envelope-open"></i></button>
                        <button onclick="setInquiryStatus(${i.id}, 'replied')" class="p-2 text-brand-blue hover:bg-blue-900/30 rounded" title="Mark replied"><i class="fas fa-reply"></i></button>
                        <button onclick="setInquiryStatus(${i.id}, 'archived')" class="p-2 text-gray-400 hover:bg-white/5 rounded" title="Archive"><i class="fas fa-box-archive"></i></button>
                        <button onclick="deleteInquiry(${i.id})" class="p-2 text-red-400 hover:bg-red-900/30 rounded" title="Delete"><i class="fas fa-trash"></i></button>
                    </div>
                </div>
            </div>`).join('');
    } catch (e) { console.error(e); }
}

async function setInquiryStatus(id, status) {
    await fetch(`${API_BASE}/messaging/inquiries/${id}/`, {
        method: 'PATCH', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
        body: JSON.stringify({ status }),
    });
    loadInbox();
}

async function deleteInquiry(id) {
    if (!confirm('Delete this message?')) return;
    await fetch(`${API_BASE}/messaging/inquiries/${id}/`, {
        method: 'DELETE', credentials: 'same-origin', headers: { 'X-CSRFToken': CSRF_TOKEN },
    });
    loadInbox();
}
