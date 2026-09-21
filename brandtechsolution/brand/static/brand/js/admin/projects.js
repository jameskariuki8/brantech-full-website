async function loadProjects() {
    try {
        const response = await fetch(`${API_BASE}/projects/`, { credentials: 'same-origin' });
        const payload = await response.json();
        // /api/projects/ is paginated and answers {results, pagination}; a bare
        // array read made the list permanently show "No projects found", the
        // same bug loadBlogs() had.
        const projects = Array.isArray(payload) ? payload : (payload.results || []);
        const container = document.getElementById('projectsList');
        if (!container) return;
        if (!projects.length) {
            container.innerHTML = `<div class="text-center py-10 text-gray-600">No projects found. Add one!</div>`;
            return;
        }
        container.innerHTML = projects.map(project => `
            <div class="bg-dark-card border border-dark-border p-5 rounded-lg flex flex-col md:flex-row justify-between items-start gap-4 hover:border-brand-green/30 transition-colors group">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2 flex-wrap">
                        <span class="text-xs font-bold text-brand-blue px-2 py-1 bg-blue-900/20 rounded">PROJECT</span>
                        ${project.featured ? '<span class="text-xs font-bold text-brand-green px-2 py-1 bg-green-900/20 rounded">FEATURED</span>' : ''}
                        ${project.showcase ? `<span class="text-xs font-bold px-2 py-1 rounded" style="color:${escapeHtml(safeColor(project.accent))};background:${escapeHtml(safeColor(project.accent))}1a">ON PRODUCTS &middot; ${escapeHtml((project.phase || '').toUpperCase())}</span>` : ''}
                    </div>
                    <h3 class="text-xl font-bold text-white mb-1">${escapeHtml(project.title)}</h3>
                    <p class="text-sm text-gray-400 mb-2">${escapeHtml(project.short_description || '')}</p>
                    <a href="${escapeHtml(safeUrl(project.project_url))}" target="_blank" rel="noopener noreferrer" class="text-xs text-brand-blue hover:underline">${escapeHtml(project.project_url || 'No Live Link')}</a>
                </div>
                <div class="flex gap-2">
                    <button onclick="editProject(${project.id})" class="p-2 text-blue-400 hover:bg-blue-900/30 rounded-lg transition-colors"><i class="fas fa-edit"></i></button>
                    <button onclick="deleteItem('projects', ${project.id})" class="p-2 text-red-400 hover:bg-red-900/30 rounded-lg transition-colors"><i class="fas fa-trash"></i></button>
                </div>
            </div>
        `).join('');
    } catch (e) { console.error(e); }
}

async function editProject(id) {
    try {
        const p = await fetch(`${API_BASE}/projects/${id}/`).then(r => r.json());
        const form = document.getElementById('addProjectForm');
        form.title.value = p.title || '';
        if (form.short_description && p.short_description) form.short_description.value = p.short_description;
        form.description.value = p.description || '';
        form.project_url.value = p.project_url || '';
        form.github_url.value = p.github_url || '';
        form.featured.checked = p.featured;
        fillShowcaseFields(form, p);

        document.querySelector('#projectForm h3').textContent = 'Edit Project';
        const btn = document.querySelector('#projectForm button[type="submit"]');
        btn.textContent = 'Update Project';

        form.onsubmit = async (e) => {
            e.preventDefault();
            attachShowcaseCollections(e.target);
            await updateItem('projects', id, e.target);
        };
        showAddForm('project');
    } catch (e) { console.error(e); }
}

// ============================================================
// SHOWCASE EDITING
// ============================================================
// A project that appears on /products/ carries the theming that used to be
// written into products.html by hand: an accent, a badge, section headings,
// a gallery, a capability list and a Chart.js config. The gallery and the
// list are variable-length, so they are built as rows here and posted as
// JSON -- the API replaces each collection wholesale.

