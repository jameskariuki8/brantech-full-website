// ============================================================
// GitHub Manager & Repository Hub Controller
// ============================================================

let currentGithubRepos = [];
let currentGithubFilter = 'all';
let activeInspectorRepo = null;

/**
 * Fetch repositories from GitHub API and initialize dashboard.
 */
async function loadGithubRepos(forceRefresh = false) {
    const list = document.getElementById('githubList');
    const loading = document.getElementById('githubLoading');
    const errorBox = document.getElementById('githubError');
    const emptyBox = document.getElementById('githubEmpty');
    const refreshBtn = document.getElementById('githubRefreshBtn');

    if (!list) return;

    if (errorBox) errorBox.classList.add('hidden');
    if (emptyBox) emptyBox.classList.add('hidden');
    list.innerHTML = '';
    loading.classList.remove('hidden');

    if (refreshBtn && forceRefresh) {
        refreshBtn.innerHTML = `<i class="fas fa-spinner fa-spin mr-2 text-xs"></i>Loading...`;
        refreshBtn.disabled = true;
    }

    try {
        const data = await fetchJson(`${API_BASE}/github/repos/`);
        currentGithubRepos = (data && data.results) || [];

        // Update Overview Metric Cards & Filters
        updateGithubDashboardMetrics(currentGithubRepos);

        if (!currentGithubRepos.length) {
            if (emptyBox) emptyBox.classList.remove('hidden');
            return;
        }

        // Render repositories with active filters and sorting
        filterGithubRepos();

        if (forceRefresh) {
            toast.success(`Loaded ${currentGithubRepos.length} repositories from GitHub.`);
        }
    } catch (e) {
        console.error('GitHub Repos Fetch Error:', e);
        if (errorBox) {
            errorBox.classList.remove('hidden');
            const msg = document.getElementById('githubErrorMessage');
            if (msg) msg.textContent = e.message || 'Could not reach GitHub API. Check your GITHUB_ACCESS_TOKEN.';
        }
        toastApiError(e, 'Could not load repositories from GitHub.');
    } finally {
        loading.classList.add('hidden');
        if (refreshBtn) {
            refreshBtn.innerHTML = `<i class="fas fa-rotate mr-2 text-xs"></i>Reload`;
            refreshBtn.disabled = false;
        }
    }
}

/**
 * Calculate and render top overview statistics.
 */
function updateGithubDashboardMetrics(repos) {
    const totalCount = repos.length;
    const syncedRepos = repos.filter(r => r.is_synced);
    const syncedCount = syncedRepos.length;
    const unsyncedCount = totalCount - syncedCount;
    const ownedCount = repos.filter(r => r.role === 'owner').length;
    const collabCount = repos.filter(r => r.role === 'collaborator').length;

    // Calculate total commits tracked across synced projects
    const totalCommits = syncedRepos.reduce((acc, r) => {
        const count = (r.project && r.project.commit_count) ? r.project.commit_count : 0;
        return acc + count;
    }, 0);

    // Update Dashboard Cards
    const elTotal = document.getElementById('statTotalRepos');
    const elOwned = document.getElementById('statOwnedCount');
    const elCollab = document.getElementById('statCollabCount');
    const elSynced = document.getElementById('statSyncedProjects');
    const elPercentage = document.getElementById('statSyncPercentage');
    const elCommits = document.getElementById('statTotalCommits');

    if (elTotal) elTotal.textContent = totalCount;
    if (elOwned) elOwned.textContent = `${ownedCount} owned`;
    if (elCollab) elCollab.textContent = `${collabCount} collab`;
    if (elSynced) elSynced.textContent = syncedCount;
    if (elPercentage) {
        const pct = totalCount > 0 ? Math.round((syncedCount / totalCount) * 100) : 0;
        elPercentage.textContent = `${pct}% of total (${syncedCount}/${totalCount})`;
    }
    if (elCommits) elCommits.textContent = totalCommits.toLocaleString();

    // Update Filter Tab Badges
    const bAll = document.getElementById('filterCountAll');
    const bSynced = document.getElementById('filterCountSynced');
    const bUnsynced = document.getElementById('filterCountUnsynced');
    const bOwned = document.getElementById('filterCountOwned');
    const bCollab = document.getElementById('filterCountCollab');

    if (bAll) bAll.textContent = `(${totalCount})`;
    if (bSynced) bSynced.textContent = `(${syncedCount})`;
    if (bUnsynced) bUnsynced.textContent = `(${unsyncedCount})`;
    if (bOwned) bOwned.textContent = `(${ownedCount})`;
    if (bCollab) bCollab.textContent = `(${collabCount})`;
}

