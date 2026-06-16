const DEFAULT_SETTINGS = {
  privacyMode: 'metadata',
  captureSnippets: false,
  snippetMaxChars: 80,
  idleThresholdMs: 6000,
  burstMinChars: 120,
  largeInsertionChars: 180,
  pasteStreakWindowMs: 20000,
  pasteStreakCount: 3,
  uniformCadenceWindow: 18,
  uniformCadenceStddevMs: 22,
  riskWeights: {
    paste: 4,
    largeInsertion: 18,
    idleToBurst: 26,
    pasteStreak: 22,
    uniformCadence: 15,
    drop: 12
  }
};

const DEFAULT_STATE = {
  active: false,
  session: null
};

function nowIso() {
  return new Date().toISOString();
}

function uid(prefix = 'id') {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

async function getSettings() {
  const stored = await chrome.storage.local.get(['settings']);
  return { ...DEFAULT_SETTINGS, ...(stored.settings || {}) };
}

async function saveSettings(settings) {
  await chrome.storage.local.set({ settings: { ...DEFAULT_SETTINGS, ...settings } });
}

async function getState() {
  const stored = await chrome.storage.local.get(['state']);
  return { ...DEFAULT_STATE, ...(stored.state || {}) };
}

async function saveState(state) {
  await chrome.storage.local.set({ state });
}

function blankSession(meta = {}) {
  return {
    id: uid('session'),
    startedAt: nowIso(),
    stoppedAt: null,
    status: 'active',
    title: meta.title || 'Controlled writing session',
    events: [],
    anomalies: [],
    riskScore: 0,
    stats: {
      pasteCount: 0,
      copyCount: 0,
      cutCount: 0,
      dropCount: 0,
      keyCount: 0,
      inputCount: 0,
      largeInsertionCount: 0,
      activeDomains: [],
      totalInsertedChars: 0
    },
    analysis: {
      lastKeyAt: null,
      lastInputAt: null,
      recentPasteTimes: [],
      keyIntervals: [],
      lastKeyTime: null
    },
    settingsSnapshot: null
  };
}

function sanitizeEvent(event, settings) {
  const safe = {
    id: uid('event'),
    t: nowIso(),
    tPerf: event.tPerf || 0,
    type: event.type,
    inputType: event.inputType || null,
    fieldType: event.fieldType || 'unknown',
    url: event.url || '',
    origin: event.origin || '',
    title: event.title || '',
    insertedLength: Number(event.insertedLength || 0),
    clipboardLength: Number(event.clipboardLength || 0),
    selectionLength: Number(event.selectionLength || 0),
    keyCategory: event.keyCategory || null,
    isTrusted: Boolean(event.isTrusted),
    metadataOnly: true
  };

  if (settings.captureSnippets && event.snippet) {
    safe.snippet = String(event.snippet).slice(0, settings.snippetMaxChars);
    safe.metadataOnly = false;
  }

  return safe;
}

function updateStats(session, event) {
  if (event.origin && !session.stats.activeDomains.includes(event.origin)) {
    session.stats.activeDomains.push(event.origin);
  }

  if (event.type === 'paste') session.stats.pasteCount += 1;
  if (event.type === 'copy') session.stats.copyCount += 1;
  if (event.type === 'cut') session.stats.cutCount += 1;
  if (event.type === 'drop') session.stats.dropCount += 1;
  if (event.type === 'keydown') session.stats.keyCount += 1;
  if (event.type === 'input' || event.type === 'beforeinput') session.stats.inputCount += 1;
  if (event.insertedLength) session.stats.totalInsertedChars += event.insertedLength;
}

function anomaly(session, ruleId, severity, rationale, features = {}) {
  const existsKey = `${ruleId}:${Math.floor(Date.now() / 1000)}`;
  const duplicate = session.anomalies.some((a) => a.dedupeKey === existsKey);
  if (duplicate) return;

  session.anomalies.push({
    id: uid('anomaly'),
    dedupeKey: existsKey,
    t: nowIso(),
    ruleId,
    severity,
    rationale,
    features
  });
}

function stddev(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + Math.pow(value - mean, 2), 0) / values.length;
  return Math.sqrt(variance);
}

