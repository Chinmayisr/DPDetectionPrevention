
/**
 * content.js
 *
 * Dark Guard AI
 *
 * Handles:
 * - DOM scanning hooks
 * - prevention patch execution
 * - live UI mitigation
 * - overlay highlighting
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// GLOBAL STATE
// ─────────────────────────────────────────────────────────────

window.__darkGuardAppliedPatches = new Set();
window.__darkGuardLatestResult = null;

// ─────────────────────────────────────────────────────────────
// MESSAGE LISTENER
// ─────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  try {
    switch (message.type) {

      // ─────────────────────────────
      // APPLY SCAN RESULT
      // ─────────────────────────────

      case 'APPLY_SCAN_RESULT': {
        const result = message.result;

        if (!result) {
          sendResponse({ ok: false });
          return true;
        }

        window.__darkGuardLatestResult = result;

        // Highlight detections
        renderDetectionHighlights(result);

        // Execute prevention patches
        applyPreventionStrategies(result.prevention);

        // Start observer
        initializeMutationObserver(result.prevention);

        sendResponse({ ok: true });

        return true;
      }

      // ─────────────────────────────
      // CLEAR PATCHES
      // ─────────────────────────────

      case 'CLEAR_PATCHES': {
        clearDarkGuardArtifacts();

        sendResponse({ ok: true });

        return true;
      }
    }
  } catch (err) {
    console.error('[DarkGuard] content.js error:', err);

    sendResponse({
      ok: false,
      error: String(err),
    });
  }

  return true;
});

// ─────────────────────────────────────────────────────────────
// PREVENTION ENGINE
// ─────────────────────────────────────────────────────────────

function applyPreventionStrategies(prevention) {
  if (!prevention?.patch_instructions) {
    return;
  }

  prevention.patch_instructions
    .sort((a, b) => (a.priority || 0) - (b.priority || 0))
    .forEach(patch => {
      try {
        executePatch(patch);
      } catch (err) {
        console.error(
          '[DarkGuard] Prevention patch failed:',
          err,
          patch,
        );
      }
    });
}

function executePatch(patch) {
  const selector = patch.css_selector || 'body';

  const elements = document.querySelectorAll(selector);

  if (!elements.length) {
    return;
  }

  elements.forEach(el => {
    const patchKey = `${patch.action}:${selector}:${patch.description}`;

    if (window.__darkGuardAppliedPatches.has(patchKey)) {
      return;
    }

    switch (patch.action) {

      // ─────────────────────────────
      // INJECT ELEMENT
      // ─────────────────────────────

      case 'inject_element': {
        const wrapper = document.createElement('div');

        wrapper.innerHTML = patch.payload?.html || '';

        const node = wrapper.firstElementChild;

        if (!node) return;

        node.classList.add('dg-generated-node');

        const position = patch.payload?.position || 'append';

        if (position === 'before') {
          el.prepend(node);
        } else if (position === 'prepend') {
          el.prepend(node);
        } else if (position === 'after') {
          el.append(node);
        } else {
          el.append(node);
        }

        break;
      }

      // ─────────────────────────────
      // ADD CLASS
      // ─────────────────────────────

      case 'add_class': {
        const classes = patch.payload?.classes || [];

        classes.forEach(cls => {
          el.classList.add(cls);
        });

        if (patch.payload?.style_override) {
          el.style.cssText += patch.payload.style_override;
        }

        break;
      }

      // ─────────────────────────────
      // ADD BADGE
      // ─────────────────────────────

      case 'add_badge': {
        const badge = document.createElement('span');

        badge.className = 'dg-generated-node dg-badge';

        badge.innerText = patch.payload?.label || 'NOTICE';

        badge.style.background =
          patch.payload?.bg_color || '#ff9800';

        badge.style.color =
          patch.payload?.color || '#fff';

        badge.style.fontSize = '11px';
        badge.style.fontWeight = '700';
        badge.style.padding = '2px 6px';
        badge.style.borderRadius = '4px';
        badge.style.marginRight = '6px';
        badge.style.display = 'inline-block';
        badge.style.zIndex = '999999';
        badge.style.position = 'relative';

        if (patch.payload?.title) {
          badge.title = patch.payload.title;
        }

        el.prepend(badge);

        break;
      }

      // ─────────────────────────────
      // HIDE ELEMENT
      // ─────────────────────────────

      case 'hide_element': {
        el.style.display = 'none';
        break;
      }

      // ─────────────────────────────
      // REPLACE TEXT
      // ─────────────────────────────

      case 'replace_text': {
        const replacement = patch.payload?.text;

        if (replacement) {
          el.textContent = replacement;
        }

        break;
      }

      default:
        console.warn(
          '[DarkGuard] Unknown prevention action:',
          patch.action,
        );
    }

    window.__darkGuardAppliedPatches.add(patchKey);
  });
}

// ─────────────────────────────────────────────────────────────
// DETECTION HIGHLIGHTING
// ─────────────────────────────────────────────────────────────

function renderDetectionHighlights(result) {
  const patterns =
    result?.all_detected_patterns || [];

  patterns.forEach(pattern => {
    (pattern.evidence || []).forEach(ev => {
      if (!ev.text) return;

      highlightText(ev.text);
    });
  });
}

function highlightText(text) {
  if (!text || text.length < 3) {
    return;
  }

  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
  );

  const matches = [];

  while (walker.nextNode()) {
    const node = walker.currentNode;

    if (
      node.textContent &&
      node.textContent.includes(text)
    ) {
      matches.push(node);
    }
  }

  matches.forEach(node => {
    const parent = node.parentElement;

    if (!parent) return;

    parent.classList.add('dg-highlight');
  });
}

// ─────────────────────────────────────────────────────────────
// MUTATION OBSERVER
// ─────────────────────────────────────────────────────────────

let darkGuardObserver = null;

function initializeMutationObserver(prevention) {
  if (darkGuardObserver) {
    return;
  }

  darkGuardObserver = new MutationObserver(() => {
    applyPreventionStrategies(prevention);
  });

  darkGuardObserver.observe(document.body, {
    childList: true,
    subtree: true,
  });
}

// ─────────────────────────────────────────────────────────────
// CLEANUP
// ─────────────────────────────────────────────────────────────

function clearDarkGuardArtifacts() {
  document
    .querySelectorAll('.dg-generated-node')
    .forEach(el => el.remove());

  document
    .querySelectorAll('.dg-highlight')
    .forEach(el => {
      el.classList.remove('dg-highlight');
    });

  window.__darkGuardAppliedPatches.clear();

  if (darkGuardObserver) {
    darkGuardObserver.disconnect();
    darkGuardObserver = null;
  }
}

// ─────────────────────────────────────────────────────────────
// GLOBAL STYLES
// ─────────────────────────────────────────────────────────────

(function injectDarkGuardStyles() {
  if (document.getElementById('darkguard-styles')) {
    return;
  }

  const style = document.createElement('style');

  style.id = 'darkguard-styles';

  style.textContent = `

    .dg-highlight {
      outline: 2px solid #ef4444 !important;
      outline-offset: 2px !important;
      transition: outline 0.2s ease;
    }

    .dg-option-parity {
      opacity: 1 !important;
      visibility: visible !important;
      font-size: 14px !important;
      padding: 8px 14px !important;
      border-radius: 6px !important;
      cursor: pointer !important;
    }

    .dg-amplify-close {
      min-width: 44px !important;
      min-height: 44px !important;
      font-size: 18px !important;
      background: #fff !important;
      border: 2px solid #111 !important;
      color: #111 !important;
      opacity: 1 !important;
      z-index: 999999 !important;
    }

    .dg-badge {
      font-family: sans-serif !important;
      line-height: 1.2 !important;
    }

  `;

  document.head.appendChild(style);
})();

// ─────────────────────────────────────────────────────────────
// STARTUP LOG
// ─────────────────────────────────────────────────────────────

console.log('[DarkGuard] content.js loaded');

