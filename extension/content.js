(function () {
  const EDITABLE_SELECTOR = 'textarea,input,[contenteditable="true"],[role="textbox"]';
  let lastValue = new WeakMap();

  function isEditable(target) {
    return target && target.closest && target.closest(EDITABLE_SELECTOR);
  }

  function getEditable(target) {
    return target?.closest?.(EDITABLE_SELECTOR) || target;
  }

  function fieldType(el) {
    if (!el) return 'unknown';
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'textarea') return 'textarea';
    if (tag === 'input') return `input:${el.type || 'text'}`;
    if (el.isContentEditable || el.getAttribute?.('contenteditable') === 'true') return 'contenteditable';
    if (el.getAttribute?.('role') === 'textbox') return 'role:textbox';
    return 'unknown';
  }

  function getValueLength(el) {
    if (!el) return 0;
    if (typeof el.value === 'string') return el.value.length;
    if (typeof el.innerText === 'string') return el.innerText.length;
    if (typeof el.textContent === 'string') return el.textContent.length;
    return 0;
  }

  function selectionLength() {
    const selection = window.getSelection?.();
    return selection ? String(selection).length : 0;
  }

  function safeSnippet(text) {
    if (!text) return '';
    return String(text).replace(/\s+/g, ' ').trim().slice(0, 160);
  }

  function baseEvent(type, target) {
    const el = getEditable(target);
    return {
      type,
      tPerf: performance.now(),
      fieldType: fieldType(el),
      url: location.href,
      origin: location.origin,
      title: document.title || '',
      selectionLength: selectionLength(),
      isTrusted: true
    };
  }

  function send(event) {
    try {
      chrome.runtime.sendMessage({ type: 'PGW_EVENT', event });
    } catch (_) {
      // Extension context may be unavailable during reloads.
    }
  }

  document.addEventListener('keydown', (e) => {
    if (!isEditable(e.target)) return;
    const key = e.key || '';
    let keyCategory = 'character';
    if (key.length > 1) keyCategory = key.toLowerCase();
    if (e.ctrlKey || e.metaKey || e.altKey) keyCategory = 'modified';

    send({
      ...baseEvent('keydown', e.target),
      keyCategory,
      modifiers: {
        ctrl: e.ctrlKey,
        meta: e.metaKey,
        alt: e.altKey,
        shift: e.shiftKey
      }
    });
  }, true);

  document.addEventListener('paste', (e) => {
    if (!isEditable(e.target)) return;
    const text = e.clipboardData?.getData('text/plain') || '';
    send({
      ...baseEvent('paste', e.target),
      clipboardLength: text.length,
      insertedLength: text.length,
      snippet: safeSnippet(text)
    });
  }, true);

  document.addEventListener('copy', (e) => {
    if (!isEditable(e.target)) return;
    send(baseEvent('copy', e.target));
  }, true);

  document.addEventListener('cut', (e) => {
    if (!isEditable(e.target)) return;
    send(baseEvent('cut', e.target));
  }, true);

  document.addEventListener('drop', (e) => {
    if (!isEditable(e.target)) return;
    const text = e.dataTransfer?.getData('text/plain') || '';
    send({
      ...baseEvent('drop', e.target),
      insertedLength: text.length,
      snippet: safeSnippet(text)
    });
  }, true);

  document.addEventListener('beforeinput', (e) => {
    if (!isEditable(e.target)) return;
    const data = typeof e.data === 'string' ? e.data : '';
    const event = {
      ...baseEvent('beforeinput', e.target),
      inputType: e.inputType || null,
      insertedLength: data.length,
      snippet: safeSnippet(data)
    };

    if (e.inputType === 'insertFromPaste' || e.inputType === 'insertFromDrop' || data.length > 20) {
      send(event);
    }
  }, true);

  document.addEventListener('focusin', (e) => {
    if (!isEditable(e.target)) return;
    const el = getEditable(e.target);
    lastValue.set(el, getValueLength(el));
    send(baseEvent('focusin', e.target));
  }, true);

  document.addEventListener('input', (e) => {
    if (!isEditable(e.target)) return;
    const el = getEditable(e.target);
    const previous = lastValue.get(el) ?? getValueLength(el);
    const current = getValueLength(el);
    const delta = Math.max(0, current - previous);
    lastValue.set(el, current);

    if (delta >= 20) {
      send({
        ...baseEvent('input', e.target),
        inputType: e.inputType || null,
        insertedLength: delta
      });
    }
  }, true);
})();
