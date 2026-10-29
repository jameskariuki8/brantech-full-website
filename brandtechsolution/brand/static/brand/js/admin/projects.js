// ============================================================
// Unified Projects & GitHub Hub Controller
// ============================================================

let currentProjectsList = [];
let currentProjectFilter = 'all';
let cachedGithubReposList = [];
let activeProjectReadmeText = '';

/**
 * Fetch projects from API and render rich cards.
 */
async function loadProjects() {
    const container = document.getElementById('projectsList');
    if (!container) return;
    try {
        const response = await fetch(`${API_BASE}/projects/`, { credentials: 'same-origin' });
        const payload = await response.json();
        currentProjectsList = Array.isArray(payload) ? payload : (payload.results || []);

        if (!currentProjectsList.length) {
            container.innerHTML = `
                <div class="col-span-full text-center py-12 text-gray-500 bg-[#06090F] border border-white/5 rounded-2xl p-8">
                    <i class="fas fa-folder-open text-3xl mb-3 text-gray-600"></i>
                    <p class="text-sm font-medium text-gray-300">No projects found.</p>
                    <p class="text-xs text-gray-500 mt-1">Create your first standalone project or link a repository to start tracking.</p>
                    <button onclick="newProject()" class="mt-4 px-4 py-2 bg-brand-green text-black font-semibold text-xs rounded-lg hover:bg-green-500 transition-colors">
                        <i class="fas fa-plus mr-1.5"></i>Create Project
                    </button>
                </div>`;
            return;
        }

        filterProjectsList();
        // Prefetch repos for form selector in background
        populateRepoDropdown(false);
    } catch (e) {
        console.error('Failed to load projects:', e);
        container.innerHTML = `<div class="col-span-full text-center py-10 text-red-400 text-sm">Failed to load projects.</div>`;
    }
}

/**
 * Filter projects by category chip.
 */
function setProjectFilter(filter) {
    currentProjectFilter = filter;
    ['all', 'github', 'standalone', 'showcase'].forEach(f => {
        const btn = document.getElementById(`pFilter-${f}`);
        if (!btn) return;
        if (f === filter) {
            btn.className = 'px-3 py-1.5 rounded-lg bg-white/10 text-white font-semibold transition-colors';
        } else {
            btn.className = 'px-3 py-1.5 rounded-lg text-gray-400 hover:text-white transition-colors';
        }
    });
    filterProjectsList();
}

/**
 * Filter and render project cards in the grid.
 */
function filterProjectsList() {
    const container = document.getElementById('projectsList');
    if (!container) return;
    const query = (document.getElementById('projectSearchInput')?.value || '').toLowerCase().trim();

    const filtered = currentProjectsList.filter(p => {
        const matchesFilter =
            currentProjectFilter === 'all' ? true :
            currentProjectFilter === 'github' ? Boolean(p.github_repo_id || p.is_github_synced) :
            currentProjectFilter === 'standalone' ? !p.github_repo_id && !p.is_github_synced :
            currentProjectFilter === 'showcase' ? Boolean(p.showcase) : true;

        if (!matchesFilter) return false;
        if (!query) return true;

        const title = (p.title || '').toLowerCase();
        const desc = (p.short_description || p.description || '').toLowerCase();
        const git = (p.github_url || '').toLowerCase();
        return title.includes(query) || desc.includes(query) || git.includes(query);
    });

    if (!filtered.length) {
        container.innerHTML = `<div class="col-span-full text-center py-10 text-gray-500 text-sm">No matching projects found.</div>`;
        return;
    }

    container.innerHTML = filtered.map(renderProjectCard).join('');
}

/**
 * Render an individual rich Project Card with dynamic accent glow.
 */
