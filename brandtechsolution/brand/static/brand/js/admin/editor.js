// Shared email-body editor: Quill with an email-safe toolbar, placeholder
// insertion, a raw-HTML source toggle, and server-rendered preview.
// Alignment and indentation are deliberately excluded: Quill implements them
// with CSS classes that email clients discard.

const EMAIL_TOOLBAR = [
    ['bold', 'italic', 'underline'],
    [{ header: [2, 3, false] }],
    ['link', 'blockquote'],
    [{ list: 'ordered' }, { list: 'bullet' }],
    ['clean'],
];

let PLACEHOLDER_CACHE = null;
const EMAIL_EDITORS = {};

async function loadPlaceholderRegistry() {
    if (PLACEHOLDER_CACHE) return PLACEHOLDER_CACHE;
    const res = await fetch(`${API_BASE}/messaging/placeholders/`, { credentials: 'same-origin' });
    PLACEHOLDER_CACHE = res.ok ? await res.json() : [];
    return PLACEHOLDER_CACHE;
}

function renderPlaceholderMenu(menuEl, onPick) {
    if (!menuEl) return;
    loadPlaceholderRegistry().then(entries => {
        menuEl.innerHTML =
            `<option value="">Insert placeholder…</option>` +
            entries.map(e =>
                `<option value="${escapeHtml(e.key)}" title="${escapeHtml(e.description)}">${escapeHtml(e.label)}</option>`
            ).join('');
        menuEl.onchange = () => {
            if (menuEl.value) { onPick(menuEl.value); menuEl.value = ''; }
        };
    });
}

function insertAtCaret(input, text) {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    input.value = input.value.slice(0, start) + text + input.value.slice(end);
    const pos = start + text.length;
    input.setSelectionRange(pos, pos);
    input.focus();
}

function createEmailEditor(prefix) {
    const container = document.getElementById(`${prefix}EditorContainer`);
    if (!container) return undefined;

    const textarea = document.getElementById(`${prefix}SourceTextarea`);
    const toggleBtn = document.getElementById(`${prefix}SourceToggle`);
    const previewBtn = document.getElementById(`${prefix}PreviewBtn`);
    const frame = document.getElementById(`${prefix}PreviewFrame`);
    const warning = document.getElementById(`${prefix}UnknownWarning`);
    const subjectInput = document.getElementById(`${prefix}SubjectInput`);

    const quill = new Quill(container, {
        theme: 'snow',
        modules: { toolbar: EMAIL_TOOLBAR },
        placeholder: 'Write your email…',
    });

    let sourceMode = false;

    const editor = {
        getValue() {
            return sourceMode ? textarea.value : quill.root.innerHTML;
        },
        setValue(html) {
            const value = html || '';
            textarea.value = value;
            quill.root.innerHTML = value;
        },
        toggleSource() {
            if (sourceMode) {
                // Source -> visual. Quill may normalise markup it cannot model.
                if (!confirm('Switch back to the visual editor? It may simplify HTML it does not support.')) return;
                quill.root.innerHTML = textarea.value;
                textarea.classList.add('hidden');
                container.classList.remove('hidden');
                document.querySelector(`#${prefix}EditorWrap .ql-toolbar`)?.classList.remove('hidden');
                toggleBtn.textContent = 'Source';
            } else {
                textarea.value = quill.root.innerHTML;
                container.classList.add('hidden');
                document.querySelector(`#${prefix}EditorWrap .ql-toolbar`)?.classList.add('hidden');
                textarea.classList.remove('hidden');
                toggleBtn.textContent = 'Visual';
            }
            sourceMode = !sourceMode;
        },
        insertPlaceholder(key) {
            const token = `{{ ${key} }}`;
            if (sourceMode) { insertAtCaret(textarea, token); return; }
            const range = quill.getSelection(true);
            quill.insertText(range ? range.index : quill.getLength(), token, 'user');
        },
        async preview() {
            const res = await fetch(`${API_BASE}/messaging/preview/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF_TOKEN },
                body: JSON.stringify({
                    subject: subjectInput ? subjectInput.value : '',
                    body_source: editor.getValue(),
                }),
            });
            if (!res.ok) { alert('Preview failed'); return; }
            const data = await res.json();
            if (frame) {
                frame.classList.remove('hidden');
                frame.srcdoc =
                    `<html><body style="margin:0;padding:16px;background:#ffffff;">` +
                    `<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#6b7280;margin-bottom:12px;">` +
                    `Subject: ${escapeHtml(data.subject)}</div>${data.body_html}</body></html>`;
            }
            if (warning) {
                if (data.unknown && data.unknown.length) {
                    warning.classList.remove('hidden');
                    warning.innerHTML =
                        `Unknown placeholder(s): ${data.unknown.map(k => escapeHtml(k)).join(', ')} — these render empty.`;
                } else {
                    warning.classList.add('hidden');
                    warning.innerHTML = '';
                }
            }
        },
    };

    if (toggleBtn) toggleBtn.onclick = () => editor.toggleSource();
    if (previewBtn) previewBtn.onclick = () => editor.preview();
    renderPlaceholderMenu(
        document.getElementById(`${prefix}PlaceholderMenu`),
        key => editor.insertPlaceholder(key),
    );
    if (subjectInput) {
        renderPlaceholderMenu(
            document.getElementById(`${prefix}SubjectPlaceholderMenu`),
            key => insertAtCaret(subjectInput, `{{ ${key} }}`),
        );
    }

    EMAIL_EDITORS[prefix] = editor;
    return editor;
}

function getEmailEditor(prefix) {
    return EMAIL_EDITORS[prefix];
}