function evaluateEvent(session, event, settings) {
  const tPerf = Number(event.tPerf || performance.now());

  if (event.type === 'keydown') {
    if (session.analysis.lastKeyTime) {
      const interval = Math.max(0, tPerf - session.analysis.lastKeyTime);
      if (interval < 2000) {
        session.analysis.keyIntervals.push(interval);
        if (session.analysis.keyIntervals.length > settings.uniformCadenceWindow) {
          session.analysis.keyIntervals.shift();
        }
      }
    }
    session.analysis.lastKeyTime = tPerf;
    session.analysis.lastKeyAt = event.t;

    if (session.analysis.keyIntervals.length >= settings.uniformCadenceWindow) {
      const sd = stddev(session.analysis.keyIntervals);
      const avg = session.analysis.keyIntervals.reduce((a, b) => a + b, 0) / session.analysis.keyIntervals.length;
      if (avg > 30 && avg < 300 && sd <= settings.uniformCadenceStddevMs) {
        anomaly(
          session,
          'timing_uniformity',
          'medium',
          `Keystroke cadence is unusually uniform (${Math.round(sd)}ms stddev across ${session.analysis.keyIntervals.length} intervals).`,
          { stddevMs: Math.round(sd), averageMs: Math.round(avg), sampleSize: session.analysis.keyIntervals.length }
        );
      }
    }
  }

  const insertedLength = Number(event.insertedLength || event.clipboardLength || 0);

  if (['paste', 'drop', 'beforeinput', 'input'].includes(event.type)) {
    session.analysis.lastInputAt = event.t;
  }

  if (event.type === 'paste') {
    session.analysis.recentPasteTimes.push(tPerf);
    const cutoff = tPerf - settings.pasteStreakWindowMs;
    session.analysis.recentPasteTimes = session.analysis.recentPasteTimes.filter((x) => x >= cutoff);

    if (session.analysis.recentPasteTimes.length >= settings.pasteStreakCount) {
      anomaly(
        session,
        'multi_paste_streak',
        'medium',
        `${session.analysis.recentPasteTimes.length} paste events occurred within ${Math.round(settings.pasteStreakWindowMs / 1000)} seconds.`,
        { pasteCount: session.analysis.recentPasteTimes.length, windowMs: settings.pasteStreakWindowMs }
      );
    }
  }

  if ((event.type === 'paste' || event.type === 'drop') && insertedLength >= settings.largeInsertionChars) {
    session.stats.largeInsertionCount += 1;
    anomaly(
      session,
      event.type === 'drop' ? 'drop_large_text' : 'large_paste',
      'high',
      `${insertedLength} characters were inserted through ${event.type}.`,
      { insertedLength, eventType: event.type }
    );
  }

  if ((event.type === 'paste' || event.inputType === 'insertFromPaste') && insertedLength >= settings.burstMinChars) {
    const lastKeyTime = session.analysis.lastKeyTime || 0;
    const idleMs = lastKeyTime ? tPerf - lastKeyTime : settings.idleThresholdMs + 1;
    if (idleMs >= settings.idleThresholdMs) {
      anomaly(
        session,
        'idle_to_burst',
        'high',
        `Idle for ${Math.round(idleMs / 1000)}s before a ${insertedLength}-character insertion.`,
        { idleMs: Math.round(idleMs), insertedLength }
      );
    }
  }

  if ((event.type === 'beforeinput' || event.type === 'input') && insertedLength >= settings.largeInsertionChars && event.inputType !== 'insertFromPaste') {
    const recentKey = session.analysis.lastKeyTime && tPerf - session.analysis.lastKeyTime < 1500;
    if (!recentKey) {
      session.stats.largeInsertionCount += 1;
      anomaly(
        session,
        'text_injection_without_typing',
        'high',
        `${insertedLength} characters appeared without nearby typing activity.`,
        { insertedLength, inputType: event.inputType || 'unknown' }
      );
    }
  }
}