function renderProjectCard(p) {
    const accent = safeColor(p.accent);
    const isGit = Boolean(p.github_repo_id || p.is_github_synced);
    const commitsCount = p.commit_count || 0;
    const lastSynced = p.last_synced_at ? new Date(p.last_synced_at).toLocaleDateString() : null;

    let gitBadgeHtml = '';
    if (isGit) {
        gitBadgeHtml = `
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-md bg-blue-500/10 text-brand-blue border border-blue-500/20 flex items-center gap-1">
                <i class="fab fa-github"></i>${escapeHtml(p.github_role ? p.github_role.toUpperCase() : 'SYNCED')}
            </span>`;
    } else {
        gitBadgeHtml = `
            <span class="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-white/5 text-gray-400">
                STANDALONE
            </span>`;
    }

    const showcasePill = p.showcase
        ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-md" style="color:${accent}; background:${accent}1a; border: 1px solid ${accent}33">
             <i class="fas fa-sparkles mr-1"></i>PRODUCTS &middot; ${escapeHtml((p.phase || 'LIVE').toUpperCase())}
           </span>`
        : '';

    const featuredPill = p.featured
        ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
             FEATURED
           </span>`
        : '';

    const mediaThumbnail = p.image
        ? `<div class="w-full h-36 rounded-xl overflow-hidden mb-3 bg-[#06090F] border border-white/5 relative group">
             <img src="${escapeHtml(p.image)}" alt="${escapeHtml(p.title)}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300">
             ${p.video_url || p.video_file ? '<span class="absolute bottom-2 right-2 px-2 py-0.5 bg-black/70 backdrop-blur rounded text-[10px] text-white flex items-center gap-1"><i class="fas fa-play text-brand-green"></i>Video</span>' : ''}
           </div>`
        : (p.video_url || p.video_file ? `
           <div class="w-full h-24 rounded-xl mb-3 bg-blue-950/20 border border-blue-500/10 flex items-center justify-center text-brand-blue text-xs gap-2">
             <i class="fas fa-circle-play text-base"></i><span>Video Demo Attached</span>
           </div>` : '');

    return `
        <div class="clean-card rounded-2xl p-5 flex flex-col justify-between border border-dark-border hover:border-white/20 transition-all duration-300 relative group"
             style="box-shadow: 0 4px 20px -2px ${accent}0d;">
            <div>
                <!-- Top Pills -->
                <div class="flex items-center gap-1.5 mb-3 flex-wrap">
                    ${gitBadgeHtml}
                    ${showcasePill}
                    ${featuredPill}
                </div>

                ${mediaThumbnail}

                <!-- Title & Description -->
                <h3 class="text-base font-bold text-white mb-1.5 font-heading group-hover:text-brand-blue transition-colors leading-snug">
                    ${escapeHtml(p.title)}
                </h3>
                <p class="text-xs text-gray-400 mb-3 line-clamp-2 leading-relaxed">
                    ${escapeHtml(p.short_description || p.description || 'No description provided.')}
                </p>

                <!-- Telemetry Stats & Links -->
                <div class="text-[11px] text-gray-500 space-y-1 py-2 mb-3 border-y border-white/5">
                    ${isGit ? `
                        <div class="flex items-center justify-between">
                            <span class="flex items-center gap-1.5 text-gray-400">
                                <i class="fas fa-code-commit text-brand-blue"></i>
                                <span><strong>${commitsCount}</strong> commits</span>
                            </span>
                            <span>${lastSynced ? `Synced ${lastSynced}` : 'Never synced'}</span>
                        </div>
                    ` : `
                        <div class="text-gray-500">Standalone Portfolio Item</div>
                    `}
                    ${p.project_url ? `
                        <div class="truncate">
                            <a href="${escapeHtml(safeUrl(p.project_url))}" target="_blank" rel="noopener noreferrer" class="text-brand-blue hover:underline">
                                <i class="fas fa-external-link-alt mr-1 text-[9px]"></i>${escapeHtml(p.project_url)}
                            </a>
                        </div>
                    ` : ''}
                </div>
            </div>

            <!-- Action Toolbar -->
            <div class="flex items-center justify-between pt-2">
                <div class="flex items-center gap-1">
                    ${isGit ? `
                        <button onclick="syncProjectNow(${p.id}, this)" class="px-2.5 py-1.5 bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white rounded-lg text-xs font-semibold flex items-center gap-1 transition-colors" title="Re-sync commits from GitHub">
                            <i class="fas fa-rotate text-[10px]"></i><span>Sync</span>
                        </button>
                        ${p.has_readme ? `
                            <button onclick="viewProjectReadme(${p.id}, '${escapeHtml(p.title)}')" class="px-2 py-1.5 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white rounded-lg text-xs transition-colors" title="Inspect README">
                                <i class="fab fa-readme"></i>
                            </button>
                        ` : ''}
                    ` : `
                        <button onclick="editProject(${p.id})" class="text-[11px] text-gray-400 hover:text-brand-blue transition-colors">
                            <i class="fab fa-github mr-1"></i>Link GitHub
                        </button>
                    `}
                </div>
                <div class="flex items-center gap-1">
                    <button onclick="editProject(${p.id})" class="p-1.5 text-gray-400 hover:text-white rounded-lg hover:bg-white/5 transition-colors" title="Edit">
                        <i class="fas fa-pen text-xs"></i>
                    </button>
                    <button onclick="deleteItem('projects', ${p.id})" class="p-1.5 text-gray-400 hover:text-red-400 rounded-lg hover:bg-red-500/10 transition-colors" title="Delete">
                        <i class="fas fa-trash text-xs"></i>
                    </button>
                </div>
            </div>
        </div>`;
}

