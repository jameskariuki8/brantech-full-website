// GitHub Manager: pick repositories to import as projects.
//
// Lost in the redesign -- the section's markup survived in admin_panel.html
// but its sidebar link and these two functions did not, so importing a repo
// meant a Django shell. Restored here, with toasts in place of alert() and
// every GitHub-supplied string escaped: a repository description is text
// someone else wrote.

async function loadGithubRepos() {
    const list = document.getElementById('githubList');
    const loading = document.getElementById('githubLoading');
    if (!list) return;
    list.innerHTML = '';
    loading.classList.remove('hidden');
    try {
        const data = await fetchJson(`${API_BASE}/github/repos/`);
        const repos = (data && data.results) || [];
        if (!repos.length) {
            list.innerHTML = `<div class="text-center py-10 text-gray-600">No repositories visible to the configured GitHub token.</div>`;
            return;
        }
        list.innerHTML = repos.map(repo => `
            <label class="bg-dark-card border ${repo.is_synced ? 'border-brand-green/50' : 'border-dark-border'} p-5 rounded-lg flex flex-col md:flex-row justify-between items-start md:items-center gap-4 hover:border-brand-blue/30 transition-colors cursor-pointer">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-2 flex-wrap">
                        <h3 class="text-lg font-bold ${repo.is_synced ? 'text-brand-green' : 'text-white'}">${escapeHtml(repo.name)}</h3>
                        ${repo.is_private ? '<span class="text-xs font-bold text-yellow-500 px-2 py-1 bg-yellow-900/20 rounded"><i class="fas fa-lock mr-1"></i>Private</span>' : ''}
                        <span class="text-xs font-bold text-gray-400 px-2 py-1 bg-gray-800 rounded uppercase">${escapeHtml(repo.role)}</span>
                        ${repo.is_synced ? '<span class="text-xs font-bold text-brand-green px-2 py-1 bg-green-900/20 rounded"><i class="fas fa-check mr-1"></i>Synced</span>' : ''}
                    </div>
                    <p class="text-sm text-gray-400 line-clamp-1">${escapeHtml(repo.description)}</p>
                </div>
                <input type="checkbox" value="${Number(repo.id)}"
                    class="github-repo-check w-6 h-6 bg-[#06090F] border-dark-border rounded text-brand-blue cursor-pointer">
            </label>
        `).join('');
    } catch (e) {
        console.error(e);
        list.innerHTML = `<div class="text-center py-10 text-gray-600">Could not load repositories.</div>`;
        toastApiError(e, 'Could not load repositories from GitHub.');
    } finally {
        loading.classList.add('hidden');
    }
}

async function syncSelectedRepos() {
    const repo_ids = Array.from(document.querySelectorAll('.github-repo-check:checked'))
        .map(cb => parseInt(cb.value, 10));
    if (!repo_ids.length) {
        toast.warning('Select at least one repository to sync.');
        return;
    }

    const btn = document.getElementById('syncBtn');
    const original = btn.innerHTML;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i>Syncing...`;
    btn.disabled = true;
    try {
        const data = await fetchJson(`${API_BASE}/github/sync/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ repo_ids }),
        });
        const n = data.synced_count;
        toast.success(`Synced ${n} ${n === 1 ? 'repository' : 'repositories'}.`);
        if (data.error_count) {
            toast.warning(`${data.error_count} could not be synced.`,
                { detail: (data.errors || []).join('\n') });
        }
        loadGithubRepos();
    } catch (e) {
        console.error(e);
        toastApiError(e, 'Could not sync the selected repositories.');
    } finally {
        btn.innerHTML = original;
        btn.disabled = false;
    }
}
