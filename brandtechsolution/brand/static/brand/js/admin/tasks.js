// Tasks section.
//
// The two rules from staff.js hold here too:
//   1. Every value from the API goes through escapeHtml() before it is
//      interpolated into markup.
//   2. No JavaScript is built inside an on* attribute. Rows carry data-*
//      attributes and delegated listeners read them.
//
// Every top-level name is prefixed. staff.js is a peer module sharing this
// global scope, and a second `const ROLES` anywhere would be a redeclaration
// SyntaxError that silently kills whichever file parsed second - taking an
// unrelated section down with it. For the same reason this file defines its
// own fetch helper rather than borrowing staff.js's apiFetch: escapeHtml and
// CSRF_TOKEN come from core.js, which is the shared base, but section modules
// do not depend on each other.
const TASK_API = '/api/work';

let TASK_TAB = 'mine';
let TASK_ROWS = [];
let TASK_NEXT = null;
let TASK_SEARCH = '';
let TASK_PEOPLE = [];
let TASK_CAN_MANAGE = false;
let TASK_LOADED = false;

async function taskApi(path, options = {}) {
    const url = path.startsWith('http') ? path : `${TASK_API}${path}`;
    const response = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
        ...options,
    });
    if (!response.ok) {
        let detail = 'Request failed';
        try {
            const body = await response.json();
            detail = typeof body === 'string'
                ? body
                : (body.detail || Object.values(body).flat().join(' ') || JSON.stringify(body));
        } catch (e) { /* response had no JSON body */ }
        throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
}

// DRF returns `next` as an absolute URL. Only follow it if it points back at
// this origin, so a spoofed or misconfigured link cannot make the panel send
// its session cookie to another host.
function taskSameOrigin(next) {
    if (!next) return null;
    try {
        const url = new URL(next, window.location.href);
        return url.origin === window.location.origin ? url.toString() : null;
    } catch (e) { return null; }
}

/* ---------- rendering helpers ---------- */

const TASK_PRIORITY_STYLE = {
    4: 'bg-red-500/10 text-red-400',
    3: 'bg-orange-500/10 text-orange-400',
    2: 'bg-blue-500/10 text-blue-400',
    1: 'bg-gray-500/10 text-gray-400',
};

const TASK_STATUS_STYLE = {
    open: 'bg-blue-500/10 text-blue-400',
    in_review: 'bg-yellow-500/10 text-yellow-400',
    done: 'bg-green-500/10 text-green-400',
};

function taskPill(text, classes) {
    return `<span class="text-xs px-2 py-1 rounded ${classes}">${escapeHtml(text)}</span>`;
}

function taskDueLabel(task) {
    if (!task.due_date) return '';
    const style = task.is_overdue ? 'text-red-400' : 'text-gray-500';
    const prefix = task.is_overdue ? 'Overdue &middot; due ' : 'Due ';
    return `<span class="text-xs ${style}">${prefix}${escapeHtml(task.due_date)}</span>`;
}

// "2 of 3 done" is the one number that says how a shared task is actually
// going. A bare status pill cannot: a task with four assignees and three
// finished looks identical to one where nobody has started.
function taskProgressLabel(task) {
    const total = task.assignees.length;
    if (!total) return '<span class="text-xs text-gray-600">Unassigned</span>';
    const done = task.assignees.filter(a => a.done).length;
    const style = done === total ? 'text-green-400' : 'text-gray-500';
    return `<span class="text-xs ${style}">${done} of ${total} done</span>`;
}

function taskAssigneeChips(task) {
    if (!task.assignees.length) return '';
    return task.assignees.map(a => `
        <span class="text-xs px-2 py-0.5 rounded-full border ${a.done
            ? 'border-green-500/30 text-green-400'
            : 'border-dark-border text-gray-400'}">
            ${a.done ? '<i class="fas fa-check mr-1"></i>' : ''}${escapeHtml(a.username)}
        </span>`).join(' ');
}