/**
 * Trigger immediate single-project GitHub sync with spinner.
 */
async function syncProjectNow(projectId, btn) {
    if (!btn) return;
    const oldHtml = btn.innerHTML;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin text-[10px]"></i><span>Syncing...</span>`;
    btn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/projects/${projectId}/sync-github/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
            credentials: 'same-origin',
        });
        const data = await res.json();
        if (data.success) {
            toast.success(data.message || 'Synced with GitHub!');
            await loadProjects();
        } else {
            toast.error(data.error || 'Failed to sync with GitHub.');
        }
    } catch (e) {
        console.error(e);
        toast.error('Network error during sync.');
    } finally {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
    }
}

/**
 * Fetch and populate GitHub repositories selector in project form.
 */
async function populateRepoDropdown(force = false) {
    const selector = document.getElementById('repoSelector');
    if (!selector) return;

    if (!force && cachedGithubReposList.length) {
        renderRepoDropdownOptions();
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/github/repos/`);
        const data = await res.json();
        cachedGithubReposList = (data && data.results) || [];
        renderRepoDropdownOptions();
        if (force) toast.success('GitHub repositories refreshed.');
    } catch (e) {
        console.warn('Could not fetch GitHub repositories list:', e);
    }
}

function renderRepoDropdownOptions(selectedRepoId = null) {
    const selector = document.getElementById('repoSelector');
    if (!selector) return;

    const baseOption = '<option value="">-- No Repository / Standalone Project --</option>';
    const repoOptions = cachedGithubReposList.map(repo => {
        const isSelected = selectedRepoId && Number(selectedRepoId) === repo.id;
        const visibility = repo.is_private ? 'Private' : 'Public';
        const stars = repo.stargazers_count ? ` · ⭐ ${repo.stargazers_count}` : '';
        return `<option value="${repo.id}" data-url="${escapeHtml(repo.html_url)}" data-name="${escapeHtml(repo.name)}" data-desc="${escapeHtml(repo.description || '')}"${isSelected ? ' selected' : ''}>
            ${escapeHtml(repo.full_name)} (${visibility}${stars})
        </option>`;
    }).join('');

    selector.innerHTML = baseOption + repoOptions;
}

/**
 * Handle repository selection from the dropdown in the Project form.
 */
function onSelectGitHubRepo(repoId) {
    const hiddenId = document.getElementById('projectGithubRepoId');
    const gitUrlInput = document.getElementById('projectGithubUrlInput');
    const badge = document.getElementById('githubStatusBadge');
    const form = document.getElementById('addProjectForm');

    if (!repoId) {
        if (hiddenId) hiddenId.value = '';
        if (badge) badge.textContent = 'Standalone (No Git)';
        return;
    }

    if (hiddenId) hiddenId.value = repoId;
    const selected = cachedGithubReposList.find(r => r.id === Number(repoId));
    if (selected) {
        if (gitUrlInput && (!gitUrlInput.value || gitUrlInput.value === '')) {
            gitUrlInput.value = selected.html_url;
        }
        if (form && !form.title.value) {
            form.title.value = selected.name;
        }
        if (form && form.short_description && !form.short_description.value && selected.description) {
            form.short_description.value = selected.description;
        }
        if (badge) {
            badge.innerHTML = `<span class="text-brand-green font-semibold"><i class="fas fa-check mr-1"></i>Linked to ${escapeHtml(selected.full_name)}</span>`;
        }
    }
}

/**
 * Readme modal viewer.
 */
async function viewProjectReadme(projectId, projectTitle) {
    const modal = document.getElementById('projectReadmeModal');
    const title = document.getElementById('modalReadmeTitle');
    const content = document.getElementById('modalReadmeContent');
    if (!modal || !content) return;

    title.textContent = `README: ${projectTitle}`;
    content.innerHTML = `<div class="text-center py-8 text-gray-500"><i class="fas fa-spinner fa-spin mr-2"></i>Loading README...</div>`;
    modal.classList.remove('hidden');

    try {
        const p = await fetch(`${API_BASE}/projects/${projectId}/`).then(r => r.json());
        content.textContent = p.readme_content || 'No README cached yet. Click "Sync" on the card to fetch.';
        activeProjectReadmeText = p.readme_content || '';
    } catch (e) {
        content.textContent = 'Failed to load README.';
    }
}

function closeProjectReadmeModal() {
    const modal = document.getElementById('projectReadmeModal');
    if (modal) modal.classList.add('hidden');
}

/**
 * Extract System Modules & Features from README.
 */
function extractFeaturesFromReadme() {
    const hiddenId = document.getElementById('projectGithubRepoId')?.value;
    const desc = document.getElementById('addProjectForm')?.description?.value || '';
    let textToParse = activeProjectReadmeText || desc;

    if (!textToParse) {
        toast.info('No README content found yet to parse. Please link a repository or paste a description.');
        return;
    }

    // Simple markdown list regex
    const lines = textToParse.split('\n');
    let extracted = [];
    const iconPool = ['fas fa-bolt', 'fas fa-shield-halved', 'fas fa-chart-line', 'fas fa-boxes-stacked', 'fas fa-robot', 'fas fa-network-wired'];

    for (const line of lines) {
        const match = line.match(/^[-*]\s+\*\*([^*]+)\*\*:\s*(.+)$/);
        if (match) {
            extracted.push({
                style: 'card',
                icon: iconPool[extracted.length % iconPool.length],
                label: match[1].trim(),
                text: match[2].trim()
            });
        }
        if (extracted.length >= 6) break;
    }

    if (!extracted.length) {
        // Fallback: parse plain bullets
        for (const line of lines) {
            const match = line.match(/^[-*]\s+([^:]+):\s*(.+)$/);
            if (match) {
                extracted.push({
                    style: 'card',
                    icon: iconPool[extracted.length % iconPool.length],
                    label: match[1].trim(),
                    text: match[2].trim()
                });
            }
            if (extracted.length >= 4) break;
        }
    }

    if (extracted.length > 0) {
        const container = document.getElementById('featureRows');
        if (container) {
            container.innerHTML = extracted.map(featureRowHtml).join('');
            toast.success(`Extracted ${extracted.length} system modules from documentation!`);
        }
    } else {
        toast.info('Could not find bulleted features (Format: - **Title**: Description). Add rows manually.');
    }
}

/**
 * Dynamic Palette Extractor from Image Upload.
 */
function handleCoverImageUpload(input) {
    if (!input.files || !input.files[0]) return;
    const file = input.files[0];
    const reader = new FileReader();

    reader.onload = function(e) {
        const img = new Image();
        img.crossOrigin = 'Anonymous';
        img.onload = function() {
            try {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = 100;
                canvas.height = 100;
                ctx.drawImage(img, 0, 0, 100, 100);
                const imageData = ctx.getImageData(0, 0, 100, 100).data;

                // Color extraction: find vibrant non-grey pixel
                let r = 0, g = 255, b = 148;
                let maxSat = 0;
                for (let i = 0; i < imageData.length; i += 16) {
                    const pr = imageData[i], pg = imageData[i+1], pb = imageData[i+2];
                    const max = Math.max(pr, pg, pb), min = Math.min(pr, pg, pb);
                    const sat = max === 0 ? 0 : (max - min) / max;
                    if (sat > maxSat && max > 50 && max < 240) {
                        maxSat = sat;
                        r = pr; g = pg; b = pb;
                    }
                }

                const hex = `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1).toUpperCase()}`;
                const deepR = Math.max(0, Math.floor(r * 0.7));
                const deepG = Math.max(0, Math.floor(g * 0.7));
                const deepB = Math.max(0, Math.floor(b * 0.7));
                const deepHex = `#${((1 << 24) + (deepR << 16) + (deepG << 8) + deepB).toString(16).slice(1).toUpperCase()}`;

                setAccentTheme(hex, deepHex);
                toast.success(`Extracted dominant theme color: ${hex}`);
            } catch (err) {
                console.warn('Canvas color extraction failed:', err);
            }
        };
        img.src = e.target.result;
    };
    reader.readAsDataURL(file);
}

