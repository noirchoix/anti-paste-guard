const ids = ['captureSnippets', 'snippetMaxChars', 'idleThresholdMs', 'burstMinChars', 'largeInsertionChars', 'pasteStreakCount', 'pasteStreakWindowMs', 'uniformCadenceStddevMs'];

function send(type, payload = {}) { return chrome.runtime.sendMessage({ type, ...payload }); }

async function load() {
  const response = await send('PGW_GET_STATE');
  const settings = response.settings || {};
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el.type === 'checkbox') el.checked = Boolean(settings[id]);
    else el.value = settings[id] ?? '';
  }
}

async function save() {
  const settings = {};
  for (const id of ids) {
    const el = document.getElementById(id);
    settings[id] = el.type === 'checkbox' ? el.checked : Number(el.value);
  }
  await send('PGW_SAVE_SETTINGS', { settings });
  document.getElementById('status').textContent = 'Settings saved.';
  setTimeout(() => (document.getElementById('status').textContent = ''), 2000);
}

document.getElementById('saveBtn').addEventListener('click', save);
load();