/**
 * Filter and sort repositories based on user search, active filter tab, and sort selection.
 */
function filterGithubRepos() {
    const list = document.getElementById('githubList');
    const emptyBox = document.getElementById('githubEmpty');
    const searchInput = document.getElementById('githubSearchInput');
    const clearBtn = document.getElementById('githubSearchClear');
    const sortSelect = document.getElementById('githubSortSelect');

    if (!list) return;

    const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
    if (clearBtn) clearBtn.classList.toggle('hidden', query.length === 0);

    let filtered = [...currentGithubRepos];

    // Filter by Tab
    if (currentGithubFilter === 'synced') {
        filtered = filtered.filter(r => r.is_synced);
    } else if (currentGithubFilter === 'unsynced') {
        filtered = filtered.filter(r => !r.is_synced);
    } else if (currentGithubFilter === 'owner') {
        filtered = filtered.filter(r => r.role === 'owner');
    } else if (currentGithubFilter === 'collaborator') {
        filtered = filtered.filter(r => r.role === 'collaborator');
    }

    // Filter by Search Query
    if (query) {
        filtered = filtered.filter(r => {
            const name = (r.name || '').toLowerCase();
            const fullName = (r.full_name || '').toLowerCase();
            const desc = (r.description || '').toLowerCase();
            const lang = (r.language || '').toLowerCase();
            const projTitle = (r.project && r.project.title ? r.project.title : '').toLowerCase();
            return name.includes(query) || fullName.includes(query) || desc.includes(query) || lang.includes(query) || projTitle.includes(query);
        });
    }

    // Sort
    const sortVal = sortSelect ? sortSelect.value : 'synced_first';
    filtered.sort((a, b) => {
        if (sortVal === 'synced_first') {
            if (a.is_synced !== b.is_synced) return a.is_synced ? -1 : 1;
            return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase());
        }
        if (sortVal === 'name_asc') {
            return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase());
        }
        if (sortVal === 'commits_desc') {
            const aCommits = (a.project && a.project.commit_count) || 0;
            const bCommits = (b.project && b.project.commit_count) || 0;
            return bCommits - aCommits;
        }
        if (sortVal === 'updated_desc') {
            return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
        }
        return 0;
    });

    if (!filtered.length) {
        list.innerHTML = '';
        if (emptyBox) emptyBox.classList.remove('hidden');
        updateSelectedCount();
        return;
    }

    if (emptyBox) emptyBox.classList.add('hidden');
    list.innerHTML = filtered.map(repo => renderGithubRepoCard(repo)).join('');
    updateSelectedCount();
}

/**
 * Render an individual repository card HTML.
 */