function setAccentTheme(primary, deep) {
    const accentInput = document.getElementById('accentColorInput');
    const deepInput = document.getElementById('accentDeepInput');
    const hexSpan = document.getElementById('accentColorHex');

    if (accentInput) accentInput.value = primary;
    if (deepInput) deepInput.value = deep;
    if (hexSpan) hexSpan.textContent = primary;
    updateLiveThemePreview();
}

function updateLiveThemePreview() {
    const accent = document.getElementById('accentColorInput')?.value || '#00FF94';
    const hexSpan = document.getElementById('accentColorHex');
    if (hexSpan) hexSpan.textContent = accent;
}

/**
 * Visual Metric Rows for Data Story Studio.
 */
function metricRowHtml(row = {}) {
    return `
        <tr class="metric-row">
            <td class="py-1 px-2">
                <input type="text" data-field="label" placeholder="e.g. Result Generation" value="${escapeHtml(row.label || '')}"
                    class="w-full bg-[#06090F] border border-dark-border rounded px-2.5 py-1.5 text-xs text-white">
            </td>
            <td class="py-1 px-2">
                <input type="number" step="any" data-field="baseline" placeholder="e.g. 14" value="${escapeHtml(row.baseline != null ? row.baseline : '')}"
                    class="w-full bg-[#06090F] border border-dark-border rounded px-2.5 py-1.5 text-xs text-white">
            </td>
            <td class="py-1 px-2">
                <input type="number" step="any" data-field="active" placeholder="e.g. 12" value="${escapeHtml(row.active != null ? row.active : '')}"
                    class="w-full bg-[#06090F] border border-dark-border rounded px-2.5 py-1.5 text-xs text-white">
            </td>
            <td class="py-1 px-2 text-right">
                <button type="button" onclick="this.closest('.metric-row').remove(); compileChartSpecFromRows();" class="text-red-400 hover:text-red-300">
                    <i class="fas fa-xmark"></i>
                </button>
            </td>
        </tr>`;
}

