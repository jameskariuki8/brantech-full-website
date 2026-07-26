document.addEventListener('DOMContentLoaded', function () {
    // Load navigation
    fetch('components/navigation.html')
        .then(response => response.text())
        .then(data => {
            const navHost = document.getElementById('navigation');
            navHost.innerHTML = data;

            // Highlight current page and set mobile indicator
            const current = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
            // Only highlight menu links, not the brand logo link
            const links = navHost.querySelectorAll('.desktop-nav a[href]');
            let currentLabel = '';
            links.forEach(a => {
                const href = a.getAttribute('href').toLowerCase();
                if (href === current) {
                    // remove conflicting pill styles
                    a.classList.remove('bg-white/80', 'text-[#0F172A]', 'border-slate-200');
                    a.classList.add('bg-[#1E3A8A]', 'text-white', 'border-[#1E3A8A]');
                    currentLabel = a.textContent.trim();
                }
            });
            // Mobile menu toggle
            const btn = navHost.querySelector('#nav-menu-btn');
            const panel = navHost.querySelector('#mobile-menu');
            if (btn && panel) {
                btn.addEventListener('click', () => {
                    const isOpen = panel.classList.toggle('hidden') === false;
                    btn.setAttribute('aria-expanded', String(isOpen));
                });
                // highlight active link in mobile list
                panel.querySelectorAll('a[href]').forEach(a => {
                    const href = a.getAttribute('href').toLowerCase();
                    if (href === current) {
                        a.classList.remove('text-[#0F172A]', 'border-slate-200');
                        a.classList.add('bg-[#1E3A8A]', 'text-white', 'border-[#1E3A8A]');
                    }
                });
            }

            // Prevent content from hiding under fixed nav
            const navEl = navHost.querySelector('nav');
            if (navEl) {
                const applyPad = () => {
                    const h = navEl.clientHeight; // more precise than offsetHeight for our case
                    document.body.style.paddingTop = (h > 0 ? h : 56) + 'px';
                };
                applyPad();
                window.addEventListener('resize', applyPad);
                // Update padding when navbar height changes (e.g., mobile menu opens)
                if (window.ResizeObserver) {
                    const ro = new ResizeObserver(applyPad);
                    ro.observe(navEl);
                }
            }
        });

    // Load footer
    fetch('components/footer.html')
        .then(response => response.text())
        .then(data => {
            document.getElementById('footer').innerHTML = data;
        });
});