function renderGithubRepoCard(repo) {
    const isSynced = repo.is_synced;
    const project = repo.project || null;
    const roleUpper = (repo.role || 'owner').toUpperCase();
    const isOwner = repo.role === 'owner';
    const lang = repo.language || null;
    const commitsCount = (project && project.commit_count) || 0;

    // Relative last synced time
    let syncTimeText = '';
    if (isSynced && project && project.last_synced_at) {
        syncTimeText = formatRelativeTime(new Date(project.last_synced_at));
    }

    // Language color helper
    const langColor = getLanguageColor(lang);

    return `
        <div class="bg-[#0A101D] border ${isSynced ? 'border-emerald-500/30' : 'border-white/10'} hover:border-brand-blue/40 rounded-xl p-5 transition-all group flex flex-col md:flex-row items-start md:items-center justify-between gap-5 shadow-sm">
            
            <!-- Left & Details Area -->
            <div class="flex items-start gap-4 flex-1 min-w-0">
                <!-- Checkbox for batch sync -->
                <div class="pt-1">
                    <input type="checkbox" value="${Number(repo.id)}" data-synced="${isSynced ? 'true' : 'false'}"
                        class="github-repo-check w-5 h-5 bg-[#06090F] border-white/20 rounded text-brand-blue cursor-pointer focus:ring-0 focus:ring-offset-0"
                        onchange="updateSelectedCount()">
                </div>

                <div class="flex-1 min-w-0">
                    <!-- Badges Row -->
                    <div class="flex items-center gap-2 mb-2 flex-wrap text-xs">
                        <span class="font-bold px-2 py-0.5 rounded ${isOwner ? 'bg-blue-900/20 text-brand-blue border border-blue-500/20' : 'bg-gray-800 text-gray-300'} uppercase">
                            ${escapeHtml(roleUpper)}
                        </span>

                        ${repo.is_private ? `
                            <span class="font-bold px-2 py-0.5 rounded bg-yellow-900/20 text-yellow-400 border border-yellow-500/20">
                                <i class="fas fa-lock mr-1 text-[10px]"></i>Private
                            </span>
                        ` : `
                            <span class="font-bold px-2 py-0.5 rounded bg-sky-900/20 text-sky-400 border border-sky-500/20">
                                <i class="fas fa-globe mr-1 text-[10px]"></i>Public
                            </span>
                        `}

                        ${isSynced ? `
                            <span class="font-bold px-2.5 py-0.5 rounded-full bg-emerald-950/60 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 shadow-sm shadow-emerald-500/10">
                                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                                Synced Project
                            </span>
                        ` : `
                            <span class="font-medium px-2 py-0.5 rounded bg-gray-800 text-gray-400">
                                Not Synced
                            </span>
                        `}

                        ${lang ? `
                            <span class="font-medium px-2 py-0.5 rounded bg-[#111827] text-gray-300 border border-white/5 flex items-center gap-1.5">
                                <span class="w-2 h-2 rounded-full" style="background-color: ${langColor};"></span>
                                ${escapeHtml(lang)}
                            </span>
                        ` : ''}

                        ${repo.stargazers_count > 0 ? `
                            <span class="text-gray-400"><i class="fas fa-star text-amber-400 mr-1"></i>${repo.stargazers_count}</span>
                        ` : ''}
                    </div>

                    <!-- Repository Name & External Link -->
                    <div class="flex items-center gap-2.5 flex-wrap">
                        <h3 class="text-lg font-bold ${isSynced ? 'text-emerald-400' : 'text-white'} group-hover:text-brand-blue transition-colors">
                            ${escapeHtml(repo.name)}
                        </h3>
                        <a href="${escapeHtml(safeUrl(repo.html_url))}" target="_blank" rel="noopener noreferrer"
                            class="text-xs text-gray-500 hover:text-white transition-colors" title="View on GitHub">
                            <i class="fas fa-arrow-up-right-from-square"></i>
                        </a>
                    </div>

                    <!-- Description -->
                    <p class="text-sm text-gray-400 mt-1 line-clamp-2 leading-relaxed">
                        ${escapeHtml(repo.description || 'No description provided on GitHub.')}
                    </p>

                    <!-- Connected Project Info Footer (if Synced) -->
                    ${isSynced && project ? `
                        <div class="mt-3 pt-3 border-t border-white/5 flex flex-wrap items-center gap-4 text-xs text-gray-400">
                            <span class="text-gray-300 flex items-center gap-1.5">
                                <i class="fas fa-folder text-brand-blue"></i>
                                Portfolio Title: <strong class="text-white">${escapeHtml(project.title)}</strong>
                            </span>
                            <span class="flex items-center gap-1.5">
                                <i class="fas fa-code-commit text-purple-400"></i>
                                <strong>${commitsCount}</strong> commits tracked
                            </span>
                            ${syncTimeText ? `
                                <span class="text-gray-500 flex items-center gap-1">
                                    <i class="fas fa-clock text-gray-600"></i>
                                    Synced ${escapeHtml(syncTimeText)}
                                </span>
                            ` : ''}
                            ${project.project_url ? `
                                <a href="${escapeHtml(safeUrl(project.project_url))}" target="_blank" rel="noopener noreferrer"
                                    class="text-brand-blue hover:underline font-medium flex items-center gap-1">
                                    <i class="fas fa-link"></i>Live Demo
                                </a>
                            ` : ''}
                        </div>
                    ` : ''}
                </div>
            </div>

            <!-- Right Action Buttons -->
            <div class="flex items-center gap-2 self-end md:self-center shrink-0 flex-wrap">
                <!-- Inspector Drawer Button -->
                <button onclick="openGithubInspector(${repo.id})"
                    class="bg-[#111827] hover:bg-[#1f2937] text-gray-200 hover:text-white border border-white/10 px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-colors">
                    <i class="fab fa-readme text-brand-blue"></i>
                    <span>README & Details</span>
                </button>

                <!-- Single Sync / Re-sync Button -->
                <button onclick="syncSingleRepo(${repo.id}, this)"
                    class="${isSynced ? 'bg-emerald-950/40 hover:bg-emerald-900/60 text-emerald-300 border border-emerald-500/30' : 'bg-brand-blue hover:bg-blue-600 text-white'} px-3.5 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all">
                    <i class="fas fa-sync-alt text-xs"></i>
                    <span>${isSynced ? 'Re-sync' : 'Sync'}</span>
                </button>

                <!-- Edit Project Button (if Synced) -->
                ${isSynced && project ? `
                    <button onclick="editProjectFromGithub(${project.id})"
                        class="p-2 text-gray-400 hover:text-emerald-400 hover:bg-emerald-950/30 rounded-lg transition-colors border border-transparent hover:border-emerald-500/20"
                        title="Edit Project in Portfolio CMS">
                        <i class="fas fa-pen-to-square"></i>
                    </button>
                ` : ''}
            </div>

        </div>
    `;
}

