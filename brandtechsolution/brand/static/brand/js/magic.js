// Techlora Interactive Script

document.addEventListener('DOMContentLoaded', () => {

    // Typewriter Effect
    const typewriterElement = document.getElementById('typewriter');
    const consoleTrigger = document.getElementById('consoleTrigger');
    const revealMessage = document.getElementById('revealMessage');

    const textToType = "./init_teklora_systems.sh --force";
    let charIndex = 0;
    let isTyping = false;
    let hasTyped = false;

    function typeText() {
        if (charIndex < textToType.length) {
            typewriterElement.textContent += textToType.charAt(charIndex);
            charIndex++;
            setTimeout(typeText, 50 + Math.random() * 50); // Random typing speed
        } else {
            // Typing finished
            setTimeout(() => {
                // Reveal message after typing
                revealMessage.classList.remove('hidden');
                gsap.fromTo(revealMessage, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.5 });

                // Wait and then reset to loop
                setTimeout(() => {
                    revealMessage.classList.add('hidden');
                    typewriterElement.textContent = "";
                    charIndex = 0;
                    typeText();
                }, 3000); // 3-second pause before restarting

            }, 500);
        }
    }

    // Trigger typing on click or scroll into view
    if (consoleTrigger) {
        consoleTrigger.addEventListener('click', () => {
            if (!isTyping && !hasTyped) {
                isTyping = true;
                typeText();
            }
        });

        // Also trigger on scroll
        ScrollTrigger.create({
            trigger: consoleTrigger,
            start: "top 80%",
            onEnter: () => {
                if (!isTyping && !hasTyped) {
                    isTyping = true;
                    typeText();
                }
            }
        });
    }

    // GSAP Animations for Cards
    gsap.utils.toArray('.tech-card').forEach((card, i) => {
        gsap.from(card, {
            scrollTrigger: {
                trigger: card,
                start: "top 90%"
            },
            y: 50,
            opacity: 0,
            duration: 0.6,
            delay: i * 0.1,
            ease: "power2.out"
        });
    });

    // Hero Image Parallax - Removed as per user request
    /*
    gsap.to(".hero-image-container", {
        scrollTrigger: {
            trigger: "body",
            start: "top top",
            end: "bottom top",
            scrub: 1
        },
        y: 100
    });
    */

});
