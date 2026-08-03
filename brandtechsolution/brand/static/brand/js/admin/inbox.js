async function loadInbox() {
    try {
        const res = await fetch(`${API_BASE}/messaging/inquiries/`, { credentials: 'same-origin' });
        const items = await res.json();
        const container = document.getElementById('inboxList');
        if (!items.length) {
            container.innerHTML = `<div class="text-center py-12 bg-dark-card border border-dark-border rounded-xl text-gray-500"><i class="fas fa-inbox text-4xl mb-3 opacity-40"></i><p>No messages received yet.</p></div>`;
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
            return `
            <div class="bg-dark-card border border-dark-border p-6 rounded-xl shadow-lg transition-all duration-300">
                <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-white/5">
                    <div class="flex items-center gap-3">
                        <div class="w-11 h-11 rounded-full bg-brand-blue/20 border border-brand-blue/30 text-brand-blue font-bold text-lg flex items-center justify-center shrink-0">
                            ${escapeHtml(initial)}
                        </div>
                        <div>
                            <h3 class="text-lg font-bold text-white flex items-center gap-2">
                                ${escapeHtml(i.name)}
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
            </div>`;
        }).join('');
    } catch (e) { console.error(e); }
}