/**
 * Handle tab filtering switch.
 */
function setGithubFilter(filterType, element) {
    currentGithubFilter = filterType;
    document.querySelectorAll('.github-filter-tab').forEach(btn => {
        btn.classList.remove('text-white', 'bg-white/10');
        btn.classList.add('text-gray-400');
    });
    if (element) {
        element.classList.remove('text-gray-400');
        element.classList.add('text-white', 'bg-white/10');
    }
    filterGithubRepos();
}

/**
 * Clear search input.
 */
function clearGithubSearch() {
    const input = document.getElementById('githubSearchInput');
    if (input) {
        input.value = '';
        filterGithubRepos();
    }
}

/**
 * Select All / Deselect All Toggle.
 */
function toggleSelectAllRepos(checkbox) {
    const checked = checkbox.checked;
    document.querySelectorAll('.github-repo-check').forEach(cb => {
        cb.checked = checked;
    });
    updateSelectedCount();
}

/**
 * Update the "Sync Selected (X)" button state and counter badge.
 */
function updateSelectedCount() {
    const checkedBoxes = document.querySelectorAll('.github-repo-check:checked');
    const count = checkedBoxes.length;
    const syncBtn = document.getElementById('syncBtn');
    const badge = document.getElementById('selectedCountBadge');
    const selectAllCheckbox = document.getElementById('selectAllCheckbox');

    if (badge) {
        badge.textContent = count;
        badge.classList.toggle('hidden', count === 0);
    }

    if (syncBtn) {
        syncBtn.disabled = count === 0;
    }

    const allBoxes = document.querySelectorAll('.github-repo-check');
    if (selectAllCheckbox && allBoxes.length > 0) {
        selectAllCheckbox.checked = (count === allBoxes.length);
    }
}

/**
 * Sync a single repository.
 */
