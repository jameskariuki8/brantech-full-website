// Blog Integration Script
class BlogIntegration {
  constructor() {
    this.apiBase = window.location.hostname === 'localhost' ? 'http://localhost:8000/api' : '/api';
    this.init();
  }

  async init() {
    // Add blog preview to homepage if we're on index.html
    if (window.location.pathname.includes('index.html') || window.location.pathname === '/') {
      this.addBlogPreviewToHomepage();
    }
  }

  async addBlogPreviewToHomepage() {
    try {
      const posts = await this.fetchLatestPosts(3);
      this.insertBlogSection(posts);
    } catch (error) {
      console.log('Blog integration not available:', error);
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
    blogSection.innerHTML = `
      <div class="max-w-6xl mx-auto">
        <div class="text-center mb-12">
          <h2 class="text-3xl md:text-4xl font-bold text-gray-900 mb-4">Latest from Our Blog</h2>
          <p class="text-lg text-gray-600">Stay updated with the latest tech insights and industry trends</p>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 mb-8">
          ${posts.map(post => this.createBlogCard(post)).join('')}
        </div>
        <div class="text-center">
          <a href="blog.html" class="inline-flex items-center px-6 py-3 bg-gradient-to-r from-blue-600 to-green-600 text-white font-semibold rounded-lg hover:shadow-lg transition-all duration-300 hover:-translate-y-1">
            <i class="fas fa-blog mr-2"></i>
            View All Posts
          </a>
        </div>
      </div>
    `;

    footer.parentNode.insertBefore(blogSection, footer);
  }

  createBlogCard(post) {
    const imageUrl = post.image ? 
      (window.location.hostname === 'localhost' ? `http://localhost:8000${post.image}` : post.image) : 
      'https://images.unsplash.com/photo-1518709268805-4e9042af2176?auto=format&fit=crop&w=400&q=80';

    return `
      <article class="bg-white rounded-xl shadow-lg overflow-hidden hover:shadow-xl transition-all duration-300 hover:-translate-y-2">
        <div class="h-48 overflow-hidden">
          <img src="${imageUrl}" alt="${post.title}" class="w-full h-full object-cover hover:scale-105 transition-transform duration-300">
        </div>
        <div class="p-6">
          <div class="text-sm text-blue-600 font-medium mb-2">${new Date(post.created_at).toLocaleDateString()}</div>
          <h3 class="text-xl font-bold text-gray-900 mb-3 line-clamp-2">${post.title}</h3>
          <p class="text-gray-600 mb-4 line-clamp-3">${post.excerpt}</p>
          <div class="flex flex-wrap gap-2 mb-4">
            ${post.tags_list ? post.tags_list.slice(0, 2).map(tag => 
              `<span class="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">${tag}</span>`
            ).join('') : ''}
          </div>
          <a href="blog.html" class="inline-flex items-center text-blue-600 font-semibold hover:text-blue-800 transition-colors">
            Read More <i class="fas fa-arrow-right ml-1"></i>
          </a>
        </div>
      </article>
    `;
  }
}

// Initialize blog integration when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new BlogIntegration();
});