/**
 * BranTech Chat Assistant
 * Uses Django sessions for anonymous users and database for logged-in users
 * Uses localStorage for chatbot open/closed state persistence
 */

class ChatAssistant {
  constructor() {
    this.threadId = null;
    this.isOpen = false;
    this.isLoading = false;
    this.messageHistory = [];
    
    // Django endpoints
    this.chatEndpoint = '/api/ai/chat/';
    this.historyEndpoint = '/api/ai/chat/history/';
    this.clearEndpoint = '/api/ai/chat/clear/';
    
    // DOM elements
    this.chatAssistant = document.getElementById('chatAssistant');
    this.chatToggle = document.getElementById('chatToggle');
    this.chatWindow = document.getElementById('chatWindow');
    this.chatClose = document.getElementById('chatClose');
    this.chatMessages = document.getElementById('chatMessages');
    this.chatInput = document.getElementById('chatInput');
    this.chatSend = document.getElementById('chatSend');
    this.chatTyping = document.getElementById('chatTyping');
    this.chatNotification = document.getElementById('chatNotification');
    this.typingMessageEl = null;
    
    this.init();
  }

  /**
   * Get CSRF token from cookies
   */
  getCsrfToken() {
    const name = 'csrftoken';
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  /**
   * Initialize the chat assistant
   */
  init() {
    // Generate or retrieve persistent thread_id from localStorage
    this.threadId = localStorage.getItem('brantech_chat_thread_id');
    if (!this.threadId) {
      this.threadId = 'anon_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
      localStorage.setItem('brantech_chat_thread_id', this.threadId);
    }

    // Load chatbot state from localStorage
    this.loadChatbotState();
    
    // Bind events
    this.bindEvents();
    
    // Load message history
    this.loadMessageHistory();
  }

  /**
   * Load chatbot open/closed state from localStorage
   */
  loadChatbotState() {
    const savedState = localStorage.getItem('brantech_chatbot_open');
    if (savedState === 'true') {
      this.openChat(false); // false = don't save state (we're loading it)
    }
  }

  /**
   * Save chatbot open/closed state to localStorage
   */
  saveChatbotState() {
    localStorage.setItem('brantech_chatbot_open', this.isOpen.toString());
  }

  /**
   * Bind event listeners
   */
  bindEvents() {
    // Toggle chat window
    this.chatToggle.addEventListener('click', () => this.toggleChat());
    this.chatClose.addEventListener('click', () => this.closeChat());
    
    // Send message
    this.chatSend.addEventListener('click', () => this.sendMessage());
    this.chatInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });
    
    // Enable/disable send button based on input
    this.chatInput.addEventListener('input', () => {
      const hasText = this.chatInput.value.trim().length > 0;
      this.chatSend.disabled = !hasText || this.isLoading;
    });
    
    // Close chat when clicking outside - use event delegation for better performance
    this.handleOutsideClick = (e) => {
      if (this.isOpen && !this.chatAssistant.contains(e.target)) {
        this.closeChat();
      }
    };
    document.addEventListener('click', this.handleOutsideClick);
    
    // Handle escape key
    this.handleEscapeKey = (e) => {
      if (e.key === 'Escape' && this.isOpen) {
        this.closeChat();
      }
    };
    document.addEventListener('keydown', this.handleEscapeKey);
    