function addChartMetricRow(data) {
    const tbody = document.getElementById('chartMetricRows');
    if (tbody) {
        tbody.insertAdjacentHTML('beforeend', metricRowHtml(data));
    }
}

function compileChartSpecFromRows() {
    const rows = Array.from(document.querySelectorAll('#chartMetricRows .metric-row')).map(tr => {
        return {
            label: tr.querySelector('[data-field="label"]')?.value || '',
            baseline: Number(tr.querySelector('[data-field="baseline"]')?.value || 0),
            active: Number(tr.querySelector('[data-field="active"]')?.value || 0),
        };
    }).filter(r => r.label);

    if (!rows.length) return;

    const accent = document.getElementById('accentColorInput')?.value || '#007AFF';
    const spec = {
        type: 'bar',
        data: {
            labels: rows.map(r => r.label),
            datasets: [
                {
                    label: 'Legacy / Manual',
                    data: rows.map(r => r.baseline),
                    backgroundColor: 'rgba(239, 68, 68, 0.4)'
                },
                {
                    label: 'With Solution',
                    data: rows.map(r => r.active),
                    backgroundColor: accent
                }
            ]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { labels: { font: { size: 9 }, color: '#9CA3AF' } }
            }
        }
    };

    const jsonInput = document.getElementById('chartSpecJsonInput');
    if (jsonInput) jsonInput.value = JSON.stringify(spec, null, 2);
}

