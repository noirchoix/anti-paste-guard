const panels = {
  current: document.getElementById('currentPanel'),
  archive: document.getElementById('archivePanel'),
  export: document.getElementById('exportPanel')
};

const els = {
  riskScore: document.getElementById('riskScore'),
  riskSummary: document.getElementById('riskSummary'),
  pasteCount: document.getElementById('pasteCount'),
  keyCount: document.getElementById('keyCount'),
  flagCount: document.getElementById('flagCount'),
  sessionStatus: document.getElementById('sessionStatus'),
  anomalyList: document.getElementById('anomalyList'),
  eventList: document.getElementById('eventList'),
  eventCount: document.getElementById('eventCount'),
  archiveList: document.getElementById('archiveList'),
  exportPreview: document.getElementById('exportPreview')
};

let currentState = null;
let archivedSessions = [];

function send(type, payload = {}) {
  return chrome.runtime.sendMessage({ type, ...payload });
}

function riskSummary(score) {
  if (score >= 70) return 'High-risk pattern. Review event sequence before making a decision.';
  if (score >= 35) return 'Moderate risk. Signals exist but require human review.';
  if (score > 0) return 'Low risk. Minor signals recorded.';
  return 'No meaningful integrity signals recorded.';
}

function eventLabel(event) {
  const len = event.insertedLength || event.clipboardLength || 0;
  return `${event.type}${event.inputType ? ` · ${event.inputType}` : ''}${len ? ` · ${len} chars` : ''}`;
}

function renderItem(title, meta, body, severity) {
  const item = document.createElement('div');
  item.className = `item ${severity || ''}`.trim();
  item.innerHTML = `<div class="meta"><span>${meta.left}</span><span>${meta.right}</span></div><strong>${title}</strong><p>${body}</p>`;
  return item;
}

function renderSession(session, active) {
  const score = session?.riskScore || 0;
  els.riskScore.textContent = score;
  els.riskSummary.textContent = session ? riskSummary(score) : 'No session loaded.';
  els.pasteCount.textContent = session?.stats?.pasteCount || 0;
  els.keyCount.textContent = session?.stats?.keyCount || 0;
  els.flagCount.textContent = session?.anomalies?.length || 0;
  els.sessionStatus.textContent = active ? 'Active' : 'Idle';
  els.sessionStatus.classList.toggle('active', active);
  els.eventCount.textContent = `${session?.events?.length || 0} events`;

  els.anomalyList.innerHTML = '';
  const anomalies = [...(session?.anomalies || [])].reverse();
  if (!anomalies.length) {
    els.anomalyList.className = 'timeline empty';
    els.anomalyList.textContent = 'No anomalies yet.';
  } else {
    els.anomalyList.className = 'timeline';
    for (const a of anomalies) {
      els.anomalyList.appendChild(renderItem(
        a.ruleId.replaceAll('_', ' '),
        { left: a.severity.toUpperCase(), right: new Date(a.t).toLocaleTimeString() },
        a.rationale,
        a.severity
      ));
    }
  }

  els.eventList.innerHTML = '';
  const events = [...(session?.events || [])].reverse().slice(0, 140);
  if (!events.length) {
    els.eventList.className = 'event-list empty';
    els.eventList.textContent = 'No event metadata yet.';
  } else {
    els.eventList.className = 'event-list';
    for (const e of events) {
      els.eventList.appendChild(renderItem(
        eventLabel(e),
        { left: e.fieldType || 'unknown', right: new Date(e.t).toLocaleTimeString() },
        `${e.origin || 'local page'} · ${e.title || 'Untitled page'}`,
        ''
      ));
    }
  }

  els.exportPreview.textContent = session ? JSON.stringify(session, null, 2) : 'No session loaded.';
}

function renderArchive() {
  els.archiveList.innerHTML = '';
  if (!archivedSessions.length) {
    els.archiveList.className = 'archive-list empty';
    els.archiveList.textContent = 'No archived sessions.';
    return;
  }
  els.archiveList.className = 'archive-list';
  for (const session of archivedSessions) {
    const item = renderItem(
      session.title || 'Controlled writing session',
      { left: `${session.riskScore || 0} risk`, right: new Date(session.startedAt).toLocaleString() },
      `${session.events?.length || 0} events · ${session.anomalies?.length || 0} flags · ${session.stats?.activeDomains?.join(', ') || 'no domain'}`,
      session.riskScore >= 70 ? 'high' : session.riskScore >= 35 ? 'medium' : ''
    );
    item.addEventListener('click', () => renderSession(session, false));
    els.archiveList.appendChild(item);
  }
}

async function refresh() {
  const stateResp = await send('PGW_GET_STATE');
  const archiveResp = await send('PGW_GET_ARCHIVE');
  currentState = stateResp.state;
  archivedSessions = archiveResp.sessions || [];
  renderSession(currentState?.session, Boolean(currentState?.active));
  renderArchive();
}

function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(session) {
  const header = ['t', 'type', 'inputType', 'fieldType', 'origin', 'insertedLength', 'clipboardLength', 'selectionLength'];
  const rows = (session?.events || []).map((e) => header.map((key) => JSON.stringify(e[key] ?? '')).join(','));
  return [header.join(','), ...rows].join('\n');
}

document.querySelectorAll('.nav').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.nav').forEach((x) => x.classList.remove('active'));
    button.classList.add('active');
    Object.values(panels).forEach((panel) => panel.classList.add('hidden'));
    panels[button.dataset.panel].classList.remove('hidden');
  });
});

document.getElementById('refreshBtn').addEventListener('click', refresh);
document.getElementById('clearBtn').addEventListener('click', async () => { await send('PGW_CLEAR_SESSION'); await refresh(); });
document.getElementById('exportJsonBtn').addEventListener('click', () => {
  const session = currentState?.session;
  if (!session) return;
  download(`pasteguard-session-${session.id}.json`, JSON.stringify(session, null, 2), 'application/json');
});
document.getElementById('exportCsvBtn').addEventListener('click', () => {
  const session = currentState?.session;
  if (!session) return;
  download(`pasteguard-events-${session.id}.csv`, toCsv(session), 'text/csv');
});

refresh();
setInterval(refresh, 3000);
