/**
 * content.js — Dark Guard AI Content Script
 *
 * Responsibilities:
 *   1. Detect page loads + SPA navigations
 *   2. Receive highlight instructions
 *   3. Receive prevention patch instructions
 *   4. Apply live DOM mitigation
 */

'use strict';

console.log('[DarkGuard] content.js loaded');

// ─────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────

let lastReportedUrl = '';

const activeTooltips = [];
const activePatches = [];

// ─────────────────────────────────────────────────────────────
// PAGE LOAD DETECTION
// ─────────────────────────────────────────────────────────────

function notifyPageLoad(url) {
  if (!url || url === lastReportedUrl) {
    return;
  }

  if (
    !url.startsWith('http://') &&
    !url.startsWith('https://')
  ) {
    return;
  }

  lastReportedUrl = url;

  clearHighlights();
  clearPatches();

  try {
    chrome.runtime.sendMessage(
      {
        type: 'PAGE_LOADED',
        url,
      },
      () => {
        void chrome.runtime.lastError;
      }
    );
  } catch {
    // Ignore
  }
}

// Initial load
if (
  document.readyState === 'complete' ||
  document.readyState === 'interactive'
) {
  notifyPageLoad(window.location.href);
} else {
  window.addEventListener(
    'DOMContentLoaded',
    () => notifyPageLoad(window.location.href)
  );
}

// Full page load fallback
window.addEventListener(
  'load',
  () => notifyPageLoad(window.location.href)
);

// ─────────────────────────────────────────────────────────────
// SPA NAVIGATION DETECTION
// ─────────────────────────────────────────────────────────────

const urlObserver = new MutationObserver(() => {
  const currentUrl = window.location.href;

  if (currentUrl !== lastReportedUrl) {
    notifyPageLoad(currentUrl);
  }
});

urlObserver.observe(document.documentElement, {
  childList: true,
  subtree: true,
});

window.addEventListener(
  'popstate',
  () => notifyPageLoad(window.location.href)
);

window.addEventListener(
  'hashchange',
  () => notifyPageLoad(window.location.href)
);

// Patch history API
(function patchHistory() {
  const push = history.pushState.bind(history);
  const replace = history.replaceState.bind(history);

  history.pushState = function (...args) {
    push(...args);

    setTimeout(() => {
      notifyPageLoad(window.location.href);
    }, 150);
  };

  history.replaceState = function (...args) {
    replace(...args);

    setTimeout(() => {
      notifyPageLoad(window.location.href);
    }, 150);
  };
})();

// ─────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message) => {

  console.log(
    '[DarkGuard] Message received:',
    message.type
  );

  // ─────────────────────────────
  // Highlight detections
  // ─────────────────────────────

  if (message.type === 'HIGHLIGHT_ELEMENTS') {
    clearHighlights();

    for (const item of (message.patterns || [])) {
      highlightElement(
        item.selector,
        item.pattern_code,
        item.pattern_name,
        item.confidence
      );
    }
  }

  // ─────────────────────────────
  // Apply prevention patches
  // ─────────────────────────────

  if (message.type === 'APPLY_PATCHES') {

    console.log(
      '[DarkGuard] Applying patches:',
      message.patches
    );

    clearPatches();

    for (const patch of (message.patches || [])) {
      applyPatch(patch);
    }
  }
});

// ─────────────────────────────────────────────────────────────
// HIGHLIGHTING
// ─────────────────────────────────────────────────────────────

function clearHighlights() {
  activeTooltips.forEach(el => el.remove());

  activeTooltips.length = 0;

  document
    .querySelectorAll('[data-darkguard-code]')
    .forEach(el => {
      el.style.outline = '';
      el.style.outlineOffset = '';

      el.removeAttribute('data-darkguard-code');
    });
}

function highlightElement(
  selector,
  patternCode,
  patternName,
  confidence
) {
  let elements;

  try {
    elements =
      document.querySelectorAll(selector);
  } catch {
    return;
  }

  if (!elements.length) {
    return;
  }

  const color = patternColor(patternCode);

  elements.forEach(el => {

    el.style.outline =
      `2px solid ${color}`;

    el.style.outlineOffset = '2px';

    el.setAttribute(
      'data-darkguard-code',
      patternCode
    );

    const tooltip =
      document.createElement('div');

    tooltip.style.cssText = `
      position: fixed;
      background: #1e293b;
      color: #f1f5f9;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      z-index: 2147483647;
      pointer-events: none;
      display: none;
      max-width: 280px;
      border-left: 3px solid ${color};
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
    `;

    tooltip.innerHTML = `
      <strong style="color:${color}">
        ${patternCode}
      </strong>
      — ${patternName}
      <br>
      <span style="font-size:11px;color:#94a3b8">
        Confidence:
        ${Math.round(confidence * 100)}%
      </span>
    `;

    document.body.appendChild(tooltip);

    activeTooltips.push(tooltip);

    el.addEventListener('mouseenter', () => {
      const rect =
        el.getBoundingClientRect();

      tooltip.style.display = 'block';

      tooltip.style.left =
        `${Math.min(
          rect.left,
          window.innerWidth - 290
        )}px`;

      tooltip.style.top =
        `${Math.min(
          rect.bottom + 6,
          window.innerHeight - 80
        )}px`;
    });

    el.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
    });
  });
}

