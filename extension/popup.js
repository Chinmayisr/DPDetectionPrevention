/**
 * popup.js — Dark Guard AI Popup Logic
 *
 * Updated for:
 * - Prevention agent schema
 * - all_detected_patterns support
 * - NaN fixes
 * - prevention rendering
 * - robust fallback handling
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────

const PATTERN_SEVERITY_MAP = {
  DP01: 'medium',
  DP02: 'medium',
  DP03: 'low',
  DP04: 'medium',
  DP05: 'high',
  DP06: 'high',
  DP07: 'high',
  DP08: 'critical',
  DP09: 'low',
  DP10: 'medium',
  DP11: 'critical',
  DP12: 'medium',
  DP13: 'high',
};

const SEVERITY_LABELS = {
  none: 'CLEAN',
  low: 'LOW',
  medium: 'MEDIUM',
  high: 'HIGH',
  critical: 'CRITICAL',
};

// ─────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', initPopup);

async function initPopup() {
  setupTabs();
  setupActionBar();
  setupSettings();
  setupHistory();

  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });

  if (!tab) return;

  displayUrl(tab.url);
  await loadSessionInfo();

  const status = await sendToBackground({
    type: 'GET_STATUS',
    tabId: tab.id,
  });

  if (status?.scanning) {
    showState('loading');
    pollForResult(tab.url, tab.id);
    return;
  }

  const cached = await sendToBackground({
    type: 'GET_SCAN_RESULT',
    url: tab.url,
  });

  if (cached) {
    renderCached(cached);
  } else {
    showState('idle');
  }
}

// ─────────────────────────────────────────────────────────────
// TABS
// ─────────────────────────────────────────────────────────────

function setupTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.dataset.tab;

      document.querySelectorAll('.tab-btn')
        .forEach(b => b.classList.remove('active'));

      document.querySelectorAll('.tab-panel')
        .forEach(p => p.hidden = true);

      btn.classList.add('active');

      const panel = document.getElementById(`tab-${targetTab}`);
      if (panel) {
        panel.hidden = false;
      }

      if (targetTab === 'history') {
        loadHistory();
      }
    });
  });
}

// ─────────────────────────────────────────────────────────────
// ACTION BAR
// ─────────────────────────────────────────────────────────────

function setupActionBar() {
  const scanBtn = document.getElementById('btn-scan');

  if (scanBtn) {
    scanBtn.addEventListener('click', async () => {
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });

      if (!tab?.url) return;

      showState('loading');
      hideExportButton();

      sendToBackground({
        type: 'MANUAL_SCAN',
        url: tab.url,
        tabId: tab.id,
      });

      pollForResult(tab.url, tab.id);
    });
  }

  const exportBtn = document.getElementById('btn-export');

  if (exportBtn) {
    exportBtn.addEventListener('click', async () => {
      const [tab] = await chrome.tabs.query({
        active: true,
        currentWindow: true,
      });

      if (!tab?.url) return;

      const cached = await sendToBackground({
        type: 'GET_SCAN_RESULT',
        url: tab.url,
      });

      if (!cached?.result) return;

      const blob = new Blob(
        [JSON.stringify(cached.result, null, 2)],
        { type: 'application/json' },
      );

      const url = URL.createObjectURL(blob);

      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `darkguard-${slugify(tab.url)}.json`;
      anchor.click();

      URL.revokeObjectURL(url);
    });
  }
}

function pollForResult(url, tabId) {
  let attempts = 0;
  const MAX_ATTEMPTS = 30;

  const interval = setInterval(async () => {
    attempts++;

    const status = await sendToBackground({
      type: 'GET_STATUS',
      tabId,
    });

    if (!status?.scanning) {
      clearInterval(interval);

      const cached = await sendToBackground({
        type: 'GET_SCAN_RESULT',
        url,
      });

      if (cached) {
        renderCached(cached);
      } else {
        showState('error');

        const err = document.getElementById('error-message');

        if (err) {
          err.textContent =
            'Scan finished but no result was stored.';
        }
      }

      return;
    }

    if (attempts >= MAX_ATTEMPTS) {
      clearInterval(interval);

      showState('error');

      const err = document.getElementById('error-message');

      if (err) {
        err.textContent =
          'Scan timed out after 60 seconds.';
      }
    }
  }, 2000);
}

// ─────────────────────────────────────────────────────────────
// RENDER CACHED
// ─────────────────────────────────────────────────────────────

function renderCached(cached) {
  if (cached.error) {
    showState('error');

    const err = document.getElementById('error-message');

    if (err) {
      err.textContent = cached.error;
    }

    return;
  }

  const result = cached.result;

  window.latestResult = result;

  if (!result) {
    showState('error');
    return;
  }

  if ((result.total_detected || 0) === 0) {
    showState('clean');

    const clean = document.getElementById('clean-summary');

    if (clean) {
      clean.textContent =
        result.synthesis_summary ||
        'This page appears to follow fair UX practices.';
    }

    return;
  }

  showState('results');
  renderResults(result);
}

// ─────────────────────────────────────────────────────────────
// RENDER RESULTS
// ─────────────────────────────────────────────────────────────

function renderResults(result) {
  const patterns =
    result.all_detected_patterns ||
    result.detected_patterns ||
    [];

  const severityCount = document.getElementById('severity-count');

  if (severityCount) {
    severityCount.textContent =
      result.total_detected || patterns.length || 0;
  }

  const chip = document.getElementById('severity-chip');

  const sev =
    result.overall_severity_label ||
    result.behavioral_severity_label ||
    'none';

  if (chip) {
    chip.textContent =
      SEVERITY_LABELS[sev] || sev.toUpperCase();

    chip.dataset.sev = sev;
  }

  renderPatterns(patterns);

  const synthCard = document.getElementById('synthesis-card');
  const synthText = document.getElementById('synthesis-text');

  if (result.synthesis_summary && synthCard && synthText) {
    synthCard.hidden = false;
    synthText.textContent = result.synthesis_summary;
  }

  setMetaChip(
    'meta-page-type',
    `📄 ${result.page_type || 'UNKNOWN'}`
  );

  setMetaChip(
    'meta-duration',
    `⏱ ${((result.total_duration_ms || 0) / 1000).toFixed(1)}s`
  );

  setMetaChip(
    'meta-agents',
    '🤖 NLP, Visual, Behavioral, Pricing'
  );

  setMetaChip(
    'meta-iterations',
    '🔁 1 iteration(s)'
  );

  const prevention = result.prevention || {};

  if (prevention.total_patches) {
    setMetaChip(
      'meta-prevention',
      `🛡 ${prevention.total_patches} protections`
    );
  }

  const exportBtn = document.getElementById('btn-export');

  if (exportBtn) {
    exportBtn.hidden = false;
  }
}

function renderPatterns(patterns) {
  const list = document.getElementById('pattern-list');

  if (!list) return;

  list.innerHTML = '';

  patterns = (patterns || []).filter(p => p.detected);

  if (!patterns.length) {
    list.innerHTML = `
      <div class="empty-state">
        No dark patterns detected.
      </div>
    `;

    return;
  }

  patterns.forEach(p => {
    const sev =
      PATTERN_SEVERITY_MAP[p.pattern_code] || 'medium';

    const conf =
      Math.round(Number(p.confidence || 0) * 100);

    const item = document.createElement('div');
    item.className = 'pattern-item';

    const header = document.createElement('div');
    header.className = 'pattern-header';

    header.innerHTML = `
      <span class="pattern-code-badge sev-${sev}">
        ${escHtml(p.pattern_code || 'DP')}
      </span>

      <span class="pattern-name">
        ${escHtml(p.pattern_name || p.pattern_code)}
      </span>

      <span class="pattern-confidence">
        ${isNaN(conf) ? 0 : conf}%
      </span>

      <span class="pattern-expand-icon">▼</span>
    `;

    const body = document.createElement('div');
    body.className = 'pattern-body';

    const detectedBy = Array.isArray(p.detected_by)
      ? p.detected_by.join(', ')
      : (p.detected_by || 'Unknown');

    const byEl = document.createElement('p');
    byEl.className = 'pattern-detected-by';
    byEl.textContent = `Detected by: ${detectedBy}`;

    body.appendChild(byEl);

    // ─────────────────────────────────────────
    // Evidence Section
    // ─────────────────────────────────────────

    const evidence =
      (p.evidence || []).filter(e => e.text);

    if (evidence.length) {
      const evList = document.createElement('div');
      evList.className = 'evidence-list';

      evidence.slice(0, 5).forEach(ev => {
        const evEl = document.createElement('div');
        evEl.className = 'evidence-item';

        evEl.innerHTML = `
          <p class="evidence-text">
            "${escHtml(ev.text?.slice(0, 200) || '')}"
          </p>

          ${
            ev.reason
              ? `
                <p class="evidence-reason">
                  ↳ ${escHtml(ev.reason)}
                </p>
              `
              : ''
          }

          ${
            ev.location
              ? `
                <p class="evidence-location">
                  📍 ${escHtml(ev.location)}
                </p>
              `
              : ''
          }
        `;

        evList.appendChild(evEl);
      });

      body.appendChild(evList);
    }

    // ─────────────────────────────────────────
    // Prevention Strategies Section
    // ─────────────────────────────────────────

    const prevention =
      window.latestResult?.prevention;

    const patchInstructions =
      prevention?.patch_instructions || [];

    const relatedPatches =
      patchInstructions.filter(
        patch =>
          patch.pattern_code === p.pattern_code
      );

    if (relatedPatches.length) {
      const preventionSection =
        document.createElement('div');

      preventionSection.className =
        'prevention-section';

      preventionSection.innerHTML = `
        <div class="prevention-header">
          🛡 Prevention Strategies
        </div>
      `;

      relatedPatches.forEach(patch => {
        const patchEl =
          document.createElement('div');

        patchEl.className =
          'prevention-item';

        patchEl.innerHTML = `
          <div class="prevention-action">
            ${escHtml(
              patch.action || 'PATCH'
            )}
          </div>

          <div class="prevention-description">
            ${escHtml(
              patch.description ||
              'Dark Guard mitigation applied'
            )}
          </div>

          ${
            patch.css_selector
              ? `
                <div class="prevention-selector">
                  🎯 ${escHtml(
                    patch.css_selector
                  )}
                </div>
              `
              : ''
          }

          ${
            patch.priority
              ? `
                <div class="prevention-priority">
                  Priority: ${patch.priority}
                </div>
              `
              : ''
          }
        `;

        preventionSection.appendChild(patchEl);
      });

      body.appendChild(preventionSection);
    }

    // ─────────────────────────────────────────
    // Expand Toggle
    // ─────────────────────────────────────────

    header.addEventListener('click', () => {
      item.classList.toggle('expanded');
    });

    item.appendChild(header);
    item.appendChild(body);

    list.appendChild(item);
  });
}

// ─────────────────────────────────────────────────────────────
// STATE MANAGEMENT
// ─────────────────────────────────────────────────────────────

function showState(name) {
  ['loading', 'clean', 'error', 'idle', 'results']
    .forEach(s => {
      const el = document.getElementById(`state-${s}`);

      if (el) {
        el.hidden = (s !== name);
      }
    });

  if (name !== 'results') {
    const patternList =
      document.getElementById('pattern-list');

    if (patternList) {
      patternList.innerHTML = '';
    }
  }
}

// ─────────────────────────────────────────────────────────────
// HISTORY
// ─────────────────────────────────────────────────────────────

function setupHistory() {
  const clearBtn =
    document.getElementById('btn-clear-history');

  if (!clearBtn) return;

  clearBtn.addEventListener('click', async () => {
    await chrome.storage.local.set({
      scan_history: [],
    });

    loadHistory();
  });
}

async function loadHistory() {
  const { scan_history = [] } =
    await chrome.storage.local.get('scan_history');

  const list = document.getElementById('history-list');

  if (!list) return;

  list.innerHTML = '';

  if (!scan_history.length) {
    list.innerHTML =
      '<div class="empty-state">No scan history yet</div>';

    return;
  }

  scan_history.forEach(entry => {
    const item = document.createElement('div');

    item.className = 'history-item';

    item.textContent =
      safeDomain(entry.url || 'Unknown');

    list.appendChild(item);
  });
}

// ─────────────────────────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────────────────────────

function setupSettings() {}

async function loadSessionInfo() {
  const stored =
    await chrome.storage.local.get([
      'session_id',
      'session_page_count',
    ]);

  const count =
    stored.session_page_count || 0;

  const sid =
    stored.session_id || '—';

  const pageCount =
    document.getElementById('session-page-count');

  const sidDisplay =
    document.getElementById('session-id-display');

  const pagesDisplay =
    document.getElementById('session-pages-display');

  if (pageCount) {
    pageCount.textContent = count;
  }

  if (sidDisplay) {
    sidDisplay.textContent =
      sid.slice(0, 8) + '…';
  }

  if (pagesDisplay) {
    pagesDisplay.textContent = count;
  }
}

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────

function displayUrl(url) {
  if (!url) return;

  const el = document.getElementById('current-url');

  if (!el) return;

  try {
    const parsed = new URL(url);

    el.textContent =
      parsed.hostname +
      (parsed.pathname !== '/' ? parsed.pathname : '');

    el.title = url;
  } catch {
    el.textContent = url.slice(0, 50);
  }
}

function setMetaChip(id, text) {
  const el = document.getElementById(id);

  if (el) {
    el.textContent = text;
  }
}

function hideExportButton() {
  const btn = document.getElementById('btn-export');

  if (btn) {
    btn.hidden = true;
  }
}

function sendToBackground(message) {
  return new Promise(resolve => {
    chrome.runtime.sendMessage(
      message,
      response => {
        if (chrome.runtime.lastError) {
          resolve(null);
        } else {
          resolve(response);
        }
      }
    );
  });
}

function escHtml(str) {
  if (!str) return '';

  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function slugify(url) {
  try {
    return new URL(url)
      .hostname
      .replace(/\./g, '-');
  } catch {
    return 'page';
  }
}

function safeDomain(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return url || '—';
  }
}