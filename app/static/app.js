// Simple vanilla JS frontend. Talks to the FastAPI backend on the same
// origin, so no CORS or base URL config is needed.

const $ = (sel) => document.querySelector(sel);
let currentFilter = "all";

// --- Submit form ----------------------------------------------------------

$("#task-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const msg = $("#form-msg");

  // Build the request body from the form fields.
  const body = {
    task_type: form.task_type.value.trim(),
    duration: Number(form.duration.value),
    priority: form.priority.value,
    schedule_policy: form.schedule_policy.value,
    should_fail: form.should_fail.checked,
  };

  // datetime-local gives a local time with no timezone. Convert to an
  // ISO string (UTC) so the backend schedules it correctly.
  if (form.scheduled_at.value) {
    body.scheduled_at = new Date(form.scheduled_at.value).toISOString();
  }

  try {
    const res = await fetch("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");
    msg.textContent = `Added ${data.task_id} (${data.status})`;
    msg.className = "form-msg ok";
    form.task_type.value = "";
    form.scheduled_at.value = "";
    form.should_fail.checked = false;
    refresh();
  } catch (err) {
    msg.textContent = err.message;
    msg.className = "form-msg err";
  }
});

// --- Filters ---------------------------------------------------------------

$("#filters").addEventListener("click", (e) => {
  if (e.target.tagName !== "BUTTON") return;
  currentFilter = e.target.dataset.filter;
  document.querySelectorAll("#filters button").forEach((b) =>
    b.classList.toggle("active", b === e.target)
  );
  renderTasks(lastTasks);
});

// --- Cancel (event delegation) --------------------------------------------

$("#task-rows").addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn-cancel");
  if (!btn) return;
  await fetch(`/tasks/${btn.dataset.id}`, { method: "DELETE" });
  refresh();
});

// --- Rendering -------------------------------------------------------------

let lastTasks = [];

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderStats(s) {
  const items = [
    ["workers", s.worker_count],
    ["queued", s.queued],
    ["scheduled", s.scheduled],
    ["pending", s.pending],
    ["running", s.running],
    ["completed", s.completed],
    ["failed", s.failed],
    ["cancelled", s.cancelled],
    ["total", s.total],
    ["avg exec", s.avg_execution_time != null ? `${s.avg_execution_time.toFixed(1)}s` : "—"],
  ];
  $("#stats").innerHTML = items
    .map(([lbl, num]) => `<div class="stat"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`)
    .join("");
}

function renderTasks(tasks) {
  const rows = tasks.filter((t) => currentFilter === "all" || t.status === currentFilter);
  $("#empty").style.display = rows.length ? "none" : "block";

  $("#task-rows").innerHTML = rows
    .map((t) => {
      const exec = t.execution_time != null ? `${t.execution_time.toFixed(1)}s` : "—";
      const cancelBtn =
        t.status === "pending"
          ? `<button class="btn-cancel" data-id="${t.task_id}">Cancel</button>`
          : "";
      return `
        <tr>
          <td>
            <div>${escapeHtml(t.task_type)}</div>
            <div class="mono" style="color:var(--muted)">${t.task_id}</div>
          </td>
          <td><span class="prio p-${t.priority}">${t.priority}</span></td>
          <td><span class="badge s-${t.status}" title="${t.error ? escapeHtml(t.error) : ""}">${t.status}</span></td>
          <td>${t.duration}s</td>
          <td>${exec}${t.retries ? ` <span class="retry-pill">${t.retries} ${t.retries > 1 ? "retries" : "retry"}</span>` : ""}</td>
          <td class="mono">${fmtTime(t.scheduled_at)}</td>
          <td>${cancelBtn}</td>
        </tr>`;
    })
    .join("");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// --- Polling ---------------------------------------------------------------

async function refresh() {
  try {
    const [tasksRes, statusRes, healthRes] = await Promise.all([
      fetch("/tasks"),
      fetch("/queue/status"),
      fetch("/health"),
    ]);
    lastTasks = await tasksRes.json();
    renderStats(await statusRes.json());
    renderTasks(lastTasks);

    const ok = healthRes.ok;
    $("#health-dot").className = `dot ${ok ? "ok" : "down"}`;
    $("#health-text").textContent = ok ? "healthy" : "down";
  } catch {
    $("#health-dot").className = "dot down";
    $("#health-text").textContent = "unreachable";
  }
}

refresh();
setInterval(refresh, 1500); // live updates every 1.5s