function patternColor(code) {
  const critical =
    new Set(['DP08', 'DP11']);

  const high =
    new Set(['DP06', 'DP07', 'DP13']);

  const medium =
    new Set([
      'DP01',
      'DP02',
      'DP04',
      'DP05',
      'DP10',
      'DP12',
    ]);

  if (critical.has(code)) {
    return '#dc2626';
  }

  if (high.has(code)) {
    return '#ea580c';
  }

  if (medium.has(code)) {
    return '#d97706';
  }

  return '#ca8a04';
}

// ─────────────────────────────────────────────────────────────
// PATCH ENGINE
// ─────────────────────────────────────────────────────────────

function clearPatches() {
  activePatches.forEach(el => {
    try {
      el.remove();
    } catch {}
  });

  activePatches.length = 0;
}

function applyPatch(patch) {

  console.log(
    '[DarkGuard] Applying patch:',
    patch.action,
    patch
  );

  const selector =
    patch.css_selector || 'body';

  let elements = [];

  try {
    elements =
      document.querySelectorAll(selector);
  } catch {
    return;
  }

  console.log(
    '[DarkGuard] Resolved elements:',
    elements.length,
    selector
  );

  if (!elements.length) {
    return;
  }

  elements.forEach(el => {

    try {

      switch (patch.action) {

        // ─────────────────────────
        // REPLACE TEXT
        // ─────────────────────────

        case 'replace_text': {

          const newText =
            patch.payload?.new_text;

          if (newText !== undefined) {
            el.textContent = newText;
          }

          break;
        }

        // ─────────────────────────
        // INJECT ELEMENT
        // ─────────────────────────

        case 'inject_element': {

          const html =
            patch.payload?.html || '';

          const position =
            patch.payload?.position ||
            'append';

          const wrapper =
            document.createElement('div');

          wrapper.innerHTML = html;

          const node =
            wrapper.firstElementChild;

          if (!node) {
            return;
          }

          node.setAttribute(
            'data-darkguard-patch',
            '1'
          );

          switch (position) {

            case 'before':
              el.parentNode?.insertBefore(
                node,
                el
              );
              break;

            case 'after':
              el.parentNode?.insertBefore(
                node,
                el.nextSibling
              );
              break;

            case 'prepend':
              el.prepend(node);
              break;

            case 'append':
            default:
              el.append(node);
              break;
          }

          activePatches.push(node);

          break;
        }

        // ─────────────────────────
        // ADD CLASS
        // ─────────────────────────

        case 'add_class': {

          const classes =
            patch.payload?.classes || [];

          classes.forEach(cls => {
            el.classList.add(cls);
          });

          if (
            patch.payload?.style_override
          ) {
            el.style.cssText +=
              ';' +
              patch.payload.style_override;
          }

          break;
        }

        // ─────────────────────────
        // ADD BADGE
        // ─────────────────────────

        case 'add_badge': {

          const badge =
            document.createElement('span');

          badge.setAttribute(
            'data-darkguard-badge',
            '1'
          );

          badge.textContent =
            patch.payload?.label || '⚠';

          badge.title =
            patch.payload?.title || '';

          badge.style.cssText = `
            background:
              ${patch.payload?.bg_color || '#f59e0b'};
            color:
              ${patch.payload?.color || '#fff'};
            display:inline-block;
            padding:2px 7px;
            border-radius:3px;
            font-size:11px;
            font-weight:600;
            margin-left:6px;
            vertical-align:middle;
            box-shadow:
              0 1px 4px rgba(0,0,0,.3);
            z-index:2147483647;
          `;

          el.parentNode?.insertBefore(
            badge,
            el.nextSibling
          );

          activePatches.push(badge);

          break;
        }

        // ─────────────────────────
        // INTERCEPT CLICK
        // ─────────────────────────

        case 'intercept_click': {

          if (
            el.dataset.darkguardIntercepted
          ) {
            break;
          }

          el.dataset.darkguardIntercepted =
            '1';

          el.addEventListener(
            'click',
            e => {

              e.preventDefault();
              e.stopImmediatePropagation();

              const warning =
                patch.payload?.warning_message ||
                'Dark Guard detected a potentially deceptive action.';

              const proceed =
                confirm(
                  `${warning}\n\nContinue anyway?`
                );

              if (proceed) {
                delete el.dataset.darkguardIntercepted;

                el.click();

                el.dataset.darkguardIntercepted =
                  '1';
              }
            },
            true
          );

          break;
        }

        // ─────────────────────────
        // UNCHECK
        // ─────────────────────────

        case 'uncheck': {

          if (
            el.type === 'checkbox' ||
            el.type === 'radio'
          ) {
            el.checked = false;
          }

          break;
        }

        default:

          console.warn(
            '[DarkGuard] Unknown action:',
            patch.action
          );
      }

    } catch (err) {

      console.error(
        '[DarkGuard] Patch failed:',
        err,
        patch
      );
    }
  });
}