function taskCard(task) {
    return `
    <div class="bg-dark-card border border-dark-border rounded-lg p-4 hover:border-brand-blue/40 transition-colors cursor-pointer"
        data-action="open-task" data-id="${escapeHtml(task.id)}">
        <div class="flex justify-between items-start gap-4 mb-2">
            <div class="min-w-0">
                <div class="text-white font-medium truncate">${escapeHtml(task.title)}</div>
                <div class="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1">
                    ${taskProgressLabel(task)}
                    ${taskDueLabel(task)}
                    ${task.comment_count
                        ? `<span class="text-xs text-gray-600"><i class="fas fa-comment mr-1"></i>${escapeHtml(task.comment_count)}</span>`
                        : ''}
                </div>
            </div>
            <div class="flex items-center gap-2 shrink-0">
                ${taskPill(task.priority_display, TASK_PRIORITY_STYLE[task.priority] || '')}
                ${taskPill(task.status_display, TASK_STATUS_STYLE[task.status] || '')}
            </div>
        </div>
        <div class="flex flex-wrap gap-1">${taskAssigneeChips(task)}</div>
    </div>`;
}

/* ---------- list ---------- */

function taskQueryString() {
    const params = new URLSearchParams();
    if (TASK_TAB === 'mine') { params.set('mine', '1'); params.set('active', '1'); }
    if (TASK_TAB === 'all') params.set('active', '1');
    if (TASK_TAB === 'review') params.set('status', 'in_review');
    if (TASK_TAB === 'done') params.set('status', 'done');
    if (TASK_SEARCH) params.set('q', TASK_SEARCH);
    return `/tasks/?${params.toString()}`;
}

function renderTaskList() {
    const container = document.getElementById('taskList');
    if (!TASK_ROWS.length) {
        const empty = {
            mine: 'Nothing assigned to you right now.',
            all: 'No open tasks.',
            review: 'Nothing waiting for review.',
            done: 'No completed tasks yet.',
        }[TASK_TAB];
        container.innerHTML = `<p class="text-gray-500 text-sm">${escapeHtml(empty)}</p>`;
    } else {
        container.innerHTML = TASK_ROWS.map(taskCard).join('');
    }
    document.getElementById('taskListMore').classList.toggle('hidden', !TASK_NEXT);
}

async function loadTaskPage(url, append) {
    const data = await taskApi(url);
    TASK_ROWS = append ? TASK_ROWS.concat(data.results || []) : (data.results || []);
    TASK_NEXT = taskSameOrigin(data.next);
    renderTaskList();
}

async function refreshTaskSummary() {
    try {
        const summary = await taskApi('/summary/');
        TASK_CAN_MANAGE = summary.can_manage;

        document.getElementById('newTaskBtn').classList.toggle('hidden', !TASK_CAN_MANAGE);
        document.getElementById('newTaskBtn').classList.toggle('flex', TASK_CAN_MANAGE);
        document.getElementById('taskReviewTab').classList.toggle('hidden', !TASK_CAN_MANAGE);

        const reviewCount = document.getElementById('taskReviewCount');
        reviewCount.textContent = summary.needs_review;
        reviewCount.classList.toggle('hidden', !summary.needs_review);

        // The sidebar badge shows whichever number the viewer can act on:
        // work waiting on them, or - for a reviewer - work waiting on their
        // approval. Reviewers see the review queue, since that is the thing
        // that stalls other people if it is ignored.
        const badge = document.getElementById('taskNavBadge');
        if (badge) {
            const count = TASK_CAN_MANAGE && summary.needs_review
                ? summary.needs_review
                : summary.my_open;
            badge.textContent = count;
            badge.classList.toggle('hidden', !count);
        }
    } catch (e) { console.error('task summary:', e); }
}

async function loadTasks() {
    try {
        await refreshTaskSummary();
        if (!TASK_LOADED) {
            TASK_PEOPLE = await taskApi('/assignable/');
            TASK_LOADED = true;
        }
        await loadTaskPage(taskQueryString(), false);
    } catch (e) {
        document.getElementById('taskList').innerHTML =
            `<p class="text-red-400 text-sm">${escapeHtml(e.message)}</p>`;
    }
}

/* ---------- detail modal ---------- */

