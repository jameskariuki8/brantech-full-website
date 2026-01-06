// Blog Integration Script (adapted for Django paths)
class BlogIntegration {
  constructor() {
    this.apiBase = '/api';
    this.init();
  }

  async init() {
    this.addBlogPreviewToHomepage();
  }

  async addBlogPreviewToHomepage() {
    try {
      const posts = await this.fetchLatestPosts(3);
      this.insertBlogSection(posts);
    } catch (error) {
      // ignore silently
    }
  }

  async fetchLatestPosts(limit = 3) {
    const response = await fetch(`${this.apiBase}/posts/?limit=${limit}`);
    if (!response.ok) throw new Error('Failed to fetch posts');
    const posts = await response.json();
    return posts.slice(0, limit);
  }

  insertBlogSection(posts) {
    const footer = document.getElementById('footer');
    if (!footer || posts.length === 0) return;

    const blogSection = document.createElement('section');
    blogSection.className = 'py-16 px-6 bg-gradient-to-br from-gray-50 to-blue-50';
    
    // Create the structure more efficiently
    const container = document.createElement('div');
    container.className = 'max-w-6xl mx-auto';
    
    // Header section
    const header = document.createElement('div');
    header.className = 'text-center mb-12';
    header.innerHTML = `
      <h2 class="text-3xl md:text-4xl font-bold text-gray-900 mb-4">Latest from Our Blog</h2>
      <p class="text-lg text-gray-600">Stay updated with the latest tech insights and industry trends</p>
    `;
    
    // Grid section - use document fragment for better performance
    const grid = document.createElement('div');
    grid.className = 'grid grid-cols-1 md:grid-cols-3 gap-8 mb-8';
    
    const fragment = document.createDocumentFragment();
    posts.forEach(post => {
      const article = this.createBlogCardElement(post);
      fragment.appendChild(article);
    });
    grid.appendChild(fragment);
    
    // View all button section
    const buttonSection = document.createElement('div');
    buttonSection.className = 'text-center';
    buttonSection.innerHTML = `
      <a href="/blog/" class="inline-flex items-center px-6 py-3 bg-gradient-to-r from-blue-600 to-green-600 text-white font-semibold rounded-lg hover:shadow-lg transition-all duration-300 hover:-translate-y-1">
        <i class="fas fa-blog mr-2"></i>
        View All Posts
      </a>
    `;
    
    // Assemble everything
    container.appendChild(header);
    container.appendChild(grid);
    container.appendChild(buttonSection);
    blogSection.appendChild(container);
    
    footer.parentNode.insertBefore(blogSection, footer);
  }

  createBlogCardElement(post) {
    const article = document.createElement('article');
    article.className = 'bg-white rounded-xl shadow-lg overflow-hidden hover:shadow-xl transition-all duration-300 hover:-translate-y-2';
    article.innerHTML = this.createBlogCard(post);
    return article;
  }

  createBlogCard(post) {
    // Helper function to escape HTML to prevent XSS
    const escapeHtml = (text) => {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    };
    
    const imageUrl = post.image || 'https://images.unsplash.com/photo-1518709268805-4e9042af2176?auto=format&fit=crop&w=400&q=80';
    const date = new Date(post.created_at).toLocaleDateString();
    
    // Escape user-generated content to prevent XSS
    const safeTitle = escapeHtml(post.title);
    const safeExcerpt = escapeHtml(post.excerpt);
    
    const tagsHtml = post.tags_list ? post.tags_list.slice(0, 2).map(tag => 
      `<span class="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">${escapeHtml(tag)}</span>`
    ).join('') : '';
    
    return `
      <div class="h-48 overflow-hidden">
        <img src="${imageUrl}" alt="${safeTitle}" class="w-full h-full object-cover hover:scale-105 transition-transform duration-300" loading="lazy">
      </div>
      <div class="p-6">
        <div class="text-sm text-blue-600 font-medium mb-2">${date}</div>
        <h3 class="text-xl font-bold text-gray-900 mb-3 line-clamp-2">${safeTitle}</h3>
        <p class="text-gray-600 mb-4 line-clamp-3">${safeExcerpt}</p>
        <div class="flex flex-wrap gap-2 mb-4">
          ${tagsHtml}
        </div>
        <a href="/blog/" class="inline-flex items-center text-blue-600 font-semibold hover:text-blue-800 transition-colors">
          Read More <i class="fas fa-arrow-right ml-1"></i>
        </a>
      </div>
    `;
  }
}

document.addEventListener('DOMContentLoaded', () => { new BlogIntegration(); });