function applyChartPreset(preset) {
    const headingInput = document.getElementById('chartHeadingInput');
    const tbody = document.getElementById('chartMetricRows');
    if (!tbody) return;

    if (preset === 'school_sms') {
        if (headingInput) headingInput.value = 'Data Story: Result Generation Speed (Manual vs SMS)';
        tbody.innerHTML = [
            { label: 'Result Generation', baseline: 14, active: 12 },
            { label: 'Fee Reconciliation', baseline: 7, active: 5 },
            { label: 'Inventory Audit', baseline: 5, active: 3 }
        ].map(metricRowHtml).join('');
    } else if (preset === 'lead_growth') {
        if (headingInput) headingInput.value = 'Data Story: Inbound Growth Post-Launch';
        tbody.innerHTML = [
            { label: 'Month 1', baseline: 5, active: 15 },
            { label: 'Month 2', baseline: 8, active: 32 },
            { label: 'Month 3', baseline: 12, active: 68 }
        ].map(metricRowHtml).join('');
    }
    compileChartSpecFromRows();
}

/**
 * Edit Project
 */
async function editProject(id) {
    try {
        const p = await fetch(`${API_BASE}/projects/${id}/`).then(r => r.json());
        const form = document.getElementById('addProjectForm');
        form.title.value = p.title || '';
        if (form.short_description) form.short_description.value = p.short_description || '';
        form.description.value = p.description || '';
        form.project_url.value = p.project_url || '';
        form.github_url.value = p.github_url || '';
        if (form.video_url) form.video_url.value = p.video_url || '';
        form.featured.checked = Boolean(p.featured);

        const hiddenId = document.getElementById('projectGithubRepoId');
        if (hiddenId) hiddenId.value = p.github_repo_id || '';
        renderRepoDropdownOptions(p.github_repo_id);

        fillShowcaseFields(form, p);

        const titleEl = document.getElementById('projectModalTitle') || document.querySelector('#projectForm h3');
        if (titleEl) titleEl.textContent = 'Edit Project';
        const btn = document.querySelector('#projectForm button[type="submit"]');
        if (btn) btn.textContent = 'Update Project';

        form.onsubmit = async (e) => {
            e.preventDefault();
            compileChartSpecFromRows();
            attachShowcaseCollections(e.target);
            await updateItem('projects', id, e.target);
            await loadProjects();
        };
        showAddForm('project');
    } catch (e) { console.error(e); }
}

function safeColor(value) {
    const raw = String(value || '').trim();
    return /^#[0-9A-Fa-f]{3,8}$/.test(raw) ? raw : '#00FF94';
}

function toggleShowcaseFields(on) {
    const box = document.getElementById('showcaseFields');
    if (box) box.classList.toggle('hidden', !on);
}

