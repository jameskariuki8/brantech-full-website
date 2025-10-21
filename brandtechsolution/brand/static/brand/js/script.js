// BranTech Script (Tabs, Animations, Mobile Menu, Active Links)
document.addEventListener('DOMContentLoaded', function () {
  /** -------------------
   * TAB SWITCHING
   * ------------------- */
  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  if (tabButtons.length > 0) {
    tabButtons.forEach((button) => {
      button.addEventListener('click', () => {
        tabButtons.forEach((btn) => btn.classList.remove('tab-active'));
        tabContents.forEach((content) => content.classList.add('hidden'));

        button.classList.add('tab-active');
        const tabId = button.getAttribute('data-tab') + '-tab';
        document.getElementById(tabId).classList.remove('hidden');
      });
    });
  }

  /** -------------------
   * ANIMATION OBSERVER (Services Cards)
   * ------------------- */
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate__animated', 'animate__fadeInUp');
        }
      });
    },
    { threshold: 0.1 }
  );

  // Target fancy service cards
  document.querySelectorAll('#services .service-card-fancy').forEach((card) => {
    observer.observe(card);
  });

  /** -------------------
   * MOBILE MENU TOGGLE (hamburger + dropdown)
   * ------------------- */
  const hamburger = document.getElementById('hamburger');
  const mobileNav = document.getElementById('mobileNav');

  if (hamburger && mobileNav) {
    hamburger.addEventListener('click', () => {
      mobileNav.classList.toggle('open');
    });

    // Close menu on link click
    mobileNav.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        mobileNav.classList.remove('open');
      });
    });
  }

  /** -------------------
   * ACTIVE NAV LINK (Desktop + Mobile)
   * ------------------- */
  const currentPage = window.location.pathname.split('/').pop();
  const navLinks = document.querySelectorAll('.nav-links a, #mobileNav a');

  navLinks.forEach((link) => {
    link.classList.remove('active');

    if (
      link.getAttribute('href') === currentPage ||
      (currentPage === '' && link.getAttribute('href') === 'index.html')
    ) {
      link.classList.add('active');
    }
  });
});