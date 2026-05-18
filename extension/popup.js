/**
 * popup.js — Dark Guard AI Popup
 *
 * Responsibilities:
 *  - Display scan results
 *  - Display prevention strategies
 *  - Render scan history
 *  - Manage settings
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

const PATTERN_CLASSIFICATIONS = {
  DP01: 'False Urgency',
  DP02: 'Confirm Shaming',
  DP03: 'Disguised Ads',
  DP04: 'Trick Question',
  DP05: 'Drip Pricing',
  DP06: 'Bait and Switch',
  DP07: 'Basket Sneaking',
  DP08: 'Subscription Trap',
  DP09: 'Nagging',
  DP10: 'SaaS Billing Manipulation',
  DP11: 'Malicious and Rogue UX',
  DP12: 'Interface Interference',
  DP13: 'Forced Action',
};

// ─────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────

document.addEventListener(
  'DOMContentLoaded',
  initPopup
);

async function initPopup() {

  console.log(
    '[DarkGuard] popup.js loaded'
  );

  setupTabs();
  setupActionBar();
  setupSettings();
  setupHistory();

  const [tab] =
    await chrome.tabs.query({
      active: true,
      currentWindow: true,
    });

  if (!tab) {
    return;
  }

  displayUrl(tab.url);

  await loadSessionInfo();

  const status =
    await sendToBackground({
      type: 'GET_STATUS',
      tabId: tab.id,
    });

  if (status?.scanning) {

    showState('loading');

    pollForResult(
      tab.url,
      tab.id
    );

    return;
  }

  const cached =
    await sendToBackground({
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

  document
    .querySelectorAll('.tab-btn')
    .forEach(btn => {

      btn.addEventListener(
        'click',
        () => {

          const target =
            btn.dataset.tab;

          document
            .querySelectorAll('.tab-btn')
            .forEach(b =>
              b.classList.remove(
                'active'
              )
            );

          document
            .querySelectorAll('.tab-panel')
            .forEach(panel => {
              panel.hidden = true;
            });

          btn.classList.add(
            'active'
          );

          const panel =
            document.getElementById(
              `tab-${target}`
            );

          if (panel) {
            panel.hidden = false;
          }

          if (target === 'history') {
            loadHistory();
          }
        }
      );
    });
}

// ─────────────────────────────────────────────────────────────
// ACTIONS
// ─────────────────────────────────────────────────────────────

function setupActionBar() {

  const scanBtn =
    document.getElementById(
      'btn-scan'
    );

  if (scanBtn) {

    scanBtn.addEventListener(
      'click',
      async () => {

        const [tab] =
          await chrome.tabs.query({
            active: true,
            currentWindow: true,
          });

        if (!tab?.url) {
          return;
        }

        showState('loading');

        sendToBackground({
          type: 'MANUAL_SCAN',
          url: tab.url,
          tabId: tab.id,
        });

        pollForResult(
          tab.url,
          tab.id
        );
      }
    );
  }

  const exportBtn =
    document.getElementById(
      'btn-export'
    );

  if (exportBtn) {

    exportBtn.addEventListener(
      'click',
      async () => {

        const [tab] =
          await chrome.tabs.query({
            active: true,
            currentWindow: true,
          });

        if (!tab?.url) {
          return;
        }

        const cached =
          await sendToBackground({
            type:
              'GET_SCAN_RESULT',
            url: tab.url,
          });

        if (!cached?.result) {
          return;
        }

        const blob =
          new Blob(
            [
              JSON.stringify(
                cached.result,
                null,
                2
              ),
            ],
            {
              type:
                'application/json',
            }
          );

        const downloadUrl =
          URL.createObjectURL(blob);

        const a =
          document.createElement('a');

        a.href = downloadUrl;

        a.download =
          `darkguard-${slugify(tab.url)}.json`;

        a.click();

        URL.revokeObjectURL(
          downloadUrl
        );
      }
    );
  }
}

// ─────────────────────────────────────────────────────────────
// POLLING
// ─────────────────────────────────────────────────────────────

function pollForResult(
  url,
  tabId
) {

  let attempts = 0;

  const interval =
    setInterval(async () => {

      attempts++;

      const status =
        await sendToBackground({
          type: 'GET_STATUS',
          tabId,
        });

      if (!status?.scanning) {

        clearInterval(interval);

        const cached =
          await sendToBackground({
            type:
              'GET_SCAN_RESULT',
            url,
          });

        if (cached) {
          renderCached(cached);
        } else {

          showState('error');

          const err =
            document.getElementById(
              'error-message'
            );

          if (err) {
            err.textContent =
              'Scan finished but no result found.';
          }
        }

        return;
      }

      if (attempts > 40) {

        clearInterval(interval);

        showState('error');

        const err =
          document.getElementById(
            'error-message'
          );

        if (err) {
          err.textContent =
            'Scan timed out.';
        }
      }

    }, 1500);
}

// ─────────────────────────────────────────────────────────────
// RESULT RENDERING
// ─────────────────────────────────────────────────────────────

function renderCached(
  cached
) {

  if (cached.error) {

    showState('error');

    const err =
      document.getElementById(
        'error-message'
      );

    if (err) {
      err.textContent =
        cached.error;
    }

    return;
  }

  const result =
    cached.result;

  window.latestResult =
    result;

  if (!result) {

    showState('error');

    return;
  }

  if (
    (result.total_detected || 0)
    === 0
  ) {

    showState('clean');

    const clean =
      document.getElementById(
        'clean-summary'
      );

    if (clean) {
      clean.textContent =
        result.synthesis_summary ||
        'No dark patterns detected.';
    }

    return;
  }

  showState('results');

  renderResults(result);
}

function renderResults(
  result
) {

  const patterns =
    result
      .all_detected_patterns ||
    [];

  const countEl =
    document.getElementById(
      'severity-count'
    );

  if (countEl) {
    countEl.textContent =
      result.total_detected ||
      patterns.length ||
      0;
  }

  const sevChip =
    document.getElementById(
      'severity-chip'
    );

  const severity =
    result
      .behavioral_severity_label ||
    'none';

  if (sevChip) {

    sevChip.textContent =
      SEVERITY_LABELS[
        severity
      ] || severity;

    sevChip.dataset.sev =
      severity;
  }

  renderPatterns(
    patterns,
    result.prevention
  );

  setMetaChip(
    'meta-page-type',
    `📄 ${
      result.page_type ||
      'UNKNOWN'
    }`
  );

  setMetaChip(
    'meta-duration',
    `⏱ ${(
      (
        result.total_duration_ms ||
        0
      ) / 1000
    ).toFixed(1)}s`
  );

  setMetaChip(
    'meta-iterations',
    '🔁 1 iteration'
  );

  const synth =
    document.getElementById(
      'synthesis-text'
    );

  const synthCard =
    document.getElementById(
      'synthesis-card'
    );

  if (
    synth &&
    synthCard &&
    result.synthesis_summary
  ) {

    synth.textContent =
      result.synthesis_summary;

    synthCard.hidden = false;
  }

  const exportBtn =
    document.getElementById(
      'btn-export'
    );

  if (exportBtn) {
    exportBtn.hidden = false;
  }
}

// ─────────────────────────────────────────────────────────────
// PATTERN RENDERING
// ─────────────────────────────────────────────────────────────

function renderPatterns(
  patterns,
  prevention
) {

  const list =
    document.getElementById(
      'pattern-list'
    );

  if (!list) {
    return;
  }

  list.innerHTML = '';

  patterns =
    (patterns || [])
      .filter(p => p.detected);

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
      PATTERN_SEVERITY_MAP[
        p.pattern_code
      ] || 'medium';

    const conf =
      Math.round(
        Number(
          p.confidence || 0
        ) * 100
      );

    const item =
      document.createElement(
        'div'
      );

    item.className =
      'pattern-item';

    const header =
      document.createElement(
        'div'
      );

    header.className =
      'pattern-header';

    header.innerHTML = `
      <span class="pattern-code-badge sev-${sev}">
        ${escHtml(
          p.pattern_code ||
          'DP'
        )}
      </span>

      <span class="pattern-name">
        ${escHtml(
          p.pattern_name ||
          p.pattern_code
        )}
      </span>

      <span class="pattern-confidence">
        ${
          isNaN(conf)
            ? 0
            : conf
        }%
      </span>

      <span class="pattern-expand-icon">
        ▼
      </span>
    `;

    const body =
      document.createElement(
        'div'
      );

    body.className =
      'pattern-body';

    // DETECTED BY

    const by =
      document.createElement(
        'p'
      );

    by.className =
      'pattern-detected-by';

    by.innerHTML = `
      <strong>Detected By:</strong>
      ${
        Array.isArray(
          p.detected_by
        )
          ? p.detected_by.join(
              ', '
            )
          : (
              p.detected_by ||
              'Unknown'
            )
      }
    `;

    body.appendChild(by);

    // CLASSIFICATION

    const classification =
      document.createElement(
        'div'
      );

    classification.className =
      'dg-classification';

    classification.innerHTML = `
      <strong>Classification:</strong>
      ${
        PATTERN_CLASSIFICATIONS[
          p.pattern_code
        ] || 'Dark Pattern'
      }
    `;

    body.appendChild(
      classification
    );

    // EXPLANATION SECTION

    const evidence =
      (
        p.evidence || []
      ).filter(
        e => e.text || e.reason
      );

    if (evidence.length) {

      const explainSection =
        document.createElement(
          'div'
        );

      explainSection.className =
        'dg-explanation-section';

      explainSection.innerHTML = `
        <div class="dg-section-title">
          Why This Was Detected
        </div>
      `;

      evidence
        .slice(0, 5)
        .forEach(ev => {

          const evEl =
            document.createElement(
              'div'
            );

          evEl.className =
            'dg-evidence-item';

          evEl.innerHTML = `

            ${
              ev.text ? `
                <div class="dg-evidence-text">
                  "${escHtml(
                    ev.text
                  )}"
                </div>
              ` : ''
            }

            ${
              ev.reason ? `
                <div class="dg-evidence-reason">
                  ${escHtml(
                    ev.reason
                  )}
                </div>
              ` : ''
            }

            ${
              ev.location ? `
                <div class="dg-evidence-location">
                  📍 ${escHtml(
                    ev.location
                  )}
                </div>
              ` : ''
            }
          `;

          explainSection.appendChild(
            evEl
          );
        });

      body.appendChild(
        explainSection
      );
    }

    // PREVENTION

    const related =
      (
        prevention
          ?.patch_instructions ||
        []
      ).filter(
        patch =>
          patch.pattern_code ===
          p.pattern_code
      );

    if (related.length) {

      const section =
        document.createElement(
          'div'
        );

      section.className =
        'prevention-section';

      section.innerHTML = `
        <div class="prevention-header">
          🛡 Prevention
        </div>
      `;

      related.forEach(patch => {

        const patchEl =
          document.createElement(
            'div'
          );

        patchEl.className =
          'prevention-item';

        patchEl.innerHTML = `
          <div class="prevention-action">
            ${escHtml(
              patch.action ||
              'PATCH'
            )}
          </div>

          <div class="prevention-description">
            ${escHtml(
              patch.description ||
              'Dark Guard mitigation applied.'
            )}
          </div>
        `;

        section.appendChild(
          patchEl
        );
      });

      body.appendChild(
        section
      );
    }

    header.addEventListener(
      'click',
      () => {
        item.classList.toggle(
          'expanded'
        );
      }
    );

    item.appendChild(header);
    item.appendChild(body);

    list.appendChild(item);
  });
}

// ─────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────

function showState(name) {

  [
    'idle',
    'loading',
    'results',
    'clean',
    'error',
  ].forEach(state => {

    const el =
      document.getElementById(
        `state-${state}`
      );

    if (el) {
      el.hidden =
        state !== name;
    }
  });
}

// ─────────────────────────────────────────────────────────────
// HISTORY
// ─────────────────────────────────────────────────────────────

function setupHistory() {

  const clearBtn =
    document.getElementById(
      'btn-clear-history'
    );

  if (!clearBtn) {
    return;
  }

  clearBtn.addEventListener(
    'click',
    async () => {

      await chrome.storage.local.set({
        scan_history: [],
      });

      loadHistory();
    }
  );
}

async function loadHistory() {

  const stored =
    await chrome.storage.local.get(
      'scan_history'
    );

  const history =
    stored.scan_history || [];

  const list =
    document.getElementById(
      'history-list'
    );

  if (!list) {
    return;
  }

  list.innerHTML = '';

  if (!history.length) {

    list.innerHTML = `
      <div class="empty-state">
        No history yet.
      </div>
    `;

    return;
  }

  history.forEach(entry => {

    const item =
      document.createElement(
        'div'
      );

    item.className =
      'history-item';

    item.innerHTML = `
      <div class="history-url">
        ${escHtml(
          safeDomain(
            entry.url
          )
        )}
      </div>

      <div class="history-meta">
        ${
          entry.total_detected
        } pattern(s)
      </div>
    `;

    list.appendChild(item);
  });
}

// ─────────────────────────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────────────────────────

function setupSettings() {
  // Placeholder
}

// ─────────────────────────────────────────────────────────────
// SESSION INFO
// ─────────────────────────────────────────────────────────────

async function loadSessionInfo() {

  const stored =
    await chrome.storage.local.get([
      'session_id',
      'session_page_count',
    ]);

  const sid =
    stored.session_id ||
    '—';

  const count =
    stored.session_page_count ||
    0;

  const sidEl =
    document.getElementById(
      'session-id-display'
    );

  const countEl =
    document.getElementById(
      'session-pages-display'
    );

  if (sidEl) {

    sidEl.textContent =
      sid.slice(0, 8) + '…';
  }

  if (countEl) {

    countEl.textContent =
      count;
  }
}

// ─────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────

function sendToBackground(
  message
) {

  return new Promise(resolve => {

    chrome.runtime.sendMessage(
      message,
      response => {

        if (
          chrome.runtime
            .lastError
        ) {

          resolve(null);

        } else {

          resolve(response);
        }
      }
    );
  });
}

function displayUrl(url) {

  const el =
    document.getElementById(
      'current-url'
    );

  if (!el || !url) {
    return;
  }

  try {

    const parsed =
      new URL(url);

    el.textContent =
      parsed.hostname +
      (
        parsed.pathname !== '/'
          ? parsed.pathname
          : ''
      );

  } catch {

    el.textContent =
      url.slice(0, 40);
  }
}

function setMetaChip(
  id,
  text
) {

  const el =
    document.getElementById(id);

  if (el) {
    el.textContent = text;
  }
}

function escHtml(str) {

  if (!str) {
    return '';
  }

  return String(str)
    .replace(
      /&/g,
      '&amp;'
    )
    .replace(
      /</g,
      '&lt;'
    )
    .replace(
      />/g,
      '&gt;'
    )
    .replace(
      /"/g,
      '&quot;'
    );
}

function slugify(url) {

  try {

    return new URL(url)
      .hostname
      .replace(
        /\./g,
        '-'
      );

  } catch {

    return 'page';
  }
}

function safeDomain(url) {

  try {

    return new URL(url)
      .hostname;

  } catch {

    return url || '—';
  }
}