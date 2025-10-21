document.addEventListener('DOMContentLoaded', () => {
  loadComponents();
});

function loadComponents() {
  const components = ['header', 'footer'];
  let loadedCount = 0;

  components.forEach(id => {
    const element = document.getElementById(id);
    if (!element) return;

    fetch(`partials/${id}.html`)
      .then(res => {
        if (!res.ok) throw new Error(`Failed to fetch ${id}.html`);
        return res.text();
      })
      .then(html => {
        element.innerHTML = html;
        if (id === 'header') {
          executeInlineScripts(element);
          insertHeaderSpacer(element);
        }
        loadedCount++;
        if (loadedCount === components.length) initializeAllFeatures();
      })
      .catch(err => console.warn(`Error loading ${id}:`, err.message));
  });
}

function initializeAllFeatures() {
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      const href = this.getAttribute('href');
      if (!href || href === '#') return;
      const target = document.querySelector(href);
      if (target) {
        e.preventDefault();
        window.scrollTo({ top: target.offsetTop - 120, behavior: 'smooth' });
      }
    });
  });
}

function insertHeaderSpacer(headerContainer) {
  if (!headerContainer) return;
  const spacer = document.createElement('div');
  spacer.className = 'header-spacer';
  // Insert right after the header container
  headerContainer.insertAdjacentElement('afterend', spacer);
}

function executeInlineScripts(container) {
  const scripts = container.querySelectorAll('script');
  scripts.forEach(oldScript => {
    const s = document.createElement('script');
    if (oldScript.src) {
      s.src = oldScript.src;
    } else {
      s.textContent = oldScript.textContent;
    }
    document.body.appendChild(s);
    oldScript.remove();
  });
}