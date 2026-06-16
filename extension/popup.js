const els = {
  statusPill: document.getElementById('statusPill'),
  riskScore: document.getElementById('riskScore'),
  riskText: document.getElementById('riskText'),
  startBtn: document.getElementById('startBtn'),
  stopBtn: document.getElementById('stopBtn'),
  pasteCount: document.getElementById('pasteCount'),
  keyCount: document.getElementById('keyCount'),
  anomalyCount: document.getElementById('anomalyCount'),
  latestFlag: document.getElementById('latestFlag'),
  dashboardBtn: document.getElementById('dashboardBtn'),
  optionsBtn: document.getElementById('optionsBtn')
};

function send(type, payload = {}) {
  return chrome.runtime.sendMessage({ type, ...payload });
}

function riskLabel(score) {
  if (score >= 70) return 'High risk pattern detected. Review the dashboard timeline.';
  if (score >= 35) return 'Moderate risk. Some behavior deserves review.';
  if (score > 0) return 'Low risk. Minor activity recorded.';
  return 'No risk signals yet.';
}

function render(state) {
  const active = Boolean(state?.active);
  const session = state?.session;
  els.statusPill.textContent = active ? 'Active' : 'Idle';
  els.statusPill.classList.toggle('active', active);
  els.startBtn.disabled = active;
  els.stopBtn.disabled = !active;

  const score = session?.riskScore || 0;
  document.documentElement.style.setProperty('--score', score);
  els.riskScore.textContent = score;
  els.riskText.textContent = active ? riskLabel(score) : 'No active session.';
  els.pasteCount.textContent = session?.stats?.pasteCount || 0;
  els.keyCount.textContent = session?.stats?.keyCount || 0;
  els.anomalyCount.textContent = session?.anomalies?.length || 0;

  const latest = session?.anomalies?.[session.anomalies.length - 1];
  els.latestFlag.textContent = latest ? `${latest.severity.toUpperCase()}: ${latest.rationale}` : 'No anomaly recorded.';
}

async function refresh() {
  const response = await send('PGW_GET_STATE');
  render(response.state);
}

els.startBtn.addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const response = await send('PGW_START_SESSION', { meta: { title: tab?.title || 'Controlled writing session' } });
  render(response.state);
});

els.stopBtn.addEventListener('click', async () => {
  const response = await send('PGW_STOP_SESSION');
  render(response.state);
});

els.dashboardBtn.addEventListener('click', () => chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') }));
els.optionsBtn.addEventListener('click', () => chrome.runtime.openOptionsPage());

refresh();
