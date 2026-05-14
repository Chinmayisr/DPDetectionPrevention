/**
 * background.js — Dark Guard AI Service Worker
 *
 * Responsibilities:
 *   - Session management (generate + persist session_id)
 *   - Receive PAGE_LOADED / MANUAL_SCAN messages from content script
 *   - Call POST /api/v1/scan and cache results in chrome.storage.local
 *   - Update extension badge (count + colour) after each scan
 *   - Manage scan history (last 20 entries)
 *   - Send DOM highlight instructions to content script
 *   - Fire browser notifications for high-severity detections
 *
 * FIX (v1.0.1):
 *   - Rewrites localhost URLs to host.docker.internal before sending to
 *     the backend, so Playwright inside Docker can reach pages running
 *     on the host machine (e.g. localhost:8080/sale).
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// CONSTANTS
// ─────────────────────────────────────────────────────────────

const DEFAULT_BACKEND_URL = 'http://localhost:8000';
const SCAN_CACHE_TTL_MS   = 10 * 60 * 1000;   // 10 minutes
const MAX_HISTORY_ITEMS   = 20;

const SEVERITY_COLORS = {
  none:     '#16a34a',   // green
  low:      '#65a30d',   // lime
  medium:   '#d97706',   // amber
  high:     '#dc2626',   // red
  critical: '#7f1d1d',   // dark red
};

// Tabs currently being scanned (tabId → true)
const scanningTabs = new Set();

// ─────────────────────────────────────────────────────────────
// INSTALLATION — seed defaults
// ─────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(async () => {
  const existing = await chrome.storage.local.get([
    'session_id', 'settings', 'scan_history',
  ]);

  if (!existing.session_id) {
    await chrome.storage.local.set({
      session_id:         generateUUID(),
      session_page_count: 0,
    });
  }

  if (!existing.settings) {
    await chrome.storage.local.set({
      settings: {
        backend_url:          DEFAULT_BACKEND_URL,
        auto_scan:            true,
        confidence_threshold: 0.70,
        notifications:        true,
      },
    });
  }

  if (!existing.scan_history) {
    await chrome.storage.local.set({ scan_history: [] });
  }
});

// ─────────────────────────────────────────────────────────────
// TAB EVENTS — reset badge on navigation
// ─────────────────────────────────────────────────────────────

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === 'loading' && changeInfo.url) {
    chrome.action.setBadgeText({ text: '...', tabId });
    chrome.action.setBadgeBackgroundColor({ color: '#9E9E9E', tabId });
  }
});

// ─────────────────────────────────────────────────────────────
// MESSAGE HANDLER
// ─────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {

  switch (message.type) {

    case 'PAGE_LOADED':
      handlePageLoaded(message.url, sender.tab?.id);
      sendResponse({ status: 'received' });
      break;

    case 'MANUAL_SCAN':
      handleManualScan(message.url, message.tabId);
      sendResponse({ status: 'scanning' });
      break;

    case 'RESET_SESSION':
      resetSession()
        .then(newId => sendResponse({ status: 'reset', session_id: newId }));
      return true;   // async

    case 'GET_SCAN_RESULT':
      getScanResult(message.url)
        .then(result => sendResponse(result));
      return true;   // async

    case 'GET_STATUS':
      sendResponse({ scanning: scanningTabs.has(message.tabId) });
      break;

    default:
      break;
  }

  return true;
});

// ─────────────────────────────────────────────────────────────
// PAGE LOADED — auto-scan flow
// ─────────────────────────────────────────────────────────────

async function handlePageLoaded(url, tabId) {
  if (!tabId)                  return;

  const settings = await getSettings();
  if (!settings.auto_scan)     return;
  if (!isValidUrl(url))        return;
  if (scanningTabs.has(tabId)) return;

  // Return cached result within TTL
  const cached = await getCachedResult(url);
  if (cached) {
    updateBadge(tabId, cached);
    return;
  }

  await runScan(url, tabId);
}

// ─────────────────────────────────────────────────────────────
// MANUAL SCAN — force fresh scan
// ─────────────────────────────────────────────────────────────

async function handleManualScan(url, tabId) {
  if (!isValidUrl(url))        return;
  if (scanningTabs.has(tabId)) return;

  // Clear cache so the scan always runs fresh
  await chrome.storage.local.remove(cacheKey(url));

  await runScan(url, tabId);
}

// ─────────────────────────────────────────────────────────────
// CORE: RUN SCAN
// ─────────────────────────────────────────────────────────────

async function runScan(url, tabId) {
  scanningTabs.add(tabId);
  setBadgeScanning(tabId);

  try {
    const stored     = await chrome.storage.local.get(['session_id', 'settings']);
    const sessionId  = stored.session_id || generateUUID();
    const backendUrl = stored.settings?.backend_url || DEFAULT_BACKEND_URL;

    // ── Rewrite localhost → host.docker.internal ──────────────
    // Playwright runs inside Docker. When it tries to scrape a URL
    // like http://localhost:8080/sale, "localhost" inside the container
    // resolves to the container itself — not the host machine.
    // host.docker.internal always resolves to the host machine's IP
    // from inside Docker Desktop (Windows and Mac).
    const scrapeUrl = rewriteLocalhostForDocker(url);
    // ─────────────────────────────────────────────────────────

    const response = await fetch(`${backendUrl}/api/v1/scan`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ url: scrapeUrl, session_id: sessionId }),
    });

    if (!response.ok) {
      throw new Error(`Backend returned HTTP ${response.status}`);
    }

    const result = await response.json();

    // Cache result (keyed on original url so popup lookup works)
    await chrome.storage.local.set({
      [cacheKey(url)]: { result, timestamp: Date.now(), url },
    });

    // Update history
    await addToHistory(url, result);

    // Increment session page count
    await incrementSessionPageCount();

    // Update badge
    updateBadge(tabId, { result, timestamp: Date.now(), url });

    // Browser notification for high/critical severity
    const settings = stored.settings || {};
    if (settings.notifications && result.total_detected > 0) {
      const sev = result.overall_severity_label;
      if (sev === 'high' || sev === 'critical') {
        chrome.notifications.create(`scan_${Date.now()}`, {
          type:     'basic',
          iconUrl:  'icons/icon48.png',
          title:    'Dark Guard AI — Warning',
          message:  `${result.total_detected} dark pattern(s) detected. Severity: ${sev.toUpperCase()}`,
          priority: 2,
        });
      }
    }

    // Send DOM highlight instructions to content script
    const selectors = extractSelectors(result.detected_patterns || []);
    if (selectors.length > 0) {
      chrome.tabs.sendMessage(tabId, {
        type:     'HIGHLIGHT_ELEMENTS',
        patterns: selectors,
      }).catch(() => {});   // content script may not be present on all pages
    }

  } catch (error) {
    // Store error state so popup can display it
    await chrome.storage.local.set({
      [cacheKey(url)]: {
        result:    null,
        error:     error.message,
        timestamp: Date.now(),
        url,
      },
    });

    chrome.action.setBadgeText({ text: '!', tabId });
    chrome.action.setBadgeBackgroundColor({ color: '#dc2626', tabId });

  } finally {
    scanningTabs.delete(tabId);
  }
}

// ─────────────────────────────────────────────────────────────
// BADGE HELPERS
// ─────────────────────────────────────────────────────────────

function setBadgeScanning(tabId) {
  chrome.action.setBadgeText({ text: '...', tabId });
  chrome.action.setBadgeBackgroundColor({ color: '#9E9E9E', tabId });
}

function updateBadge(tabId, cached) {
  if (!cached) {
    chrome.action.setBadgeText({ text: '', tabId });
    return;
  }

  if (cached.error) {
    chrome.action.setBadgeText({ text: '!', tabId });
    chrome.action.setBadgeBackgroundColor({ color: '#dc2626', tabId });
    return;
  }

  const result = cached.result;
  if (!result) return;

  const count    = result.total_detected || 0;
  const severity = result.overall_severity_label || 'none';

  chrome.action.setBadgeText({
    text: count === 0 ? '✓' : String(count),
    tabId,
  });
  chrome.action.setBadgeBackgroundColor({
    color: count === 0 ? '#16a34a' : (SEVERITY_COLORS[severity] || '#d97706'),
    tabId,
  });
}

// ─────────────────────────────────────────────────────────────
// HISTORY
// ─────────────────────────────────────────────────────────────

async function addToHistory(url, result) {
  const { scan_history = [] } = await chrome.storage.local.get('scan_history');

  const entry = {
    url,
    timestamp:        Date.now(),
    total_detected:   result.total_detected        || 0,
    severity_label:   result.overall_severity_label || 'none',
    severity_score:   result.overall_severity_score || 0,
    page_type:        result.page_type               || 'OTHER',
    scan_duration_ms: result.scan_duration_ms        || 0,
    detected_patterns: (result.detected_patterns || []).map(p => ({
      pattern_code: p.pattern_code,
      pattern_name: p.pattern_name,
      confidence:   p.confidence,
    })),
  };

  const updated = [entry, ...scan_history].slice(0, MAX_HISTORY_ITEMS);
  await chrome.storage.local.set({ scan_history: updated });
}

// ─────────────────────────────────────────────────────────────
// UTILITIES
// ─────────────────────────────────────────────────────────────

async function getScanResult(url) {
  const data = await chrome.storage.local.get(cacheKey(url));
  return data[cacheKey(url)] || null;
}

async function getCachedResult(url) {
  const data   = await chrome.storage.local.get(cacheKey(url));
  const cached = data[cacheKey(url)];
  if (!cached)                                             return null;
  if (Date.now() - cached.timestamp > SCAN_CACHE_TTL_MS)  return null;
  return cached;
}

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return settings || {
    backend_url:          DEFAULT_BACKEND_URL,
    auto_scan:            true,
    confidence_threshold: 0.70,
    notifications:        true,
  };
}

async function resetSession() {
  const newId = generateUUID();
  await chrome.storage.local.set({ session_id: newId, session_page_count: 0 });
  return newId;
}

async function incrementSessionPageCount() {
  const { session_page_count = 0 } = await chrome.storage.local.get('session_page_count');
  await chrome.storage.local.set({ session_page_count: session_page_count + 1 });
}

function extractSelectors(patterns) {
  const result = [];
  for (const pattern of patterns) {
    for (const ev of (pattern.evidence || [])) {
      if (ev.css_selector) {
        result.push({
          selector:     ev.css_selector,
          pattern_code: pattern.pattern_code,
          pattern_name: pattern.pattern_name,
          confidence:   pattern.confidence,
        });
      }
    }
  }
  return result;
}

/**
 * Rewrite localhost/127.0.0.1 URLs so Playwright inside Docker
 * can reach pages running on the host machine.
 *
 * Examples:
 *   http://localhost:8080/sale  →  http://host.docker.internal:8080/sale
 *   http://127.0.0.1:3000/     →  http://host.docker.internal:3000/
 *   https://example.com/       →  https://example.com/  (unchanged)
 */
function rewriteLocalhostForDocker(url) {
  try {
    const parsed = new URL(url);
    if (
      parsed.hostname === 'localhost' ||
      parsed.hostname === '127.0.0.1'
    ) {
      parsed.hostname = 'host.docker.internal';
      return parsed.toString();
    }
  } catch {
    // Malformed URL — return as-is and let the backend handle the error
  }
  return url;
}

function isValidUrl(url) {
  return url && (url.startsWith('http://') || url.startsWith('https://'));
}

function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

function cacheKey(url) {
  try {
    const p = new URL(url);
    // Key on origin + pathname — ignore query params to improve cache hit rate
    const raw = p.origin + p.pathname;
    return 'result_' + btoa(unescape(encodeURIComponent(raw)))
                           .replace(/[^a-zA-Z0-9]/g, '')
                           .slice(0, 50);
  } catch {
    return 'result_' + btoa(url).replace(/[^a-zA-Z0-9]/g, '').slice(0, 50);
  }
}