function scoreRisk(session, settings) {
  let score = 0;
  for (const anomalyItem of session.anomalies) {
    if (anomalyItem.ruleId.includes('idle_to_burst')) score += settings.riskWeights.idleToBurst;
    else if (anomalyItem.ruleId.includes('multi_paste')) score += settings.riskWeights.pasteStreak;
    else if (anomalyItem.ruleId.includes('uniform')) score += settings.riskWeights.uniformCadence;
    else if (anomalyItem.ruleId.includes('drop')) score += settings.riskWeights.drop;
    else if (anomalyItem.ruleId.includes('large')) score += settings.riskWeights.largeInsertion;
    else score += 8;
  }

  score += Math.min(20, session.stats.pasteCount * settings.riskWeights.paste);
  return Math.min(100, Math.round(score));
}

async function startSession(meta = {}) {
  const settings = await getSettings();
  const session = blankSession(meta);
  session.settingsSnapshot = settings;
  const state = { active: true, session };
  await saveState(state);
  return state;
}

async function stopSession() {
  const state = await getState();
  if (!state.session) return state;
  state.active = false;
  state.session.status = 'stopped';
  state.session.stoppedAt = nowIso();
  await archiveSession(state.session);
  await saveState(state);
  return state;
}

async function archiveSession(session) {
  const stored = await chrome.storage.local.get(['sessions']);
  const sessions = stored.sessions || [];
  const withoutCurrent = sessions.filter((s) => s.id !== session.id);
  withoutCurrent.unshift(session);
  await chrome.storage.local.set({ sessions: withoutCurrent.slice(0, 30) });
}

async function clearCurrentSession() {
  await saveState(DEFAULT_STATE);
  return DEFAULT_STATE;
}

async function recordEvent(rawEvent) {
  const settings = await getSettings();
  const state = await getState();
  if (!state.active || !state.session) return state;

  const event = sanitizeEvent(rawEvent, settings);
  state.session.events.push(event);
  if (state.session.events.length > 3000) state.session.events.shift();

  updateStats(state.session, event);
  evaluateEvent(state.session, event, settings);
  state.session.riskScore = scoreRisk(state.session, settings);

  await saveState(state);
  return state;
}

chrome.runtime.onInstalled.addListener(async () => {
  const stored = await chrome.storage.local.get(['settings', 'state']);
  if (!stored.settings) await saveSettings(DEFAULT_SETTINGS);
  if (!stored.state) await saveState(DEFAULT_STATE);
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message?.type === 'PGW_START_SESSION') sendResponse({ ok: true, state: await startSession(message.meta || {}) });
    else if (message?.type === 'PGW_STOP_SESSION') sendResponse({ ok: true, state: await stopSession() });
    else if (message?.type === 'PGW_CLEAR_SESSION') sendResponse({ ok: true, state: await clearCurrentSession() });
    else if (message?.type === 'PGW_GET_STATE') sendResponse({ ok: true, state: await getState(), settings: await getSettings() });
    else if (message?.type === 'PGW_SAVE_SETTINGS') {
      await saveSettings(message.settings || {});
      sendResponse({ ok: true, settings: await getSettings() });
    } else if (message?.type === 'PGW_EVENT') {
      sendResponse({ ok: true, state: await recordEvent(message.event || {}) });
    } else if (message?.type === 'PGW_GET_ARCHIVE') {
      const stored = await chrome.storage.local.get(['sessions']);
      sendResponse({ ok: true, sessions: stored.sessions || [] });
    } else {
      sendResponse({ ok: false, error: 'Unknown message type' });
    }
  })();
  return true;
});
