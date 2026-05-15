/**
 * background.js — Dark Guard AI
 *
 * Responsibilities:
 *  - Maintain browsing session
 *  - Trigger backend scans
 *  - Store scan results
 *  - Update extension badge
 *  - Send highlight instructions
 *  - Send prevention patch instructions
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// CONFIG
// ─────────────────────────────────────────────────────────────

const DEFAULT_SETTINGS = {
  backend_url: 'http://localhost:8000',
  auto_scan: true,
  notifications: true,
  confidence_threshold: 0.70,
};

const SCAN_DEBOUNCE_MS = 2500;

// ─────────────────────────────────────────────────────────────
// GLOBAL STATE
// ─────────────────────────────────────────────────────────────

const activeScans = new Map();
const recentScans = new Map();

let currentSessionId = crypto.randomUUID();
let sessionPageCount = 0;

// ─────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(async () => {

  console.log('[DarkGuard] Extension installed');

  const stored =
    await chrome.storage.local.get([
      'settings',
      'session_id',
      'session_page_count',
    ]);

  if (!stored.settings) {
    await chrome.storage.local.set({
      settings: DEFAULT_SETTINGS,
    });
  }

  if (stored.session_id) {
    currentSessionId = stored.session_id;
  } else {
    await chrome.storage.local.set({
      session_id: currentSessionId,
    });
  }

  sessionPageCount =
    stored.session_page_count || 0;

  updateBadge('ON', '#2563eb');
});

// ─────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener(
  (message, sender, sendResponse) => {

    (async () => {

      try {

        // ─────────────────────────
        // PAGE LOADED
        // ─────────────────────────

        if (message.type === 'PAGE_LOADED') {

          const settings =
            await getSettings();

          if (!settings.auto_scan) {
            sendResponse({ ok: true });
            return;
          }

          const tabId =
            sender.tab?.id;

          if (!tabId) {
            sendResponse({ ok: false });
            return;
          }

          triggerScan(
            message.url,
            tabId,
          );

          sendResponse({ ok: true });

          return;
        }

        // ─────────────────────────
        // MANUAL SCAN
        // ─────────────────────────

        if (message.type === 'MANUAL_SCAN') {

          triggerScan(
            message.url,
            message.tabId,
            true,
          );

          sendResponse({ ok: true });

          return;
        }

        // ─────────────────────────
        // GET STATUS
        // ─────────────────────────

        if (message.type === 'GET_STATUS') {

          sendResponse({
            scanning:
              activeScans.has(message.tabId),
          });

          return;
        }

        // ─────────────────────────
        // GET SCAN RESULT
        // ─────────────────────────

        if (
          message.type ===
          'GET_SCAN_RESULT'
        ) {

          const key =
            cacheKey(message.url);

          const result =
            recentScans.get(key);

          sendResponse(result || null);

          return;
        }

        // ─────────────────────────
        // RESET SESSION
        // ─────────────────────────

        if (message.type === 'RESET_SESSION') {

          currentSessionId =
            crypto.randomUUID();

          sessionPageCount = 0;

          await chrome.storage.local.set({
            session_id: currentSessionId,
            session_page_count:
              sessionPageCount,
          });

          sendResponse({
            status: 'reset',
          });

          return;
        }

      } catch (err) {

        console.error(
          '[DarkGuard] Background error:',
          err
        );

        sendResponse({
          ok: false,
          error: String(err),
        });
      }

    })();

    return true;
  }
);

// ─────────────────────────────────────────────────────────────
// SCAN PIPELINE
// ─────────────────────────────────────────────────────────────

async function triggerScan(
  url,
  tabId,
  force = false
) {

  if (!url || !tabId) {
    return;
  }

  if (
    !url.startsWith('http://') &&
    !url.startsWith('https://')
  ) {
    return;
  }

  const key = cacheKey(url);

  // Prevent duplicate scans
  if (activeScans.has(tabId)) {
    return;
  }

  const existing =
    recentScans.get(key);

  if (
    existing &&
    !force &&
    Date.now() - existing.timestamp <
      SCAN_DEBOUNCE_MS
  ) {
    return;
  }

  activeScans.set(tabId, true);

  updateBadge('...', '#f59e0b');

  try {

    const settings =
      await getSettings();

    const backendUrl =
      settings.backend_url;

    sessionPageCount++;

    await chrome.storage.local.set({
      session_page_count:
        sessionPageCount,
    });

    console.log(
      '[DarkGuard] Starting scan:',
      url
    );

    // ─────────────────────────
    // Backend request
    // ─────────────────────────

    const response = await fetch(
      `${backendUrl}/api/v1/scan`,
      {
        method: 'POST',

        headers: {
          'Content-Type':
            'application/json',
        },

        body: JSON.stringify({
          url,
          session_id:
            currentSessionId,
        }),
      }
    );

    if (!response.ok) {

      throw new Error(
        `Backend scan failed: ${response.status}`
      );
    }

    const result =
      await response.json();

    console.log(
      '[DarkGuard] Scan result:',
      result
    );

    // ─────────────────────────
    // Cache result
    // ─────────────────────────

    const cachedResult = {
      result,
      timestamp: Date.now(),
      url,
    };

    recentScans.set(
      key,
      cachedResult,
    );

    // ─────────────────────────
    // Store history
    // ─────────────────────────

    await appendHistory(result, url);

    // ─────────────────────────
    // Badge update
    // ─────────────────────────

    updateResultBadge(result);

    // ─────────────────────────
    // Highlight instructions
    // ─────────────────────────

    const patterns =
      result.all_detected_patterns ||
      [];

    const highlightPayload =
      buildHighlightPayload(patterns);

    try {

      await chrome.tabs.sendMessage(
        tabId,
        {
          type:
            'HIGHLIGHT_ELEMENTS',
          patterns:
            highlightPayload,
        }
      );

      console.log(
        '[DarkGuard] Highlight instructions sent'
      );

    } catch (err) {

      console.warn(
        '[DarkGuard] Highlight send failed:',
        err
      );
    }

    // ─────────────────────────
    // Prevention patches
    // ─────────────────────────

    const patches =
      result?.prevention
        ?.patch_instructions || [];

    if (patches.length) {

      try {

        await chrome.tabs.sendMessage(
          tabId,
          {
            type: 'APPLY_PATCHES',
            patches,
          }
        );

        console.log(
          '[DarkGuard] Prevention patches sent:',
          patches.length
        );

      } catch (err) {

        console.error(
          '[DarkGuard] Failed sending patches:',
          err
        );
      }
    }

    // ─────────────────────────
    // Notification
    // ─────────────────────────

    if (
      settings.notifications &&
      (result.total_detected || 0) > 0
    ) {

      chrome.notifications.create({
        type: 'basic',

        iconUrl:
          'icons/icon128.png',

        title:
          'Dark Guard Warning',

        message:
          `${result.total_detected} dark pattern(s) detected on this page.`,
      });
    }

  } catch (err) {

    console.error(
      '[DarkGuard] Scan failed:',
      err
    );

    recentScans.set(
      key,
      {
        error: String(err),
        timestamp: Date.now(),
        url,
      }
    );

    updateBadge('ERR', '#dc2626');

  } finally {

    activeScans.delete(tabId);
  }
}

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────

function buildHighlightPayload(
  patterns
) {

  const output = [];

  patterns.forEach(pattern => {

    const evidence =
      pattern.evidence || [];

    evidence.forEach(ev => {

      if (
        ev.selector &&
        pattern.detected
      ) {

        output.push({
          selector:
            ev.selector,

          pattern_code:
            pattern.pattern_code,

          pattern_name:
            pattern.pattern_name,

          confidence:
            pattern.confidence || 0,
        });
      }
    });
  });

  return output;
}

async function appendHistory(
  result,
  url
) {

  const storage =
    await chrome.storage.local.get(
      'scan_history'
    );

  const history =
    storage.scan_history || [];

  history.unshift({
    timestamp: Date.now(),

    url,

    total_detected:
      result.total_detected || 0,

    severity_label:
      result
        .overall_severity_label ||
      'none',

    all_detected_patterns:
      result
        .all_detected_patterns || [],
  });

  // Keep only latest 50
  const trimmed =
    history.slice(0, 50);

  await chrome.storage.local.set({
    scan_history: trimmed,
  });
}

async function getSettings() {

  const storage =
    await chrome.storage.local.get(
      'settings'
    );

  return {
    ...DEFAULT_SETTINGS,
    ...(storage.settings || {}),
  };
}

function updateResultBadge(
  result
) {

  const count =
    result.total_detected || 0;

  if (count === 0) {

    updateBadge('✓', '#16a34a');

    return;
  }

  if (count >= 5) {

    updateBadge(
      String(count),
      '#dc2626'
    );

    return;
  }

  updateBadge(
    String(count),
    '#ea580c'
  );
}

function updateBadge(
  text,
  color
) {

  chrome.action.setBadgeText({
    text,
  });

  chrome.action.setBadgeBackgroundColor({
    color,
  });
}

function cacheKey(url) {

  try {

    const parsed =
      new URL(url);

    return (
      parsed.origin +
      parsed.pathname
    );

  } catch {

    return url;
  }
}