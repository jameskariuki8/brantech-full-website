async function loadBlogs() {
    try {
        const response = await fetch(`${API_BASE}/posts/`, { credentials: 'same-origin' });
        const payload = await response.json();
        // /api/posts/ is paginated and answers {results, pagination}. Older
        // callers here assumed a bare array, which made the list permanently
        // read "No posts found" and put the Edit button out of reach.
        const blogs = Array.isArray(payload) ? payload : (payload.results || []);
        const container = document.getElementById('blogsList');
        if (!container) return;
        if (!blogs.length) {
            container.innerHTML = `<div class="text-center py-10 text-gray-600">No posts found. Create your first one!</div>`;
            return;
        }
        container.innerHTML = blogs.map(blog => `
            <div class="bg-dark-card border border-dark-border p-5 rounded-lg flex flex-col md:flex-row justify-between items-start gap-4 hover:border-brand-blue/30 transition-colors group">
                <div class="flex-1">
                    <div class="flex items-center gap-2 mb-2">
                        <span class="text-xs font-bold px-2 py-1 rounded uppercase ${blog.status === 'published' ? 'text-brand-green bg-green-900/20' : 'text-gray-400 bg-white/5'}">${escapeHtml(blog.status || 'draft')}</span>
                        <span class="text-xs font-bold text-brand-blue px-2 py-1 bg-blue-900/20 rounded uppercase">${escapeHtml(blog.category)}</span>
                        ${blog.featured ? '<span class="text-xs font-bold text-purple-400 px-2 py-1 bg-purple-900/20 rounded">FEATURED</span>' : ''}
                        <span class="text-gray-500 text-xs">${escapeHtml(new Date(blog.created_at).toLocaleDateString())}</span>
                    </div>
                    <h3 class="text-xl font-bold text-white mb-2 group-hover:text-brand-blue transition-colors">${escapeHtml(blog.title)}</h3>
                    <p class="text-gray-400 text-sm line-clamp-2 mb-3">${escapeHtml(blog.excerpt || '')}</p>
                    <div class="flex items-center text-xs text-gray-500 gap-4">
                        <span><i class="fas fa-eye mr-1"></i>${blog.view_count || 0}</span>
                    </div>
                </div>
                <div class="flex gap-2">
                    <button onclick="editBlog(${blog.id})" class="p-2 text-blue-400 hover:bg-blue-900/30 rounded-lg transition-colors"><i class="fas fa-edit"></i></button>
                    <button onclick="deleteItem('posts', ${blog.id})" class="p-2 text-red-400 hover:bg-red-900/30 rounded-lg transition-colors"><i class="fas fa-trash"></i></button>
                </div>
            </div>
        `).join('');
    } catch (e) { console.error(e); }
}

// Edit Pre-fill
async function editBlog(id) {
    try {
        const blog = await fetch(`${API_BASE}/posts/${id}/`).then(r => r.json());
        const form = document.getElementById('addBlogForm');
        form.title.value = blog.title;
        form.category.value = blog.category;
        form.excerpt.value = blog.excerpt;
        form.content.value = blog.content;
        form.tags.value = blog.tags;
        form.featured.checked = blog.featured;
        // Must reflect the post's real status even when the control is
        // disabled: otherwise the select would sit on its default and, for a
        // user who does hold publish_blog, an ordinary edit of a published
        // post would silently unpublish it.
        if (form.status) form.status.value = blog.status || 'draft';

        document.querySelector('#blogForm h3').textContent = 'Edit Blog Post';
        const btn = document.querySelector('#blogForm button[type="submit"]');
        btn.textContent = 'Update Post';

        form.onsubmit = async (e) => { e.preventDefault(); await updateItem('posts', id, e.target); };
        showAddForm('blog');
    } catch (e) { console.error(e); }
}

// Bind initial submit. The section is only rendered for holders of
// manage_blog, so the form may legitimately be absent.
const addBlogFormEl = document.getElementById('addBlogForm');
if (addBlogFormEl) {
    addBlogFormEl.onsubmit = async (e) => { e.preventDefault(); await addItem('posts', e.target); };
}
