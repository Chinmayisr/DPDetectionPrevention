/**
 * content.js — Dark Guard AI Content Script
 *
 * Injected into every page. Responsibilities:
 *   1. Detect page loads and SPA navigations → notify background worker
 *   2. Listen for HIGHLIGHT_ELEMENTS → draw visual overlays on flagged elements
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────

let lastReportedUrl = '';
const activeTooltips = [];

// ─────────────────────────────────────────────────────────────
// PAGE LOAD DETECTION
// ─────────────────────────────────────────────────────────────

function notifyPageLoad(url) {
  if (!url || url === lastReportedUrl) return;
  // Skip chrome internal pages
  if (!url.startsWith('http://') && !url.startsWith('https://')) return;

  lastReportedUrl = url;
  clearHighlights();

  chrome.runtime.sendMessage({ type: 'PAGE_LOADED', url }).catch(() => {
    // Background service worker may be temporarily inactive — ignore
  });
}

// Initial load
if (document.readyState === 'complete' || document.readyState === 'interactive') {
  notifyPageLoad(window.location.href);
} else {
  window.addEventListener('DOMContentLoaded', () => notifyPageLoad(window.location.href));
}

// Full page load (fallback)
window.addEventListener('load', () => notifyPageLoad(window.location.href));

// ── SPA Navigation Detection ──────────────────────────────────

// MutationObserver: catches URL changes driven by React Router / Next.js / Vue Router
const _urlObserver = new MutationObserver(() => {
  const currentUrl = window.location.href;
  if (currentUrl !== lastReportedUrl) notifyPageLoad(currentUrl);
});
_urlObserver.observe(document.documentElement, { childList: true, subtree: true });

// Browser history API
window.addEventListener('popstate',   () => notifyPageLoad(window.location.href));
window.addEventListener('hashchange', () => notifyPageLoad(window.location.href));

// Patch pushState / replaceState for frameworks that don't fire popstate
(function patchHistory() {
  const _push    = history.pushState.bind(history);
  const _replace = history.replaceState.bind(history);

  history.pushState = function (...args) {
    _push(...args);
    setTimeout(() => notifyPageLoad(window.location.href), 150);
  };

  history.replaceState = function (...args) {
    _replace(...args);
    setTimeout(() => notifyPageLoad(window.location.href), 150);
  };
})();

// ─────────────────────────────────────────────────────────────
// DOM HIGHLIGHTING
// ─────────────────────────────────────────────────────────────

function clearHighlights() {
  // Remove tooltips
  activeTooltips.forEach(el => el.remove());
  activeTooltips.length = 0;

  // Remove outlines from flagged elements
  document.querySelectorAll('[data-darkguard-code]').forEach(el => {
    el.style.outline      = '';
    el.style.outlineOffset = '';
    el.removeAttribute('data-darkguard-code');
  });
}

function highlightElement(selector, patternCode, patternName, confidence) {
  let elements;
  try {
    elements = document.querySelectorAll(selector);
  } catch {
    return;   // Invalid CSS selector — skip
  }
  if (!elements.length) return;

  const color = patternColor(patternCode);

  elements.forEach(el => {
    // Outline
    el.style.outline       = `2px solid ${color}`;
    el.style.outlineOffset = '2px';
    el.setAttribute('data-darkguard-code', patternCode);

    // Tooltip element (created on demand)
    const tooltip = document.createElement('div');
    tooltip.setAttribute('data-darkguard-tooltip', '1');
    tooltip.style.cssText = [
      'position: fixed',
      'background: #1e293b',
      'color: #f1f5f9',
      'padding: 8px 12px',
      'border-radius: 6px',
      'font-size: 12px',
      'font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      'z-index: 2147483647',
      'pointer-events: none',
      'box-shadow: 0 4px 12px rgba(0,0,0,0.4)',
      `border-left: 3px solid ${color}`,
      'display: none',
      'max-width: 280px',
      'line-height: 1.5',
    ].join(';');
    tooltip.innerHTML =
      `<strong style="color:${color}">${patternCode}</strong> — ${patternName}<br>` +
      `<span style="color:#94a3b8;font-size:11px">Confidence: ${Math.round(confidence * 100)}%</span>`;

    document.body.appendChild(tooltip);
    activeTooltips.push(tooltip);

    el.addEventListener('mouseenter', () => {
      const rect = el.getBoundingClientRect();
      tooltip.style.display = 'block';
      tooltip.style.left    = `${Math.min(rect.left, window.innerWidth - 290)}px`;
      tooltip.style.top     = `${Math.min(rect.bottom + 6, window.innerHeight - 80)}px`;
    });

    el.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
    });
  });
}

function patternColor(code) {
  const critical = new Set(['DP08', 'DP11']);
  const high     = new Set(['DP06', 'DP07', 'DP13']);
  const medium   = new Set(['DP01', 'DP02', 'DP04', 'DP05', 'DP10', 'DP12']);

  if (critical.has(code)) return '#dc2626';
  if (high.has(code))     return '#ea580c';
  if (medium.has(code))   return '#d97706';
  return '#ca8a04';
}

// ─────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'HIGHLIGHT_ELEMENTS') {
    clearHighlights();
    for (const item of (message.patterns || [])) {
      highlightElement(item.selector, item.pattern_code, item.pattern_name, item.confidence);
    }
  }
});
