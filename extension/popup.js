/**
 * popup.js — Dark Guard AI Popup Logic
 *
 * Handles all UI interaction in the popup:
 *   - Tab switching
 *   - Results rendering (loading / clean / error / detected states)
 *   - Per-pattern expandable details with evidence
 *   - Financial impact alert
 *   - History list
 *   - Settings load/save
 *   - Session info
 *   - Manual scan + export
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────

const PATTERN_SEVERITY_MAP = {
  DP01: 'medium',  DP02: 'medium',  DP03: 'low',
  DP04: 'medium',  DP05: 'high',    DP06: 'high',
  DP07: 'high',    DP08: 'critical', DP09: 'low',
  DP10: 'medium',  DP11: 'critical', DP12: 'medium',
  DP13: 'high',
};

const SEVERITY_LABELS = {
  none:     'CLEAN',
  low:      'LOW',
  medium:   'MEDIUM',
  high:     'HIGH',
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

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;

  displayUrl(tab.url);
  await loadSessionInfo();

  // Check if a scan is currently running
  const status = await sendToBackground({ type: 'GET_STATUS', tabId: tab.id });
  if (status?.scanning) {
    showState('loading');
    pollForResult(tab.url, tab.id);
    return;
  }

  // Load existing result from cache
  const cached = await sendToBackground({ type: 'GET_SCAN_RESULT', url: tab.url });
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

      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.hidden = true);

      btn.classList.add('active');
      document.getElementById(`tab-${targetTab}`).hidden = false;

      // Refresh history when switching to it
      if (targetTab === 'history') loadHistory();
    });
  });
}

// ─────────────────────────────────────────────────────────────
// ACTION BAR — Scan + Export
// ─────────────────────────────────────────────────────────────

function setupActionBar() {
  document.getElementById('btn-scan').addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url) return;

    showState('loading');
    hideExportButton();

    sendToBackground({ type: 'MANUAL_SCAN', url: tab.url, tabId: tab.id });
    pollForResult(tab.url, tab.id);
  });

  document.getElementById('btn-export').addEventListener('click', async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url) return;

    const cached = await sendToBackground({ type: 'GET_SCAN_RESULT', url: tab.url });
    if (!cached?.result) return;

    const blob = new Blob(
      [JSON.stringify(cached.result, null, 2)],
      { type: 'application/json' },
    );
    const url    = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href     = url;
    anchor.download = `darkguard-${slugify(tab.url)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  });
}

// Poll every 2 seconds until result appears in storage
function pollForResult(url, tabId) {
  let attempts = 0;
  const MAX_ATTEMPTS = 30;   // 60 seconds maximum

  const interval = setInterval(async () => {
    attempts++;

    const status = await sendToBackground({ type: 'GET_STATUS', tabId });
    if (!status?.scanning) {
      clearInterval(interval);
      const cached = await sendToBackground({ type: 'GET_SCAN_RESULT', url });
      if (cached) {
        renderCached(cached);
      } else {
        showState('error');
        document.getElementById('error-message').textContent =
          'Scan finished but no result was stored. Check backend logs.';
      }
      return;
    }

    if (attempts >= MAX_ATTEMPTS) {
      clearInterval(interval);
      showState('error');
      document.getElementById('error-message').textContent =
        'Scan timed out after 60 seconds. The page may be too slow or the backend is unreachable.';
    }
  }, 2000);
}

// ─────────────────────────────────────────────────────────────
// RENDER CACHED RESULT
// ─────────────────────────────────────────────────────────────

function renderCached(cached) {
  if (cached.error) {
    showState('error');
    document.getElementById('error-message').textContent = cached.error;
    return;
  }

  const result = cached.result;
  if (!result) { showState('error'); return; }

  if (result.total_detected === 0) {
    showState('clean');
    document.getElementById('clean-summary').textContent =
      result.synthesis_summary || 'This page appears to follow fair UX practices.';
    return;
  }

  showState('results');
  renderResults(result);
}

// ─────────────────────────────────────────────────────────────
// RENDER RESULTS
// ─────────────────────────────────────────────────────────────

function renderResults(result) {
  // Severity banner
  document.getElementById('severity-count').textContent = result.total_detected;
  const chip = document.getElementById('severity-chip');
  const sev  = result.overall_severity_label || 'none';
  chip.textContent    = SEVERITY_LABELS[sev] || sev.toUpperCase();
  chip.dataset.sev    = sev;

  // Financial impact alert
  const fi = result.financial_impact || {};
  if (fi.total_extra_charged && fi.total_extra_charged > 0) {
    document.getElementById('financial-alert').hidden = false;
    document.getElementById('financial-detail').textContent =
      `₹${fi.total_extra_charged.toFixed(2)} in hidden/extra charges detected` +
      (fi.drip_pricing_hidden_amount > 0 ? ` (Drip: ₹${fi.drip_pricing_hidden_amount.toFixed(2)})` : '') +
      (fi.bait_switch_overcharge > 0 ? ` (Bait & Switch: ₹${fi.bait_switch_overcharge.toFixed(2)})` : '');
  }

  // Agent error warning
  const errors = (result.errors || []).filter(Boolean);
  if (errors.length > 0) {
    document.getElementById('agent-error-alert').hidden = false;
  }

  // Pattern list
  renderPatterns(result.detected_patterns || []);

  // Synthesis summary
  if (result.synthesis_summary) {
    document.getElementById('synthesis-card').hidden = false;
    document.getElementById('synthesis-text').textContent = result.synthesis_summary;
  }

  // Scan meta chips
  setMetaChip('meta-page-type',   `📄 ${result.page_type || 'UNKNOWN'}`);
  setMetaChip('meta-duration',    `⏱ ${(result.scan_duration_ms / 1000).toFixed(1)}s`);
  setMetaChip('meta-agents',      `🤖 ${(result.agents_invoked || []).join(', ')}`);
  setMetaChip('meta-iterations',  `🔁 ${result.iterations_run || 1} iteration(s)`);

  // Show export button
  document.getElementById('btn-export').hidden = false;
}

function renderPatterns(patterns) {
  const list = document.getElementById('pattern-list');
  list.innerHTML = '';

  if (!patterns.length) return;

  patterns.forEach(p => {
    const sev  = PATTERN_SEVERITY_MAP[p.pattern_code] || 'medium';
    const conf = Math.round((p.confidence || 0) * 100);

    const item = document.createElement('div');
    item.className = 'pattern-item';

    // Header row
    const header = document.createElement('div');
    header.className = 'pattern-header';
    header.innerHTML = `
      <span class="pattern-code-badge sev-${sev}">${p.pattern_code}</span>
      <span class="pattern-name">${escHtml(p.pattern_name || p.pattern_code)}</span>
      <span class="pattern-confidence">${conf}%</span>
      <span class="pattern-expand-icon">▼</span>
    `;

    // Body — evidence
    const body = document.createElement('div');
    body.className = 'pattern-body';

    const detectedBy = (p.detected_by || []).join(', ');
    if (detectedBy) {
      const byEl = document.createElement('p');
      byEl.className = 'pattern-detected-by';
      byEl.textContent = `Detected by: ${detectedBy}`;
      body.appendChild(byEl);
    }

    const evidence = (p.evidence || []).filter(e => e.text);
    if (evidence.length) {
      const evList = document.createElement('div');
      evList.className = 'evidence-list';

      evidence.slice(0, 5).forEach(ev => {
        const evEl = document.createElement('div');
        evEl.className = 'evidence-item';
        evEl.innerHTML = `
          <p class="evidence-text">"${escHtml(ev.text?.slice(0, 200) || '')}"</p>
          ${ev.reason ? `<p class="evidence-reason">↳ ${escHtml(ev.reason)}</p>` : ''}
          ${ev.location ? `<p class="evidence-reason">📍 ${escHtml(ev.location)}</p>` : ''}
        `;
        evList.appendChild(evEl);
      });

      body.appendChild(evList);
    } else {
      body.innerHTML += `<p class="evidence-reason" style="margin-top:6px">No specific evidence text captured.</p>`;
    }

    // Toggle expand
    header.addEventListener('click', () => item.classList.toggle('expanded'));

    item.appendChild(header);
    item.appendChild(body);
    list.appendChild(item);
  });
}

// ─────────────────────────────────────────────────────────────
// STATE MANAGEMENT
// ─────────────────────────────────────────────────────────────

function showState(name) {
  ['loading', 'clean', 'error', 'idle', 'results'].forEach(s => {
    const el = document.getElementById(`state-${s}`);
    if (el) el.hidden = (s !== name);
  });

  // Reset alerts + meta on fresh render
  if (name !== 'results') {
    document.getElementById('financial-alert').hidden   = true;
    document.getElementById('agent-error-alert').hidden = true;
    document.getElementById('synthesis-card').hidden    = true;
    document.getElementById('pattern-list').innerHTML   = '';
  }
}

// ─────────────────────────────────────────────────────────────
// HISTORY
// ─────────────────────────────────────────────────────────────

function setupHistory() {
  document.getElementById('btn-clear-history').addEventListener('click', async () => {
    await chrome.storage.local.set({ scan_history: [] });
    loadHistory();
  });
}

async function loadHistory() {
  const { scan_history = [] } = await chrome.storage.local.get('scan_history');
  const list = document.getElementById('history-list');
  list.innerHTML = '';

  if (!scan_history.length) {
    list.innerHTML = '<div class="empty-state">No scan history yet</div>';
    return;
  }

  scan_history.forEach(entry => {
    const sev    = entry.severity_label || 'none';
    const count  = entry.total_detected || 0;
    const time   = formatTime(entry.timestamp);
    const domain = safeDomain(entry.url);

    const item = document.createElement('div');
    item.className = 'history-item';
    item.innerHTML = `
      <div class="history-item-top">
        <span class="history-url" title="${escHtml(entry.url)}">${escHtml(domain)}</span>
        <span class="history-chip severity-chip" data-sev="${sev}">
          ${SEVERITY_LABELS[sev] || sev.toUpperCase()}
        </span>
      </div>
      <div class="history-item-bottom">
        <span class="history-time">${time}</span>
        <span class="history-count" style="color:${count > 0 ? 'var(--accent)' : 'var(--success)'}">
          ${count === 0 ? '✓ Clean' : `${count} pattern${count > 1 ? 's' : ''}`}
        </span>
      </div>
      ${entry.detected_patterns?.length
        ? `<p class="history-patterns">${entry.detected_patterns.map(p => p.pattern_code).join(' · ')}</p>`
        : ''}
    `;
    list.appendChild(item);
  });
}

// ─────────────────────────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────────────────────────

function setupSettings() {
  // Threshold slider display
  const slider = document.getElementById('setting-threshold');
  slider.addEventListener('input', () => {
    document.getElementById('threshold-display').textContent = `${slider.value}%`;
  });

  // Save settings
  document.getElementById('btn-save-settings').addEventListener('click', saveSettings);

  // Reset session
  document.getElementById('btn-reset-session').addEventListener('click', async () => {
    const result = await sendToBackground({ type: 'RESET_SESSION' });
    if (result?.status === 'reset') {
      await loadSessionInfo();
      const statusEl = document.getElementById('save-status');
      statusEl.textContent = '✓ Session reset';
      setTimeout(() => { statusEl.textContent = ''; }, 2500);
    }
  });

  // Load initial values
  loadSettingsUI();
}

async function loadSettingsUI() {
  const { settings } = await chrome.storage.local.get('settings');
  if (!settings) return;

  document.getElementById('setting-backend-url').value   = settings.backend_url || '';
  document.getElementById('setting-auto-scan').checked   = !!settings.auto_scan;
  document.getElementById('setting-notifications').checked = !!settings.notifications;

  const threshold = Math.round((settings.confidence_threshold || 0.70) * 100);
  document.getElementById('setting-threshold').value     = threshold;
  document.getElementById('threshold-display').textContent = `${threshold}%`;
}

async function saveSettings() {
  const backendUrl  = document.getElementById('setting-backend-url').value.trim();
  const autoScan    = document.getElementById('setting-auto-scan').checked;
  const notifs      = document.getElementById('setting-notifications').checked;
  const threshold   = parseInt(document.getElementById('setting-threshold').value) / 100;

  await chrome.storage.local.set({
    settings: {
      backend_url:          backendUrl || 'http://localhost:8000',
      auto_scan:            autoScan,
      notifications:        notifs,
      confidence_threshold: threshold,
    },
  });

  const statusEl = document.getElementById('save-status');
  statusEl.textContent = '✓ Settings saved';
  setTimeout(() => { statusEl.textContent = ''; }, 2500);
}

// ─────────────────────────────────────────────────────────────
// SESSION INFO
// ─────────────────────────────────────────────────────────────

async function loadSessionInfo() {
  const stored = await chrome.storage.local.get(['session_id', 'session_page_count']);
  const count  = stored.session_page_count || 0;
  const sid    = stored.session_id || '—';

  document.getElementById('session-page-count').textContent  = count;
  document.getElementById('session-id-display').textContent  = sid.slice(0, 8) + '…';
  document.getElementById('session-pages-display').textContent = count;
}

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────

function displayUrl(url) {
  if (!url) return;
  const el = document.getElementById('current-url');
  try {
    const parsed = new URL(url);
    el.textContent = parsed.hostname + (parsed.pathname !== '/' ? parsed.pathname : '');
    el.title       = url;
  } catch {
    el.textContent = url.slice(0, 50);
  }
}

function setMetaChip(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function hideExportButton() {
  document.getElementById('btn-export').hidden = true;
}

function sendToBackground(message) {
  return new Promise(resolve => {
    chrome.runtime.sendMessage(message, response => {
      if (chrome.runtime.lastError) resolve(null);
      else resolve(response);
    });
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
    return new URL(url).hostname.replace(/\./g, '-');
  } catch {
    return 'page';
  }
}

function safeDomain(url) {
  try {
    const p = new URL(url);
    return p.hostname + (p.pathname !== '/' ? p.pathname.slice(0, 30) : '');
  } catch {
    return url?.slice(0, 40) || '—';
  }
}

function formatTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  const now = new Date();
  const diff = now - d;

  if (diff < 60000)     return 'Just now';
  if (diff < 3600000)   return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000)  return `${Math.floor(diff / 3600000)}h ago`;
  return d.toLocaleDateString();
}