    // Handle window resize with debouncing for better performance
    this.handleResize = this.debounce(() => {
      if (this.isOpen) {
        // Update body class based on current screen size
        if (window.innerWidth <= 768) {
          document.body.classList.add('chat-open');
        } else {
          document.body.classList.remove('chat-open');
        }
      }
    }, 250);
    window.addEventListener('resize', this.handleResize);
  }

  /**
   * Debounce function to limit the rate at which a function can fire
   */
  debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }

  /**
   * Clean up event listeners when destroying the instance
   */
  destroy() {
    if (this.handleOutsideClick) {
      document.removeEventListener('click', this.handleOutsideClick);
    }
    if (this.handleEscapeKey) {
      document.removeEventListener('keydown', this.handleEscapeKey);
    }
    if (this.handleResize) {
      window.removeEventListener('resize', this.handleResize);
    }
  }

  /**
   * Toggle chat window visibility
   */
  toggleChat() {
    if (this.isOpen) {
      this.closeChat();
    } else {
      this.openChat();
    }
  }

  /**
   * Open chat window
   */
  openChat(saveState = true) {
    this.isOpen = true;
    this.chatWindow.classList.add('open');
    this.chatToggle.style.transform = 'scale(0.9)';
    this.chatInput.focus();
    this.hideNotification();
    this.scrollToBottom();
    
    // Prevent body scrolling on mobile when chat is open
    if (window.innerWidth <= 768) {
      document.body.classList.add('chat-open');
    }
    
    // Save state to localStorage
    if (saveState) {
      this.saveChatbotState();
    }
  }

  /**
   * Close chat window
   */
  closeChat() {
    this.isOpen = false;
    this.chatWindow.classList.remove('open');
    this.chatToggle.style.transform = 'scale(1)';
    
    // Restore body scrolling when chat is closed
    document.body.classList.remove('chat-open');
    
    // Save state to localStorage
    this.saveChatbotState();
  }

  /**
   * Show notification badge
   */
  showNotification() {
    if (this.chatNotification) {
      this.chatNotification.style.display = 'flex';
    }
  }

  /**
   * Hide notification badge
   */
  hideNotification() {
    if (this.chatNotification) {
      this.chatNotification.style.display = 'none';
    }
  }

  /**
   * Load message history from Django
   */
  async loadMessageHistory() {
    try {
      const csrfToken = this.getCsrfToken();
      
      // Append thread_id to the URL query parameters
      const url = new URL(this.historyEndpoint, window.location.origin);
      if (this.threadId) {
        url.searchParams.append('thread_id', this.threadId);
      }

      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
      });

      if (response.ok) {
        const data = await response.json();
        // Always update thread_id from server response if provided
        if (data.thread_id) {
          this.threadId = data.thread_id;
          localStorage.setItem('brantech_chat_thread_id', this.threadId);
        }
        
        if (Array.isArray(data.messages) && data.messages.length > 0) {
          this.messageHistory = data.messages;
          this.displayMessageHistory();
        } else {
          console.log('No messages found in history');
        }
      } else {
        console.log('No message history found');
      }
    } catch (error) {
      console.log('Could not load message history:', error.message);
    }
  }

  /**
   * Display loaded message history
   */
  displayMessageHistory() {
    // Clear welcome message if we have history
    if (this.messageHistory.length > 0) {
      const welcomeMessage = this.chatMessages.querySelector('.chat-welcome');
      if (welcomeMessage) {
        welcomeMessage.remove();
      }
    }

    // Display each message
    this.messageHistory.forEach(message => {
      const role = message.role || 'user';
      const content = message.content || message.text || '';
      this.addMessageToChat(content, role, false);
    });

    this.scrollToBottom();
  }

  /**
   * Send message to chatbot
   */
  async sendMessage() {
    const message = this.chatInput.value.trim();
    if (!message || this.isLoading) return;

    // Add user message to chat
    this.addMessageToChat(message, 'user');
    
    // Clear input and disable send button
    this.chatInput.value = '';
    this.chatSend.disabled = true;
    this.isLoading = true;
    
    // Show typing indicator
    this.showTyping();
    
    try {
      const csrfToken = this.getCsrfToken();
      const response = await fetch(this.chatEndpoint, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({
          message: message,
          thread_id: this.threadId
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      // Hide typing indicator
      this.hideTyping();
      
      // Always update thread_id from server response (should always be present)
      if (data.thread_id) {
        this.threadId = data.thread_id;
        localStorage.setItem('brantech_chat_thread_id', this.threadId);
      } else {
        console.warn('Server did not return thread_id in response');
      }
      
      // Add assistant response to chat
      if (data.response) {
        this.addMessageToChat(data.response, 'assistant');
      } else {
        this.addErrorMessage('Sorry, I didn\'t receive a proper response. Please try again.');
      }
      
    } catch (error) {
      console.error('Chat error:', error);
      this.hideTyping();
      this.addErrorMessage('Sorry, I\'m having trouble connecting. Please check your internet connection and try again.');
    } finally {
      this.isLoading = false;
      this.chatSend.disabled = false;
      this.chatInput.focus();
    }
  }

  /**
   * Add message to chat interface
   */
  addMessageToChat(content, role, animate = true) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;
    
    const avatarDiv = document.createElement('div');
    avatarDiv.className = 'message-avatar';
    
    const avatarSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    avatarSvg.setAttribute('viewBox', '0 0 24 24');
    avatarSvg.setAttribute('fill', 'none');
    avatarSvg.setAttribute('stroke', 'currentColor');
    avatarSvg.setAttribute('stroke-width', '2');
    
    if (role === 'user') {
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2');
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', '12');
      circle.setAttribute('cy', '7');
      circle.setAttribute('r', '4');
      avatarSvg.appendChild(path);
      avatarSvg.appendChild(circle);
    } else {
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2');
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', '12');
      circle.setAttribute('cy', '7');
      circle.setAttribute('r', '4');
      avatarSvg.appendChild(path);
      avatarSvg.appendChild(circle);
    }
    
    avatarDiv.appendChild(avatarSvg);
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    // Render markdown for assistant messages, plain text for user messages
    if (role === 'assistant') {
      contentDiv.innerHTML = this.renderMarkdown(content);
    } else {
      contentDiv.textContent = content;
    }
    
    messageDiv.appendChild(avatarDiv);
    messageDiv.appendChild(contentDiv);
    
    // Add to chat messages
    this.chatMessages.appendChild(messageDiv);
    
    // Store in message history (only for new messages, not when loading from API)
    if (animate) {
      this.messageHistory.push({
        content: content,
        role: role,
        timestamp: new Date().toISOString()
      });
    }
    
    // Scroll to bottom
    this.scrollToBottom();
    
    // Show notification if chat is closed
    if (!this.isOpen && role === 'assistant') {
      this.showNotification();
    }
  }

  /**
   * Render markdown content to HTML
   */
  renderMarkdown(text) {
    if (!text) return '';
    
    // Escape HTML first to prevent XSS
    let html = this.escapeHtml(text);
    
    // Convert markdown to HTML
    html = this.convertMarkdownToHtml(html);
    
    return html;
  }

  /**
   * Escape HTML to prevent XSS attacks
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Convert markdown syntax to HTML
   */
  convertMarkdownToHtml(text) {
    if (!text) return '';
    
    // Code blocks first (to prevent other parsing from affecting them)
    text = text.replace(/```([\s\S]*?)```/g, '<pre><code class="code-block">$1</code></pre>');
    
    // Inline code: `code` (but not inside code blocks)
    text = text.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
    
    // Bold text: **text** or __text__
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/__(.*?)__/g, '<strong>$1</strong>');
    
    // Italic text: *text* or _text_ (but not inside code)
    text = text.replace(/(?<!<code[^>]*>)\*([^*]+)\*(?!<\/code>)/g, '<em>$1</em>');
    text = text.replace(/(?<!<code[^>]*>)_([^_]+)_(?!<\/code>)/g, '<em>$1</em>');
    
    // Headers: # Header, ## Header, ### Header
    text = text.replace(/^### (.*$)/gm, '<h3 class="markdown-h3">$1</h3>');
    text = text.replace(/^## (.*$)/gm, '<h2 class="markdown-h2">$1</h2>');
    text = text.replace(/^# (.*$)/gm, '<h1 class="markdown-h1">$1</h1>');
    
    // Links: [text](url)
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="markdown-link">$1</a>');
    
    // Lists: - item or * item (handle multiple items)
    text = text.replace(/^[\s]*[-*] (.*$)/gm, '<li class="markdown-li">$1</li>');
    // Wrap consecutive list items in ul tags
    text = text.replace(/(<li class="markdown-li">.*?<\/li>)(\s*<li class="markdown-li">.*?<\/li>)*/gs, (match) => {
      return '<ul class="markdown-ul">' + match + '</ul>';
    });
    
    // Numbered lists: 1. item (handle multiple items)
    text = text.replace(/^[\s]*\d+\. (.*$)/gm, '<li class="markdown-li">$1</li>');
    // Wrap consecutive numbered list items in ol tags
    text = text.replace(/(<li class="markdown-li">.*?<\/li>)(\s*<li class="markdown-li">.*?<\/li>)*/gs, (match) => {
      return '<ol class="markdown-ol">' + match + '</ol>';
    });
    
    // Line breaks: Convert double newlines to paragraphs
    text = text.replace(/\n\n/g, '</p><p class="markdown-p">');
    text = '<p class="markdown-p">' + text + '</p>';
    
    // Clean up empty paragraphs
    text = text.replace(/<p class="markdown-p"><\/p>/g, '');
    text = text.replace(/<p class="markdown-p">\s*<\/p>/g, '');
    
    // Convert single newlines to <br> (but not inside code blocks)
    text = text.replace(/(?<!<code[^>]*>)\n(?!<\/code>)/g, '<br>');
    
    return text;
  }

  /**
   * Add error message to chat
   */
  addErrorMessage(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    
    const errorSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    errorSvg.setAttribute('viewBox', '0 0 24 24');
    errorSvg.setAttribute('fill', 'none');
    errorSvg.setAttribute('stroke', 'currentColor');
    errorSvg.setAttribute('stroke-width', '2');
    
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z');
    errorSvg.appendChild(path);
    
    const errorText = document.createElement('span');
    errorText.textContent = message;
    
    errorDiv.appendChild(errorSvg);
    errorDiv.appendChild(errorText);
    
    this.chatMessages.appendChild(errorDiv);
    this.scrollToBottom();
  }

  /**
   * Show typing indicator
   */
  showTyping() {
    // If a typing bubble already exists, do nothing
    if (this.typingMessageEl) {
      this.scrollToBottom();
      return;
    }

    // Build a message-like typing bubble inside the messages stream
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant typing';

    const avatarDiv = document.createElement('div');
    avatarDiv.className = 'message-avatar';
    const avatarSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    avatarSvg.setAttribute('viewBox', '0 0 24 24');
    avatarSvg.setAttribute('fill', 'none');
    avatarSvg.setAttribute('stroke', 'currentColor');
    avatarSvg.setAttribute('stroke-width', '2');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2');
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', '12');
    circle.setAttribute('cy', '7');
    circle.setAttribute('r', '4');
    avatarSvg.appendChild(path);
    avatarSvg.appendChild(circle);
    avatarDiv.appendChild(avatarSvg);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    const typingWrap = document.createElement('div');
    typingWrap.className = 'typing-indicator';
    typingWrap.innerHTML = '<span></span><span></span><span></span>';
    contentDiv.appendChild(typingWrap);

    messageDiv.appendChild(avatarDiv);
    messageDiv.appendChild(contentDiv);

    this.chatMessages.appendChild(messageDiv);
    this.typingMessageEl = messageDiv;
    this.scrollToBottom();
  }

  /**
   * Hide typing indicator
   */
  hideTyping() {
    // Remove typing bubble from messages if present
    if (this.typingMessageEl && this.typingMessageEl.parentNode) {
      this.typingMessageEl.parentNode.removeChild(this.typingMessageEl);
    }
    this.typingMessageEl = null;
  }

  /**
   * Scroll chat to bottom
   */
  scrollToBottom() {
    setTimeout(() => {
      this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
    }, 100);
  }

  /**
   * Clear chat history
   */
  async clearHistory() {
    try {
      const csrfToken = this.getCsrfToken();
      const response = await fetch(this.clearEndpoint, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({
          thread_id: this.threadId
        })
      });

      if (response.ok) {
        this.messageHistory = [];
        const messages = this.chatMessages.querySelectorAll('.message, .error-message');
        messages.forEach(msg => msg.remove());
        
        // Restore welcome message
        const welcomeDiv = document.createElement('div');
        welcomeDiv.className = 'chat-welcome';
        welcomeDiv.innerHTML = `
          <div class="welcome-message">
            <div class="welcome-avatar">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
            </div>
            <div class="welcome-text">
              <p>Hello! I'm your BranTech Solutions assistant. I can help you with:</p>
              <ul>
                <li>Our services and solutions</li>
                <li>Project inquiries</li>
                <li>Technical support</li>
                <li>General questions</li>
              </ul>
              <p>What would you like to know?</p>
            </div>
          </div>
        `;
        this.chatMessages.appendChild(welcomeDiv);
        
        // Clear thread ID from localStorage and memory
        localStorage.removeItem('brantech_chat_thread_id');
        this.threadId = null;
        
        // Re-initialize a fresh anonymous thread ID for next message
        this.threadId = 'anon_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
        localStorage.setItem('brantech_chat_thread_id', this.threadId);
      }
    } catch (error) {
      console.error('Error clearing history:', error);
    }
  }
}

// Initialize chat assistant when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
  // Only initialize if chat assistant elements exist
  if (document.getElementById('chatAssistant')) {
    window.chatAssistant = new ChatAssistant();
    console.log('BranTech Chat Assistant initialized');
  }
});

// Export for potential external use
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ChatAssistant;
}