async function syncSingleRepo(repoId, btnElement = null) {
    let originalHtml = '';
    if (btnElement) {
        originalHtml = btnElement.innerHTML;
        btnElement.innerHTML = `<i class="fas fa-spinner fa-spin mr-1.5"></i>Syncing...`;
        btnElement.disabled = true;
    }

    try {
        const data = await fetchJson(`${API_BASE}/github/sync/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ repo_ids: [repoId] }),
        });

        if (data.synced_count > 0) {
            toast.success(`Repository successfully synced as a TekLora project!`);
        } else if (data.error_count > 0) {
            toast.error(`Sync failed: ${(data.errors || []).join(', ')}`);
        }

        // Refresh list
        await loadGithubRepos(false);

        // If inspector is open on this repo, refresh it too
        if (activeInspectorRepo && activeInspectorRepo.id === repoId) {
            const updated = currentGithubRepos.find(r => r.id === repoId);
            if (updated) openGithubInspector(repoId);
        }
    } catch (e) {
        console.error('Single Sync Error:', e);
        toastApiError(e, 'Could not sync the repository.');
    } finally {
        if (btnElement) {
            btnElement.innerHTML = originalHtml;
            btnElement.disabled = false;
        }
    }
}

/**
 * Batch sync selected repositories.
 */
async function syncSelectedRepos() {
    const repo_ids = Array.from(document.querySelectorAll('.github-repo-check:checked'))
        .map(cb => parseInt(cb.value, 10));

    if (!repo_ids.length) {
        toast.warning('Select at least one repository to sync.');
        return;
    }

    const btn = document.getElementById('syncBtn');
    const original = btn.innerHTML;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i>Syncing ${repo_ids.length}...`;
    btn.disabled = true;

    try {
        const data = await fetchJson(`${API_BASE}/github/sync/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ repo_ids }),
        });

        const n = data.synced_count;
        toast.success(`Successfully synced ${n} ${n === 1 ? 'repository' : 'repositories'}.`);

        if (data.error_count) {
            toast.warning(`${data.error_count} could not be synced.`, { detail: (data.errors || []).join('\n') });
        }

        await loadGithubRepos(false);
    } catch (e) {
        console.error('Batch Sync Error:', e);
        toastApiError(e, 'Could not sync the selected repositories.');
    } finally {
        btn.innerHTML = original;
        btn.disabled = false;
    }
}

/**
 * Sync all repositories that are already tracked as projects.
 */
async function syncAllTrackedRepos() {
    const tracked = currentGithubRepos.filter(r => r.is_synced).map(r => r.id);
    if (!tracked.length) {
        toast.warning('No synced repositories are currently tracked to re-sync.');
        return;
    }

    const btn = document.getElementById('syncAllTrackedBtn');
    const original = btn.innerHTML;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-2 text-xs"></i>Syncing ${tracked.length}...`;
    btn.disabled = true;

    try {
        const data = await fetchJson(`${API_BASE}/github/sync/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
            body: JSON.stringify({ repo_ids: tracked }),
        });

        toast.success(`Re-synced ${data.synced_count} tracked projects.`);
        await loadGithubRepos(false);
    } catch (e) {
        console.error('Tracked Re-sync Error:', e);
        toastApiError(e, 'Could not re-sync tracked repositories.');
    } finally {
        btn.innerHTML = original;
        btn.disabled = false;
    }
}

// ============================================================
// Slide-over Modal & Inspector (README, Commits, Project Data)
// ============================================================

/**
 * Open the Slide-over Inspector for a repository.
 */
async function openGithubInspector(repoId, initialTab = 'readme') {
    const repo = currentGithubRepos.find(r => r.id === repoId);
    if (!repo) return;

    activeInspectorRepo = repo;
    const modal = document.getElementById('githubInspectorModal');
    if (!modal) return;

    // Header population
    document.getElementById('inspectorRepoName').textContent = repo.name;
    document.getElementById('inspectorRepoDescription').textContent = repo.description || 'No description provided.';
    
    const roleBadge = document.getElementById('inspectorRoleBadge');
    if (roleBadge) {
        roleBadge.textContent = (repo.role || 'owner').toUpperCase();
    }

    const visBadge = document.getElementById('inspectorVisibilityBadge');
    if (visBadge) {
        visBadge.innerHTML = repo.is_private
            ? `<i class="fas fa-lock mr-1"></i>Private`
            : `<i class="fas fa-globe mr-1"></i>Public`;
        visBadge.className = repo.is_private
            ? `text-xs font-bold px-2 py-0.5 rounded bg-yellow-900/20 text-yellow-400 border border-yellow-500/20`
            : `text-xs font-bold px-2 py-0.5 rounded bg-sky-900/20 text-sky-400 border border-sky-500/20`;
    }

    const syncBadge = document.getElementById('inspectorSyncBadge');
    if (syncBadge) {
        syncBadge.innerHTML = repo.is_synced
            ? `<i class="fas fa-check mr-1"></i>Synced to Projects`
            : `Not Synced`;
        syncBadge.className = repo.is_synced
            ? `text-xs font-bold px-2 py-0.5 rounded bg-emerald-900/20 text-emerald-400 border border-emerald-500/20`
            : `text-xs font-medium px-2 py-0.5 rounded bg-gray-800 text-gray-400`;
    }

    const langBadge = document.getElementById('inspectorLangBadge');
    if (langBadge) {
        if (repo.language) {
            langBadge.textContent = repo.language;
            langBadge.classList.remove('hidden');
        } else {
            langBadge.classList.add('hidden');
        }
    }

    const ghLink = document.getElementById('inspectorGithubLink');
    if (ghLink) ghLink.href = safeUrl(repo.html_url);

    // Commit & Sync sub-header
    const commitCountSpan = document.getElementById('inspectorCommitCount');
    const commitCount = (repo.project && repo.project.commit_count) || 0;
    if (commitCountSpan) {
        commitCountSpan.innerHTML = `<i class="fas fa-code-commit text-brand-blue mr-1.5"></i><strong>${commitCount}</strong> commits recorded`;
    }

    const lastSyncedSpan = document.getElementById('inspectorLastSynced');
    if (lastSyncedSpan) {
        if (repo.is_synced && repo.project && repo.project.last_synced_at) {
            lastSyncedSpan.innerHTML = `<i class="fas fa-clock text-gray-500 mr-1.5"></i>Synced ${formatRelativeTime(new Date(repo.project.last_synced_at))}`;
        } else {
            lastSyncedSpan.innerHTML = `<i class="fas fa-clock text-gray-500 mr-1.5"></i>Never synced`;
        }
    }

    const editBtn = document.getElementById('inspectorEditProjectBtn');
    if (editBtn) {
        editBtn.classList.toggle('hidden', !repo.is_synced || !repo.project);
    }

    const syncBtn = document.getElementById('inspectorSyncBtn');
    if (syncBtn) {
        syncBtn.innerHTML = `<i class="fas fa-sync-alt mr-1.5"></i>${repo.is_synced ? 'Re-sync Repository' : 'Import as Project'}`;
    }

    // Open Modal
    modal.classList.remove('hidden');

    // Switch to initial tab
    switchInspectorTab(initialTab);
}

/**
 * Close Inspector Modal.
 */
function closeGithubInspector() {
    const modal = document.getElementById('githubInspectorModal');
    if (modal) modal.classList.add('hidden');
    activeInspectorRepo = null;
}

/**
 * Switch active inspector tab ('readme', 'commits', 'project').
 */
async function switchInspectorTab(tabName, clickedBtn = null) {
    if (!activeInspectorRepo) return;

    // Update tab button styles
    document.querySelectorAll('.inspector-tab-btn').forEach(b => {
        b.classList.remove('text-brand-blue', 'border-brand-blue');
        b.classList.add('text-gray-400', 'border-transparent');
    });

    const targetBtn = clickedBtn || document.getElementById(`tabBtn${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);
    if (targetBtn) {
        targetBtn.classList.remove('text-gray-400', 'border-transparent');
        targetBtn.classList.add('text-brand-blue', 'border-brand-blue');
    }

    // Switch panels
    document.querySelectorAll('.inspector-tab-panel').forEach(p => p.classList.add('hidden'));

    if (tabName === 'readme') {
        const panel = document.getElementById('inspectorTabContentReadme');
        if (panel) panel.classList.remove('hidden');
        await loadInspectorReadme(activeInspectorRepo);
    } else if (tabName === 'commits') {
        const panel = document.getElementById('inspectorTabContentCommits');
        if (panel) panel.classList.remove('hidden');
        renderInspectorCommits(activeInspectorRepo);
    } else if (tabName === 'project') {
        const panel = document.getElementById('inspectorTabContentProject');
        if (panel) panel.classList.remove('hidden');
        renderInspectorProjectDetails(activeInspectorRepo);
    }
}

/**
 * Load and render Markdown README.
 */
async function loadInspectorReadme(repo) {
    const container = document.getElementById('inspectorReadmeContent');
    const loading = document.getElementById('inspectorReadmeLoading');
    const empty = document.getElementById('inspectorReadmeEmpty');

    if (!container) return;

    // Check if we already have cached README
    let readmeText = (repo.project && repo.project.readme_content) ? repo.project.readme_content : null;

    if (readmeText) {
        if (loading) loading.classList.add('hidden');
        if (empty) empty.classList.add('hidden');
        container.innerHTML = renderMarkdown(readmeText);
        return;
    }

    // Otherwise fetch live from API
    if (loading) loading.classList.remove('hidden');
    if (empty) empty.classList.add('hidden');
    container.innerHTML = '';

    try {
        const data = await fetchJson(`${API_BASE}/github/repos/${repo.id}/readme/`);
        if (data && data.readme) {
            // Save to repo object cache in memory
            if (!repo.project) repo.project = {};
            repo.project.readme_content = data.readme;

            if (empty) empty.classList.add('hidden');
            container.innerHTML = renderMarkdown(data.readme);
        } else {
            if (empty) empty.classList.remove('hidden');
        }
    } catch (e) {
        console.warn('Could not load live README:', e);
        if (empty) empty.classList.remove('hidden');
    } finally {
        if (loading) loading.classList.add('hidden');
    }
}

/**
 * Helper to render Markdown using marked.js with fallback.
 */
function renderMarkdown(rawText) {
    if (!rawText) return '<p class="text-gray-500 italic">No content available.</p>';
    if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
        return marked.parse(rawText);
    }
    return `<pre class="whitespace-pre-wrap font-mono text-xs text-gray-300">${escapeHtml(rawText)}</pre>`;
}

/**
 * Render last 10 cached commits inside inspector.
 */
function renderInspectorCommits(repo) {
    const container = document.getElementById('inspectorCommitsList');
    const empty = document.getElementById('inspectorCommitsEmpty');
    const refreshBtn = document.getElementById('inspectorRefreshCommitsBtn');

    if (!container) return;

    const commits = (repo.project && repo.project.cached_commits) || [];

    if (refreshBtn) {
        refreshBtn.classList.toggle('hidden', !repo.is_synced || !repo.project);
    }

    if (!commits.length) {
        container.innerHTML = '';
        if (empty) empty.classList.remove('hidden');
        return;
    }

    if (empty) empty.classList.add('hidden');

    container.innerHTML = commits.map(c => `
        <div class="bg-[#0A101D] border border-white/5 rounded-lg p-3.5 hover:border-brand-blue/30 transition-colors">
            <div class="flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-white break-words">
                        ${escapeHtml(c.message || 'No commit message')}
                    </p>
                    <div class="flex items-center gap-3 mt-2 text-xs text-gray-400 flex-wrap">
                        <span class="text-gray-300 font-medium flex items-center gap-1">
                            <i class="fas fa-user-circle text-brand-blue"></i>
                            ${escapeHtml(c.author || 'Unknown')}
                        </span>
                        ${c.date ? `
                            <span>&middot;</span>
                            <span class="text-gray-500">${formatRelativeTime(new Date(c.date))}</span>
                        ` : ''}
                        ${(c.additions || c.deletions) ? `
                            <span>&middot;</span>
                            <span class="text-emerald-400 font-mono">+${c.additions || 0}</span>
                            <span class="text-red-400 font-mono">-${c.deletions || 0}</span>
                        ` : ''}
                    </div>
                </div>
                <a href="${escapeHtml(safeUrl(`${repo.html_url}/commit/${c.sha}`))}" target="_blank" rel="noopener noreferrer"
                    class="font-mono text-xs text-brand-blue hover:underline px-2 py-1 bg-blue-900/20 border border-blue-500/20 rounded shrink-0"
                    title="View commit on GitHub">
                    ${escapeHtml((c.sha || '').substring(0, 7))}
                </a>
            </div>
        </div>
    `).join('');
}

/**
 * Fetch fresh live commits from GitHub for this project.
 */
async function refreshInspectorCommitsLive() {
    if (!activeInspectorRepo || !activeInspectorRepo.project) return;
    const projectId = activeInspectorRepo.project.id;
    const btn = document.getElementById('inspectorRefreshCommitsBtn');
    const original = btn ? btn.innerHTML : '';

    if (btn) {
        btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-1"></i>Fetching...`;
        btn.disabled = true;
    }

    try {
        const data = await fetchJson(`${API_BASE}/projects/${projectId}/commits/?refresh=1`);
        if (data && data.commits) {
            activeInspectorRepo.project.cached_commits = data.commits;
            renderInspectorCommits(activeInspectorRepo);
            toast.success('Commits refreshed from GitHub!');
        }
    } catch (e) {
        console.error('Failed to refresh commits:', e);
        toastApiError(e, 'Could not fetch live commits from GitHub.');
    } finally {
        if (btn) {
            btn.innerHTML = original;
            btn.disabled = false;
        }
    }
}

/**
 * Render Project CMS metadata inside inspector.
 */
function renderInspectorProjectDetails(repo) {
    const detailsBox = document.getElementById('inspectorProjectDetailsBox');
    const unsyncedBox = document.getElementById('inspectorProjectUnsyncedBox');

    if (!detailsBox || !unsyncedBox) return;

    if (!repo.is_synced || !repo.project) {
        detailsBox.classList.add('hidden');
        unsyncedBox.classList.remove('hidden');
        return;
    }

    unsyncedBox.classList.add('hidden');
    detailsBox.classList.remove('hidden');

    const p = repo.project;

    detailsBox.innerHTML = `
        <div class="bg-[#0A101D] border border-white/10 rounded-xl p-5 space-y-4">
            <div class="flex justify-between items-start">
                <div>
                    <span class="text-xs font-bold text-brand-blue uppercase">Portfolio Project #${p.id}</span>
                    <h4 class="text-lg font-bold text-white mt-1">${escapeHtml(p.title)}</h4>
                </div>
                <button onclick="editProjectFromGithub(${p.id})"
                    class="bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors">
                    <i class="fas fa-pen-to-square"></i>Edit in CMS
                </button>
            </div>

            <div>
                <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">Short Description</label>
                <p class="text-sm text-gray-300 bg-[#06090F] p-3 rounded-lg border border-white/5 leading-relaxed">
                    ${escapeHtml(p.short_description || 'None set.')}
                </p>
            </div>

            <div>
                <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">Full Description</label>
                <div class="text-sm text-gray-300 bg-[#06090F] p-3 rounded-lg border border-white/5 max-h-48 overflow-y-auto leading-relaxed whitespace-pre-wrap">
                    ${escapeHtml(p.description || 'None set.')}
                </div>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs pt-2">
                <div class="bg-[#06090F] p-3 rounded-lg border border-white/5">
                    <span class="text-gray-500 block mb-1">Live Demo URL</span>
                    ${p.project_url ? `
                        <a href="${escapeHtml(safeUrl(p.project_url))}" target="_blank" rel="noopener noreferrer" class="text-brand-blue hover:underline font-medium break-all">
                            ${escapeHtml(p.project_url)}
                        </a>
                    ` : '<span class="text-gray-600">Not configured</span>'}
                </div>
                <div class="bg-[#06090F] p-3 rounded-lg border border-white/5">
                    <span class="text-gray-500 block mb-1">Featured Status</span>
                    <span class="font-semibold ${p.featured ? 'text-emerald-400' : 'text-gray-400'}">
                        ${p.featured ? '<i class="fas fa-star text-amber-400 mr-1"></i>Featured on Homepage' : 'Standard Project'}
                    </span>
                </div>
            </div>
        </div>
    `;
}

/**
 * Sync the currently inspected repo.
 */
async function syncCurrentInspectorRepo() {
    if (!activeInspectorRepo) return;
    const btn = document.getElementById('inspectorSyncBtn');
    await syncSingleRepo(activeInspectorRepo.id, btn);
}

/**
 * Jump directly from GitHub Manager into the Project editor in Projects section.
 */
function openLinkedProjectEditor() {
    if (!activeInspectorRepo || !activeInspectorRepo.project) return;
    const projectId = activeInspectorRepo.project.id;
    editProjectFromGithub(projectId);
}

function editProjectFromGithub(projectId) {
    closeGithubInspector();
    showSection('projects');
    if (typeof editProject === 'function') {
        editProject(projectId);
    }
}

// ============================================================
// Utility Helpers
// ============================================================

function formatRelativeTime(date) {
    if (!(date instanceof Date) || isNaN(date.getTime())) return '';
    const now = new Date();
    const diffSecs = Math.floor((now - date) / 1000);

    if (diffSecs < 60) return 'just now';
    const diffMins = Math.floor(diffSecs / 60);
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 30) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function getLanguageColor(lang) {
    const colors = {
        'TypeScript': '#3178C6',
        'JavaScript': '#F7DF1E',
        'Python': '#3572A5',
        'HTML': '#E34C26',
        'CSS': '#563D7C',
        'Dart': '#00B4AB',
        'Go': '#00ADD8',
        'Rust': '#DEA584',
        'PHP': '#4F5D95',
        'Ruby': '#701516',
        'Java': '#B07219',
        'C++': '#F34B7D',
        'C#': '#178600',
        'Shell': '#89E051',
    };
    return colors[lang] || '#38BDF8';
}