// Colours are interpolated into a style attribute, so anything that is not a
// plain hex value is dropped rather than escaped into the stylesheet.
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
            <input type="url" data-field="remote_url" placeholder="Image URL" value="${escapeHtml(image.remote_url || '')}"
                class="md:col-span-4 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-sm">
            <input type="text" data-field="static_path" placeholder="or static path" value="${escapeHtml(image.static_path || '')}"
                class="md:col-span-3 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-sm">
            <input type="text" data-field="caption" placeholder="Hover caption" value="${escapeHtml(image.caption || '')}"
                class="md:col-span-4 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-sm">
            <button type="button" onclick="this.closest('.gallery-row').remove()"
                class="md:col-span-1 p-2 text-red-400 hover:bg-red-900/30 rounded-lg"><i class="fas fa-trash"></i></button>
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
            <select data-field="style" class="md:col-span-2 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-sm">${options}</select>
            <input type="text" data-field="icon" placeholder="fas fa-bolt" value="${escapeHtml(feature.icon || '')}"
                class="md:col-span-2 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-sm">
            <input type="text" data-field="label" placeholder="Bold lead-in" value="${escapeHtml(feature.label || '')}"
                class="md:col-span-3 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-sm">
            <input type="text" data-field="text" placeholder="Description" value="${escapeHtml(feature.text || '')}"
                class="md:col-span-4 bg-[#06090F] border border-dark-border rounded-lg px-3 py-2 text-white text-sm">
            <button type="button" onclick="this.closest('.feature-row').remove()"
                class="md:col-span-1 p-2 text-red-400 hover:bg-red-900/30 rounded-lg"><i class="fas fa-trash"></i></button>
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

// Set a field only when the form actually has it, so this keeps working if
// the markup is trimmed down later.
function setField(form, name, value) {
    if (form[name] !== undefined && form[name] !== null) form[name].value = value;
}

function fillShowcaseFields(form, p) {
    const showcaseBox = document.getElementById('projectShowcase');
    if (showcaseBox) showcaseBox.checked = !!p.showcase;
    toggleShowcaseFields(!!p.showcase);

    setField(form, 'phase', p.phase || 'completed');
    setField(form, 'display_order', p.display_order != null ? p.display_order : 0);
    setField(form, 'card_variant', p.card_variant || 'default');
    setField(form, 'accent', safeColor(p.accent));
    setField(form, 'accent_deep', p.accent_deep || '');
    setField(form, 'badge_icon', p.badge_icon || '');
    setField(form, 'badge_label', p.badge_label || '');
    setField(form, 'cta_label', p.cta_label || '');
    setField(form, 'cta_icon', p.cta_icon || '');
    setField(form, 'gallery_heading', p.gallery_heading || '');
    setField(form, 'features_heading', p.features_heading || '');
    setField(form, 'chart_heading', p.chart_heading || '');
    setField(form, 'chart_icon', p.chart_icon || '');
    setField(form, 'chart_spec', p.chart_spec ? JSON.stringify(p.chart_spec, null, 2) : '');

    const gallery = document.getElementById('galleryRows');
    const features = document.getElementById('featureRows');
    if (gallery) gallery.innerHTML = (p.gallery || []).map(galleryRowHtml).join('');
    if (features) features.innerHTML = (p.features || []).map(featureRowHtml).join('');
}

// Opening the blank form after an edit has to undo the edit: form.reset()
// restores the declared defaults but leaves the gallery and feature rows of
// the project that was being edited, and leaves onsubmit pointing at
// updateItem for that project's id.
function newProject() {
    const form = document.getElementById('addProjectForm');
    if (!form) return;
    form.reset();
    fillShowcaseFields(form, {});
    document.querySelector('#projectForm h3').textContent = 'New Project Details';
    document.querySelector('#projectForm button[type="submit"]').textContent = 'Save Project';
    form.onsubmit = async (e) => {
        e.preventDefault();
        attachShowcaseCollections(e.target);
        await addItem('projects', e.target);
    };
    showAddForm('project');
}

// The variable-length collections are not plain inputs, so they are attached
// to the FormData just before it is built. Notes are deliberately not edited
// here -- only one product uses them, and Django admin covers that case.
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

    // A checkbox posts "on" when ticked and nothing at all when not, so the
    // flag is carried as an explicit value instead -- an untouched box has to
    // read as false, not as "field absent, leave it alone".
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

// Bind initial submit
// The section is only rendered for holders of manage_projects, so the form
// may legitimately be absent.
const addProjectFormEl = document.getElementById('addProjectForm');
if (addProjectFormEl) {
    addProjectFormEl.onsubmit = async (e) => {
        e.preventDefault();
        attachShowcaseCollections(e.target);
        await addItem('projects', e.target);
    };
}
