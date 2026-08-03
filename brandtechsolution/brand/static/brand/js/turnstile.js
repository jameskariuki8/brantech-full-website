// Reads the Turnstile token for forms submitted by JavaScript.
//
// The widget injects a hidden <input name="cf-turnstile-response"> into its
// own container once the challenge is solved. A form posted normally sends
// that input for free; a fetch() has to pick it up and put it in the payload.
//
// Returns '' when the widget is absent (keys unset) or unsolved. The server
// treats an empty token as a failure whenever checks are enabled, and ignores
// it entirely when they are not, so returning '' is always safe.
function turnstileToken(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return '';
    const field = container.querySelector('[name="cf-turnstile-response"]');
    return field ? field.value : '';
}

// Turnstile tokens are single-use. After a submission the widget has to be
// reset or the next attempt replays a token Cloudflare has already retired,
// which reads to the visitor as "it worked once and now it refuses me".
function resetTurnstile(containerId) {
    if (typeof turnstile === 'undefined') return;
    const container = document.getElementById(containerId);
    if (container) turnstile.reset(container);
}