function galleryRowHtml(image = {}) {
    return `
        <div class="gallery-row grid grid-cols-1 md:grid-cols-12 gap-2 items-start">
            <input type="url" data-field="remote_url" placeholder="Screenshot / Image URL" value="${escapeHtml(image.remote_url || '')}"
                class="md:col-span-5 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-xs focus:border-brand-blue">
            <input type="text" data-field="static_path" placeholder="or static/ path" value="${escapeHtml(image.static_path || '')}"
                class="md:col-span-3 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-xs focus:border-brand-blue">
            <input type="text" data-field="caption" placeholder="Caption" value="${escapeHtml(image.caption || '')}"
                class="md:col-span-3 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-xs focus:border-brand-blue">
            <button type="button" onclick="this.closest('.gallery-row').remove()"
                class="md:col-span-1 p-2 text-red-400 hover:bg-red-900/30 rounded-lg text-center"><i class="fas fa-trash text-xs"></i></button>
            <input type="hidden" data-field="full_url" value="${escapeHtml(image.full_url || '')}">
            <input type="hidden" data-field="alt" value="${escapeHtml(image.alt || '')}">
            <input type="hidden" data-field="lightbox_title" value="${escapeHtml(image.lightbox_title || '')}">
        </div>`;
}

function featureRowHtml(feature = {}) {
    const styles = ['card', 'chip', 'check'];
    const options = styles.map(s =>
        `<option value="${s}"${(feature.style || 'card') === s ? ' selected' : ''}>${s}</option>`).join('');
    return `
        <div class="feature-row grid grid-cols-1 md:grid-cols-12 gap-2 items-start">
            <select data-field="style" class="md:col-span-2 bg-[#06090F] border border-dark-border rounded-lg px-2 py-2 text-white text-xs">${options}</select>
            <input type="text" data-field="icon" placeholder="fas fa-bolt" value="${escapeHtml(feature.icon || 'fas fa-bolt')}"
                class="md:col-span-2 bg-[#06090F] border border-dark-border rounded-lg px-2 py-2 text-white text-xs">
            <input type="text" data-field="label" placeholder="Module Title" value="${escapeHtml(feature.label || '')}"
                class="md:col-span-3 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-xs">
            <input type="text" data-field="text" placeholder="Capabilities description" value="${escapeHtml(feature.text || '')}"
                class="md:col-span-4 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-xs">
            <button type="button" onclick="this.closest('.feature-row').remove()"
                class="md:col-span-1 p-2 text-red-400 hover:bg-red-900/30 rounded-lg text-center"><i class="fas fa-trash text-xs"></i></button>
        </div>`;
}

function addGalleryRow(image) {
    document.getElementById('galleryRows').insertAdjacentHTML('beforeend', galleryRowHtml(image));
}

function addFeatureRow(feature) {
    document.getElementById('featureRows').insertAdjacentHTML('beforeend', featureRowHtml(feature));
}

function collectRows(containerId, rowClass) {
    return Array.from(document.querySelectorAll(`#${containerId} .${rowClass}`)).map(row => {
        const out = {};
        row.querySelectorAll('[data-field]').forEach(input => { out[input.dataset.field] = input.value; });
        return out;
    });
}

function setField(form, name, value) {
    if (form[name] !== undefined && form[name] !== null) form[name].value = value;
}

