/* ============================================================
   Teklora toast notifications + honest API errors
   ------------------------------------------------------------
   Replaces window.alert()/window.confirm() across the admin panel,
   the editorial dashboard and the public pages.

   Exposes:
     showToast(message, type, opts)  -> id
     toast.success/error/warning/info(message, opts)
     toast.dismiss(id) / toast.clear()
     tkConfirm(message, opts)        -> Promise<boolean>
     fetchJson(url, options)         -> Promise<data>   (throws ApiError)
     toastApiError(err, fallback)
     ApiError

   Loaded as a classic script (no module) because every consumer is a
   plain <script defer> include.
   ============================================================ */
(function () {
  'use strict';

  var DEFAULT_DURATION = 5000;
  var ERROR_DURATION = 9000;   // errors carry detail worth reading
  var MAX_VISIBLE = 4;

  var ICONS = {
    success: '✓',
    error: '✕',
    warning: '!',
    info: 'i'
  };

  var TITLES = {
    success: 'Done',
    error: 'Something went wrong',
    warning: 'Heads up',
    info: 'Notice'
  };

  var region = null;
  var counter = 0;
  var live = new Map();

  function ensureRegion() {
    if (region && document.body.contains(region)) return region;
    region = document.createElement('div');
    region.className = 'tk-toast-region';
    // polite: a toast is supplementary, it shouldn't interrupt a screen
    // reader mid-sentence. Errors escalate to assertive per-toast.
    region.setAttribute('role', 'region');
    region.setAttribute('aria-label', 'Notifications');
    document.body.appendChild(region);
    return region;
  }

  function dismiss(id) {
    var el = live.get(id);
    if (!el) return;
    live.delete(id);
    el.classList.remove('tk-toast--in');
    el.classList.add('tk-toast--out');
    var done = function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    };
    el.addEventListener('transitionend', done, { once: true });
    setTimeout(done, 400); // belt and braces if the transition never fires
  }

  function showToast(message, type, opts) {
    opts = opts || {};
    type = ICONS[type] ? type : 'info';

    var host = ensureRegion();
    var id = ++counter;

    // Keep the stack readable — drop the oldest beyond the cap.
    var ids = Array.from(live.keys());
    while (ids.length >= MAX_VISIBLE) dismiss(ids.shift());

    var duration = opts.duration;
    if (duration === undefined) {
      duration = type === 'error' ? ERROR_DURATION : DEFAULT_DURATION;
    }

    var el = document.createElement('div');
    el.className = 'tk-toast tk-toast--' + type;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');

    var icon = document.createElement('span');
    icon.className = 'tk-toast__icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = ICONS[type];

    var body = document.createElement('div');
    body.className = 'tk-toast__body';

    var title = document.createElement('p');
    title.className = 'tk-toast__title';
    title.textContent = opts.title || TITLES[type];

    var msg = document.createElement('p');
    msg.className = 'tk-toast__message';
    // textContent throughout: messages routinely carry server strings.
    msg.textContent = message == null ? '' : String(message);

    body.appendChild(title);
    body.appendChild(msg);

    if (opts.detail) {
      var detail = document.createElement('pre');
      detail.className = 'tk-toast__detail';
      detail.textContent = String(opts.detail);
      body.appendChild(detail);
    }

    var close = document.createElement('button');
    close.className = 'tk-toast__close';
    close.type = 'button';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.textContent = '✕';
    close.addEventListener('click', function () { dismiss(id); });

    el.appendChild(icon);
    el.appendChild(body);
    el.appendChild(close);

    if (duration > 0) {
      var timer = document.createElement('span');
      timer.className = 'tk-toast__timer';
      timer.style.animationDuration = duration + 'ms';
      timer.addEventListener('animationend', function () { dismiss(id); });
      el.appendChild(timer);
    }

    host.appendChild(el);
    live.set(id, el);

    // Next frame so the entry transition actually runs.
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { el.classList.add('tk-toast--in'); });
    });

    return id;
  }

  /* ---------------------------------------------------------- */
  /* Confirm dialog                                             */
  /* ---------------------------------------------------------- */

  function tkConfirm(message, opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      var backdrop = document.createElement('div');
      backdrop.className = 'tk-confirm-backdrop';
      if (opts.danger) backdrop.classList.add('tk-confirm--danger');

      var panel = document.createElement('div');
      panel.className = 'tk-confirm';
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-modal', 'true');

      var title = document.createElement('h2');
      title.className = 'tk-confirm__title';
      title.textContent = opts.title || 'Are you sure?';

      var msg = document.createElement('p');
      msg.className = 'tk-confirm__message';
      msg.textContent = message == null ? '' : String(message);

      var titleId = 'tk-confirm-title-' + (++counter);
      title.id = titleId;
      panel.setAttribute('aria-labelledby', titleId);

      var actions = document.createElement('div');
      actions.className = 'tk-confirm__actions';

      var cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'tk-confirm__btn tk-confirm__btn--cancel';
      cancel.textContent = opts.cancelText || 'Cancel';

      var ok = document.createElement('button');
      ok.type = 'button';
      ok.className = 'tk-confirm__btn tk-confirm__btn--confirm';
      ok.textContent = opts.confirmText || 'Confirm';

      actions.appendChild(cancel);
      actions.appendChild(ok);
      panel.appendChild(title);
      panel.appendChild(msg);
      panel.appendChild(actions);
      backdrop.appendChild(panel);
      document.body.appendChild(backdrop);

      var previouslyFocused = document.activeElement;
      var settled = false;

      function close(result) {
        if (settled) return;
        settled = true;
        document.removeEventListener('keydown', onKey, true);
        backdrop.classList.remove('tk-confirm--in');
        setTimeout(function () {
          if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
          if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
        }, 200);
        resolve(result);
      }

      function onKey(e) {
        if (e.key === 'Escape') { e.preventDefault(); close(false); return; }
        if (e.key !== 'Tab') return;
        // Trap focus between the two buttons.
        e.preventDefault();
        (document.activeElement === ok ? cancel : ok).focus();
      }

      cancel.addEventListener('click', function () { close(false); });
      ok.addEventListener('click', function () { close(true); });
      backdrop.addEventListener('mousedown', function (e) {
        if (e.target === backdrop) close(false);
      });
      document.addEventListener('keydown', onKey, true);

      requestAnimationFrame(function () {
        backdrop.classList.add('tk-confirm--in');
        ok.focus();
      });
    });
  }

  /* ---------------------------------------------------------- */
  /* API errors                                                 */
  /* ---------------------------------------------------------- */

  function ApiError(message, info) {
    var err = Error.call(this, message);
    this.name = 'ApiError';
    this.message = message;
    this.stack = err.stack;
    info = info || {};
    this.status = info.status || 0;
    this.detail = info.detail || '';
    this.data = info.data || null;
    this.url = info.url || '';
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  function looksLikeHtml(text) {
    return /^\s*(<!doctype|<html)/i.test(text || '');
  }

  // Django's DEBUG error page puts the exception in <title>, e.g.
  // "IntegrityError at /editorial/api/articles/3/approve/". That is by far
  // the most useful thing in a 500, so surface it instead of "<!DOCTYPE".
  function htmlSummary(text) {
    var m = /<title[^>]*>([\s\S]*?)<\/title>/i.exec(text || '');
    if (!m) return '';
    return m[1].replace(/\s+/g, ' ').trim().slice(0, 200);
  }

  function describeStatus(status, text) {
    switch (status) {
      case 0:   return 'Could not reach the server. Check your connection and try again.';
      case 401: return 'Your session has expired. Sign in again to continue.';
      case 403: return 'You do not have permission to do that.';
      case 404: return 'That endpoint was not found.';
      case 405: return 'That action is not allowed here.';
      case 413: return 'The upload was too large.';
      case 429: return 'Too many requests. Give it a moment and retry.';
      case 502:
      case 503: return 'The server is unavailable right now. Try again shortly.';
      case 504:
      case 524: return 'The request timed out before the server finished. The work may still be running in the background.';
      default:
        if (status >= 500) return 'The server hit an error while handling that request.';
        if (looksLikeHtml(text)) return 'The server returned a web page instead of data.';
        return 'The request failed.';
    }
  }

  // Pull the human-facing message out of whatever shape the API returned.
  function extractDetail(data) {
    if (!data || typeof data !== 'object') return '';
    if (typeof data.detail === 'string') return data.detail;
    if (typeof data.error === 'string') return data.error;
    if (typeof data.message === 'string') return data.message;
    // DRF field errors: {"email": ["Enter a valid email address."]}
    for (var key in data) {
      if (!Object.prototype.hasOwnProperty.call(data, key)) continue;
      var v = data[key];
      if (Array.isArray(v) && typeof v[0] === 'string') return v[0];
    }
    return '';
  }

  /**
   * fetch() that always resolves to parsed JSON or throws an ApiError
   * carrying the real status and cause. Never lets an HTML error page
   * surface as "Unexpected token '<'".
   */
  async function fetchJson(url, options) {
    options = options || {};
    var res;
    var raw = '';

    try {
      res = await fetch(url, Object.assign({ credentials: 'same-origin' }, options));
    } catch (networkErr) {
      throw new ApiError(describeStatus(0), {
        status: 0,
        detail: networkErr && networkErr.message ? networkErr.message : '',
        url: url
      });
    }

    try {
      raw = await res.text();
    } catch (readErr) {
      raw = '';
    }

    var data = null;
    if (raw) {
      try { data = JSON.parse(raw); } catch (e) { data = null; }
    }

    if (res.ok && data !== null) return data;

    // 204 No Content / empty 200 -- a successful DELETE has nothing to parse.
    if (res.ok && !raw.trim()) return null;

    if (res.ok) {
      // 2xx that isn't JSON — an auth redirect landing on a login page is
      // the usual culprit, since fetch follows redirects transparently.
      throw new ApiError(
        looksLikeHtml(raw)
          ? 'The server returned a web page instead of data. Your session may have expired.'
          : 'The server returned an unreadable response.',
        { status: res.status, detail: htmlSummary(raw) || raw.slice(0, 200), url: url }
      );
    }

    var detail = extractDetail(data);
    var message = detail || describeStatus(res.status, raw);
    var technical = 'HTTP ' + res.status + (res.statusText ? ' ' + res.statusText : '');
    var summary = data === null ? htmlSummary(raw) : '';
    if (summary) technical += '\n' + summary;

    throw new ApiError(message, {
      status: res.status,
      detail: technical,
      data: data,
      url: url
    });
  }

  /**
   * Build an ApiError from a failed Response whose body has NOT been read yet.
   * For call sites that still branch on res.ok themselves rather than using
   * fetchJson.
   */
  async function apiErrorFromResponse(res) {
    var raw = '';
    try { raw = await res.text(); } catch (e) { raw = ''; }

    var data = null;
    if (raw) {
      try { data = JSON.parse(raw); } catch (e) { data = null; }
    }

    var detail = extractDetail(data);
    var technical = 'HTTP ' + res.status + (res.statusText ? ' ' + res.statusText : '');
    var summary = data === null ? htmlSummary(raw) : '';
    if (summary) technical += '\n' + summary;

    return new ApiError(detail || describeStatus(res.status, raw), {
      status: res.status,
      detail: technical,
      data: data,
      url: res.url || ''
    });
  }

  /** Show any thrown error as an error toast, with technical detail attached. */
  function toastApiError(err, fallback) {
    if (err instanceof ApiError) {
      return showToast(err.message, 'error', { detail: err.detail || undefined });
    }
    var msg = err && err.message ? err.message : String(err || '');
    return showToast(fallback || msg || 'The request failed.', 'error', {
      detail: fallback && msg && fallback !== msg ? msg : undefined
    });
  }

  /* ---------------------------------------------------------- */

  var toast = {
    success: function (m, o) { return showToast(m, 'success', o); },
    error:   function (m, o) { return showToast(m, 'error', o); },
    warning: function (m, o) { return showToast(m, 'warning', o); },
    info:    function (m, o) { return showToast(m, 'info', o); },
    dismiss: dismiss,
    clear:   function () { Array.from(live.keys()).forEach(dismiss); }
  };

  window.showToast = showToast;
  window.toast = toast;
  window.tkConfirm = tkConfirm;
  window.fetchJson = fetchJson;
  window.apiErrorFromResponse = apiErrorFromResponse;
  window.toastApiError = toastApiError;
  window.ApiError = ApiError;
})();