function openTaskModal(title, body) {
    document.getElementById('taskModalTitle').textContent = title;
    document.getElementById('taskModalBody').innerHTML = body;
    const modal = document.getElementById('taskModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeTaskModal() {
    const modal = document.getElementById('taskModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.getElementById('taskModalBody').innerHTML = '';
}

const TASK_ACTIVITY_ICON = {
    comment: 'fa-comment text-gray-500',
    created: 'fa-plus text-blue-400',
    edited: 'fa-pen text-gray-500',
    assignees_changed: 'fa-users text-blue-400',
    marked_done: 'fa-check text-green-400',
    marked_undone: 'fa-rotate-left text-yellow-400',
    submitted: 'fa-paper-plane text-yellow-400',
    approved: 'fa-circle-check text-green-400',
    reopened: 'fa-arrow-rotate-left text-red-400',
};

function taskActivityRow(entry) {
    const when = new Date(entry.created_at).toLocaleString();
    return `
    <div class="flex gap-3 text-sm">
        <i class="fas ${TASK_ACTIVITY_ICON[entry.kind] || 'fa-circle text-gray-600'} mt-1 w-4 text-center"></i>
        <div class="min-w-0">
            <div class="text-gray-300 break-words">${escapeHtml(entry.body || entry.kind_display)}</div>
            <div class="text-xs text-gray-600">${escapeHtml(entry.actor_name)} &middot; ${escapeHtml(when)}</div>
        </div>
    </div>`;
}

function taskDetailBody(task, activity) {
    const mine = task.my_assignment;
    const inReview = task.status === 'in_review';
    const isDone = task.status === 'done';

    const assigneeRows = task.assignees.length
        ? task.assignees.map(a => `
            <div class="flex justify-between items-center py-1.5">
                <span class="text-sm ${a.done ? 'text-green-400' : 'text-gray-300'}">
                    ${a.done ? '<i class="fas fa-check mr-2"></i>' : '<i class="far fa-circle mr-2"></i>'}${escapeHtml(a.username)}
                </span>
                ${TASK_CAN_MANAGE && !isDone ? `
                    <button type="button" class="text-xs text-brand-blue hover:text-blue-400"
                        data-action="${a.done ? 'admin-undone' : 'admin-done'}"
                        data-id="${escapeHtml(task.id)}" data-user="${escapeHtml(a.id)}">
                        ${a.done ? 'Reopen their part' : 'Mark done'}
                    </button>` : ''}
            </div>`).join('')
        : '<p class="text-sm text-gray-600">Nobody is assigned.</p>';

    return `
    <div class="space-y-6">
        <div class="flex flex-wrap gap-2">
            ${taskPill(task.status_display, TASK_STATUS_STYLE[task.status] || '')}
            ${taskPill(task.priority_display, TASK_PRIORITY_STYLE[task.priority] || '')}
            ${taskDueLabel(task)}
        </div>

        ${task.description
            ? `<p class="text-sm text-gray-300 whitespace-pre-wrap break-words">${escapeHtml(task.description)}</p>`
            : '<p class="text-sm text-gray-600">No description.</p>'}

        <div>
            <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Assigned to</h4>
            <div class="divide-y divide-dark-border">${assigneeRows}</div>
        </div>

        <div class="flex flex-wrap gap-2">
            ${mine && !isDone ? `
                <button type="button" data-action="${mine.done ? 'uncomplete' : 'complete'}"
                    data-id="${escapeHtml(task.id)}"
                    class="${mine.done
                        ? 'border border-dark-border text-gray-300 hover:text-white'
                        : 'bg-brand-green hover:bg-green-500 text-black font-semibold'} px-4 py-2 rounded-lg text-sm transition-colors">
                    ${mine.done ? 'I\'m not done after all' : 'Mark my part done'}
                </button>` : ''}
            ${TASK_CAN_MANAGE && inReview ? `
                <button type="button" data-action="approve" data-id="${escapeHtml(task.id)}"
                    class="bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded-lg text-sm transition-colors">
                    <i class="fas fa-check mr-2"></i>Approve
                </button>` : ''}
            ${TASK_CAN_MANAGE && (inReview || isDone) ? `
                <button type="button" data-action="reopen" data-id="${escapeHtml(task.id)}"
                    class="border border-red-500/40 text-red-400 hover:bg-red-500/10 px-4 py-2 rounded-lg text-sm transition-colors">
                    Send back
                </button>` : ''}
            ${TASK_CAN_MANAGE ? `
                <button type="button" data-action="edit-task" data-id="${escapeHtml(task.id)}"
                    class="border border-dark-border text-gray-300 hover:text-white px-4 py-2 rounded-lg text-sm transition-colors">
                    Edit
                </button>
                <button type="button" data-action="delete-task" data-id="${escapeHtml(task.id)}"
                    class="text-red-400 hover:text-red-300 px-4 py-2 rounded-lg text-sm transition-colors">
                    Delete
                </button>` : ''}
        </div>

        <div>
            <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Activity</h4>
            <div class="space-y-3">${activity.map(taskActivityRow).join('')}</div>
        </div>

        <div>
            <textarea id="taskCommentBody" rows="2" placeholder="Add a comment&hellip;"
                class="w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-blue"></textarea>
            <button type="button" data-action="comment" data-id="${escapeHtml(task.id)}"
                class="mt-2 px-4 py-2 text-sm rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5 transition-colors">
                Comment
            </button>
        </div>
    </div>`;
}

async function openTaskDetail(id) {
    try {
        const [task, activity] = await Promise.all([
            taskApi(`/tasks/${id}/`),
            taskApi(`/tasks/${id}/activity/`),
        ]);
        openTaskModal(task.title, taskDetailBody(task, activity));
    } catch (e) { alert(e.message); }
}

/* ---------- create / edit form ---------- */

function taskFormBody(task) {
    const selected = new Set((task ? task.assignees : []).map(a => a.id));
    const people = TASK_PEOPLE.length
        ? TASK_PEOPLE.map(p => `
            <label class="flex items-center gap-2 py-1 text-sm text-gray-300">
                <input type="checkbox" class="task-assignee" value="${escapeHtml(p.id)}"
                    ${selected.has(p.id) ? 'checked' : ''}>
                ${escapeHtml(p.username)}
            </label>`).join('')
        : '<p class="text-sm text-gray-600">No staff accounts to assign yet.</p>';

    const field = 'w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-blue';

    return `
    <div class="space-y-4">
        <div>
            <label class="block text-xs text-gray-500 mb-1">Title</label>
            <input type="text" id="taskFormTitle" class="${field}"
                value="${escapeHtml(task ? task.title : '')}">
        </div>
        <div>
            <label class="block text-xs text-gray-500 mb-1">Description</label>
            <textarea id="taskFormDescription" rows="4" class="${field}">${escapeHtml(task ? task.description : '')}</textarea>
        </div>
        <div class="grid grid-cols-2 gap-4">
            <div>
                <label class="block text-xs text-gray-500 mb-1">Priority</label>
                <select id="taskFormPriority" class="${field}">
                    ${[[4, 'Urgent'], [3, 'High'], [2, 'Normal'], [1, 'Low']].map(([v, l]) =>
                        `<option value="${v}" ${(task ? task.priority : 2) === v ? 'selected' : ''}>${l}</option>`
                    ).join('')}
                </select>
            </div>
            <div>
                <label class="block text-xs text-gray-500 mb-1">Due date</label>
                <input type="date" id="taskFormDue" class="${field}"
                    value="${escapeHtml(task && task.due_date ? task.due_date : '')}">
            </div>
        </div>
        <div>
            <label class="block text-xs text-gray-500 mb-2">Assign to</label>
            <div class="max-h-44 overflow-y-auto border border-dark-border rounded-lg p-3">${people}</div>
        </div>
        <div class="flex gap-2 pt-2">
            <button type="button" data-action="save-task" data-id="${escapeHtml(task ? task.id : '')}"
                class="bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-2 rounded-lg text-sm transition-colors">
                ${task ? 'Save changes' : 'Create task'}
            </button>
            <button type="button" data-action="cancel-task"
                class="border border-dark-border text-gray-300 hover:text-white px-5 py-2 rounded-lg text-sm transition-colors">
                Cancel
            </button>
        </div>
    </div>`;
}

async function saveTask(id) {
    const assigneeIds = Array.from(document.querySelectorAll('.task-assignee'))
        .filter(box => box.checked)
        .map(box => Number(box.value));

    const due = document.getElementById('taskFormDue').value;
    const payload = {
        title: document.getElementById('taskFormTitle').value,
        description: document.getElementById('taskFormDescription').value,
        priority: Number(document.getElementById('taskFormPriority').value),
        // An empty date input reads as ''. DRF rejects that for a DateField;
        // null is how "no due date" is spelled.
        due_date: due || null,
        assignee_ids: assigneeIds,
    };

    try {
        await taskApi(id ? `/tasks/${id}/` : '/tasks/', {
            method: id ? 'PATCH' : 'POST',
            body: JSON.stringify(payload),
        });
        closeTaskModal();
        await loadTasks();
    } catch (e) { alert(e.message); }
}

/* ---------- actions ---------- */

async function runTaskAction(action, id, userId) {
    if (action === 'complete' || action === 'admin-done') {
        return taskApi(`/tasks/${id}/complete/`, {
            method: 'POST',
            body: JSON.stringify(userId ? { assignee_id: Number(userId) } : {}),
        });
    }
    if (action === 'uncomplete' || action === 'admin-undone') {
        return taskApi(`/tasks/${id}/uncomplete/`, {
            method: 'POST',
            body: JSON.stringify(userId ? { assignee_id: Number(userId) } : {}),
        });
    }
    if (action === 'approve') {
        return taskApi(`/tasks/${id}/approve/`, { method: 'POST', body: '{}' });
    }
    if (action === 'reopen') {
        const reason = prompt('What still needs doing?');
        if (!reason) return null;
        return taskApi(`/tasks/${id}/reopen/`, {
            method: 'POST',
            body: JSON.stringify({ reason }),
        });
    }
    if (action === 'delete-task') {
        if (!confirm('Delete this task and its history permanently?')) return null;
        return taskApi(`/tasks/${id}/`, { method: 'DELETE' });
    }
    if (action === 'comment') {
        const body = document.getElementById('taskCommentBody').value.trim();
        if (!body) return null;
        return taskApi(`/tasks/${id}/activity/`, {
            method: 'POST',
            body: JSON.stringify({ body }),
        });
    }
    return null;
}

/* ---------- wiring ---------- */

document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('tasks');
    const modal = document.getElementById('taskModal');
    if (!section) return;

    section.addEventListener('click', async (event) => {
        const tab = event.target.closest('.task-tab');
        if (tab) {
            TASK_TAB = tab.dataset.tab;
            document.querySelectorAll('.task-tab').forEach(button => {
                const on = button === tab;
                button.classList.toggle('text-white', on);
                button.classList.toggle('border-brand-blue', on);
                button.classList.toggle('text-gray-400', !on);
                button.classList.toggle('border-transparent', !on);
            });
            await loadTasks();
            return;
        }

        const card = event.target.closest('[data-action="open-task"]');
        if (card) { await openTaskDetail(card.dataset.id); return; }

        if (event.target.closest('#newTaskBtn')) {
            openTaskModal('New task', taskFormBody(null));
        }
    });

    document.getElementById('taskListMore').addEventListener('click', async (event) => {
        if (!TASK_NEXT) return;
        event.target.disabled = true;
        try { await loadTaskPage(TASK_NEXT, true); }
        catch (e) { alert(e.message); }
        finally { event.target.disabled = false; }
    });

    // Debounced so a search does not fire a request per keystroke.
    let searchTimer = null;
    document.getElementById('taskSearch').addEventListener('input', (event) => {
        clearTimeout(searchTimer);
        const value = event.target.value.trim();
        searchTimer = setTimeout(() => {
            TASK_SEARCH = value;
            loadTasks();
        }, 300);
    });

    document.getElementById('taskModalClose').addEventListener('click', closeTaskModal);
    modal.addEventListener('click', (event) => {
        if (event.target === modal) closeTaskModal();
    });

    modal.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const { action, id, user } = button.dataset;

        if (action === 'cancel-task') { closeTaskModal(); return; }
        if (action === 'save-task') { await saveTask(id); return; }
        if (action === 'edit-task') {
            const task = await taskApi(`/tasks/${id}/`);
            openTaskModal('Edit task', taskFormBody(task));
            return;
        }

        button.disabled = true;
        try {
            const result = await runTaskAction(action, id, user);
            if (result === null) return;
            if (action === 'delete-task') closeTaskModal();
            else await openTaskDetail(id);
            await loadTasks();
        } catch (e) {
            alert(e.message);
        } finally {
            button.disabled = false;
        }
    });

    // The badge has to be right before anyone opens the section, otherwise
    // nobody learns there is work waiting for them.
    refreshTaskSummary();
});