function fillShowcaseFields(form, p) {
    const showcaseBox = document.getElementById('projectShowcase');
    if (showcaseBox) showcaseBox.checked = Boolean(p.showcase);
    toggleShowcaseFields(Boolean(p.showcase));

    setField(form, 'phase', p.phase || 'completed');
    setField(form, 'display_order', p.display_order != null ? p.display_order : 0);
    setField(form, 'card_variant', p.card_variant || 'default');
    setAccentTheme(safeColor(p.accent), p.accent_deep || '');
    setField(form, 'badge_icon', p.badge_icon || 'fas fa-check-circle');
    setField(form, 'badge_label', p.badge_label || '');
    setField(form, 'cta_label', p.cta_label || '');
    setField(form, 'cta_icon', p.cta_icon || 'fas fa-arrow-up-right-from-square');
    setField(form, 'gallery_heading', p.gallery_heading || 'Interface Gallery');
    setField(form, 'features_heading', p.features_heading || 'System Modules & Features');
    setField(form, 'chart_heading', p.chart_heading || '');
    setField(form, 'chart_icon', p.chart_icon || 'fas fa-chart-bar');
    setField(form, 'chart_spec', p.chart_spec ? JSON.stringify(p.chart_spec, null, 2) : '');

    const gallery = document.getElementById('galleryRows');
    const features = document.getElementById('featureRows');
    if (gallery) gallery.innerHTML = (p.gallery || []).map(galleryRowHtml).join('');
    if (features) features.innerHTML = (p.features || []).map(featureRowHtml).join('');

    // Load initial metric table from chart_spec if bar chart
    const tbody = document.getElementById('chartMetricRows');
    if (tbody && p.chart_spec && p.chart_spec.data) {
        const labels = p.chart_spec.data.labels || [];
        const ds1 = (p.chart_spec.data.datasets && p.chart_spec.data.datasets[0]?.data) || [];
        const ds2 = (p.chart_spec.data.datasets && p.chart_spec.data.datasets[1]?.data) || [];
        tbody.innerHTML = labels.map((l, idx) => metricRowHtml({
            label: l,
            baseline: ds1[idx] != null ? ds1[idx] : '',
            active: ds2[idx] != null ? ds2[idx] : '',
        })).join('');
    } else if (tbody) {
        tbody.innerHTML = '';
    }
}

function newProject() {
    const form = document.getElementById('addProjectForm');
    if (!form) return;
    form.reset();
    const hiddenId = document.getElementById('projectGithubRepoId');
    if (hiddenId) hiddenId.value = '';
    renderRepoDropdownOptions();
    fillShowcaseFields(form, {});
    const titleEl = document.getElementById('projectModalTitle') || document.querySelector('#projectForm h3');
    if (titleEl) titleEl.textContent = 'New Project Details';
    const btn = document.querySelector('#projectForm button[type="submit"]');
    if (btn) btn.textContent = 'Save Project';
    form.onsubmit = async (e) => {
        e.preventDefault();
        compileChartSpecFromRows();
        attachShowcaseCollections(e.target);
        await addItem('projects', e.target);
        await loadProjects();
    };
    showAddForm('project');
}

function attachShowcaseCollections(form) {
    let gallery = form.querySelector('input[name="gallery"]');
    let features = form.querySelector('input[name="features"]');
    if (!gallery) {
        gallery = document.createElement('input');
        gallery.type = 'hidden';
        gallery.name = 'gallery';
        form.appendChild(gallery);
    }
    if (!features) {
        features = document.createElement('input');
        features.type = 'hidden';
        features.name = 'features';
        form.appendChild(features);
    }
    gallery.value = JSON.stringify(collectRows('galleryRows', 'gallery-row').filter(r => r.remote_url || r.static_path));
    features.value = JSON.stringify(collectRows('featureRows', 'feature-row').filter(r => r.text || r.label));

    let showcase = form.querySelector('input[name="showcase"]');
    if (!showcase) {
        showcase = document.createElement('input');
        showcase.type = 'hidden';
        showcase.name = 'showcase';
        form.appendChild(showcase);
    }
    const box = document.getElementById('projectShowcase');
    showcase.value = box && box.checked ? 'true' : 'false';
}

const addProjectFormEl = document.getElementById('addProjectForm');
if (addProjectFormEl) {
    addProjectFormEl.onsubmit = async (e) => {
        e.preventDefault();
        compileChartSpecFromRows();
        attachShowcaseCollections(e.target);
        await addItem('projects', e.target);
        await loadProjects();
    };
}
