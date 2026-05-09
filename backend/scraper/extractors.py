"""
backend/scraper/extractors.py
─────────────────────────────────────────────────────────────────
All JavaScript extraction functions executed inside the browser
via page.evaluate().  Every function is self-contained so it can
run on any website regardless of framework.

Design rules:
  - Each function catches its own exceptions and returns empty
    arrays/objects rather than throwing — a single broken page
    element must never crash the whole extraction.
  - Functions are synchronous JS (no async/await) because
    page.evaluate() runs them in a synchronous context.
  - CSS selector generation is best-effort; falls back to tag+index.
"""
from __future__ import annotations


# ── CSS selector helper (injected as shared code) ─────────────

_CSS_SELECTOR_HELPER = """
function getCssSelector(el) {
    try {
        if (el.id) return '#' + CSS.escape(el.id);
        const parts = [];
        let current = el;
        while (current && current !== document.body) {
            let selector = current.tagName.toLowerCase();
            if (current.className && typeof current.className === 'string') {
                const classes = current.className.trim().split(/\s+/).slice(0, 2);
                if (classes.length) selector += '.' + classes.map(c => CSS.escape(c)).join('.');
            }
            const siblings = Array.from(current.parentElement?.children || [])
                .filter(s => s.tagName === current.tagName);
            if (siblings.length > 1) {
                const idx = siblings.indexOf(current) + 1;
                selector += ':nth-of-type(' + idx + ')';
            }
            parts.unshift(selector);
            current = current.parentElement;
            if (parts.length >= 4) break;
        }
        return parts.join(' > ');
    } catch(e) { return el.tagName.toLowerCase(); }
}
"""

# ── Bounding box helper ───────────────────────────────────────

_BBOX_HELPER = """
function getBbox(el) {
    try {
        const r = el.getBoundingClientRect();
        return { x: r.x, y: r.y, width: r.width, height: r.height };
    } catch(e) { return null; }
}
"""

# ── Computed style helper ─────────────────────────────────────

_STYLE_HELPER = """
function getComputedVal(el, prop) {
    try { return window.getComputedStyle(el).getPropertyValue(prop) || null; }
    catch(e) { return null; }
}
"""


# ─────────────────────────────────────────────────────────────
# 1. BUTTON EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_BUTTONS_JS = _CSS_SELECTOR_HELPER + _BBOX_HELPER + _STYLE_HELPER + """
(function extractButtons() {
    const results = [];
    const selectors = [
        'button',
        '[role="button"]',
        'input[type="submit"]',
        'input[type="button"]',
        'input[type="reset"]',
        'a.btn', 'a.button',
        '[class*="btn"]',
        '[class*="button"]',
        '[class*="cta"]',
    ];
    const seen = new WeakSet();
    const allEls = document.querySelectorAll(selectors.join(','));

    allEls.forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const text = (el.innerText || el.value || el.textContent || '').trim();
            const ariaLabel = el.getAttribute('aria-label') || null;
            const href = el.getAttribute('href') || null;

            // Detect if inside modal/overlay
            let ancestor = el.parentElement;
            let isInModal = false;
            let isInSticky = false;
            while (ancestor && ancestor !== document.body) {
                const pos = getComputedVal(ancestor, 'position');
                const zIdx = parseInt(getComputedVal(ancestor, 'z-index') || '0');
                if ((pos === 'fixed' || pos === 'sticky') && zIdx > 100) {
                    isInModal = true;
                }
                if (pos === 'sticky') isInSticky = true;
                ancestor = ancestor.parentElement;
            }

            // Is it a close button?
            const closeIndicators = ['close', 'dismiss', 'cancel', '×', '✕', '✖', 'x'];
            const textLower = (text + (ariaLabel || '')).toLowerCase();
            const isClose = closeIndicators.some(c => textLower.includes(c)) ||
                el.getAttribute('data-dismiss') !== null ||
                el.getAttribute('aria-label')?.toLowerCase().includes('close');

            // Data attributes
            const dataAttrs = {};
            Array.from(el.attributes)
                .filter(a => a.name.startsWith('data-'))
                .forEach(a => { dataAttrs[a.name] = a.value; });

            results.push({
                text,
                aria_label: ariaLabel,
                href,
                actual_href: href,
                domain_mismatch: false,
                redirect_chain: [],
                is_in_modal: isInModal,
                is_in_sticky: isInSticky,
                bg_color: getComputedVal(el, 'background-color'),
                text_color: getComputedVal(el, 'color'),
                font_size: getComputedVal(el, 'font-size'),
                css_selector: getCssSelector(el),
                bounding_box: getBbox(el),
                is_close_button: isClose,
                data_attributes: dataAttrs,
            });
        } catch(e) {}
    });
    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 2. FORM EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_FORMS_JS = _CSS_SELECTOR_HELPER + """
(function extractForms() {
    const results = [];
    const forms = document.querySelectorAll('form');

    // Also pick up standalone checkboxes outside forms (common dark pattern location)
    const standaloneCheckboxes = Array.from(
        document.querySelectorAll('input[type="checkbox"]')
    ).filter(cb => !cb.closest('form'));

    const processField = (el) => {
        const type = el.getAttribute('type') || el.tagName.toLowerCase();
        const name = el.getAttribute('name') || el.getAttribute('id') || null;

        // Find associated label
        let labelText = null;
        const id = el.getAttribute('id');
        if (id) {
            const label = document.querySelector('label[for="' + id + '"]');
            if (label) labelText = label.innerText.trim();
        }
        if (!labelText) {
            const parentLabel = el.closest('label');
            if (parentLabel) labelText = parentLabel.innerText.trim();
        }

        const isChecked = el.checked || false;
        // Determine if it's pre-checked by checking the default state via HTML attribute
        const isPreChecked = el.hasAttribute('checked') || el.defaultChecked || false;

        return {
            tag: el.tagName.toLowerCase(),
            input_type: type,
            name: name,
            label_text: labelText,
            placeholder: el.getAttribute('placeholder') || null,
            value: el.value || el.getAttribute('value') || null,
            is_checked: isChecked,
            is_pre_checked: isPreChecked,
            is_required: el.required || el.hasAttribute('required'),
            is_hidden: type === 'hidden' || el.style.display === 'none' ||
                       el.style.visibility === 'hidden',
            css_selector: getCssSelector(el),
        };
    };

    forms.forEach(form => {
        const fields = [];
        let hasHiddenConsent = false;
        let preCheckedCount = 0;

        form.querySelectorAll('input, select, textarea').forEach(el => {
            const field = processField(el);
            fields.push(field);
            if (field.is_hidden && field.value) hasHiddenConsent = true;
            if (field.input_type === 'checkbox' && field.is_pre_checked) preCheckedCount++;
        });

        results.push({
            form_id: form.getAttribute('id') || form.getAttribute('name') || null,
            action: form.getAttribute('action') || null,
            method: (form.getAttribute('method') || 'GET').toUpperCase(),
            fields,
            has_hidden_consent: hasHiddenConsent,
            pre_checked_count: preCheckedCount,
        });
    });

    // Standalone checkboxes as a synthetic form
    if (standaloneCheckboxes.length > 0) {
        const fields = standaloneCheckboxes.map(processField);
        const preCheckedCount = fields.filter(f => f.is_pre_checked).length;
        if (fields.length > 0) {
            results.push({
                form_id: '__standalone_checkboxes__',
                action: null,
                method: 'N/A',
                fields,
                has_hidden_consent: false,
                pre_checked_count: preCheckedCount,
            });
        }
    }

    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 3. PRICE EXTRACTOR  (3-layer strategy)
# ─────────────────────────────────────────────────────────────

EXTRACT_PRICES_JS = _CSS_SELECTOR_HELPER + _BBOX_HELPER + """
(function extractPrices() {
    const results = [];
    const seen = new WeakSet();

    // ── Layer 1: Schema.org structured data ──────────────────
    const schemaScripts = document.querySelectorAll(
        'script[type="application/ld+json"]'
    );
    schemaScripts.forEach(script => {
        try {
            const data = JSON.parse(script.textContent);
            const items = Array.isArray(data) ? data : [data];
            items.forEach(item => {
                const type = item['@type'];
                if (!type) return;
                const typeStr = Array.isArray(type) ? type.join(' ') : type;

                let price = null, currency = null, origPrice = null;

                if (typeStr.includes('Product') || typeStr.includes('Offer')) {
                    const offer = item.offers || item;
                    const offers = Array.isArray(offer) ? offer : [offer];
                    offers.forEach(o => {
                        if (o.price !== undefined) {
                            price = parseFloat(o.price);
                            currency = o.priceCurrency || null;
                        }
                    });
                    origPrice = item.highPrice ? parseFloat(item.highPrice) : null;
                }

                if (typeStr.includes('ShoppingCart') || typeStr.includes('Order')) {
                    const total = item.price || item.totalPrice;
                    if (total !== undefined) {
                        price = parseFloat(total);
                        currency = item.priceCurrency || null;
                    }
                }

                if (price !== null) {
                    results.push({
                        text: String(price),
                        amount: price,
                        currency,
                        original_price: origPrice,
                        context_before: null,
                        context_after: null,
                        location: 'schema_org',
                        css_selector: null,
                        bounding_box: null,
                        schema_sourced: true,
                    });
                }
            });
        } catch(e) {}
    });

    // ── Layer 2: Semantic DOM patterns ───────────────────────
    const PRICE_SELECTORS = [
        '[class*="price"]', '[class*="Price"]',
        '[class*="cost"]',  '[class*="Cost"]',
        '[class*="amount"]','[class*="Amount"]',
        '[class*="total"]', '[class*="Total"]',
        '[class*="subtotal"]',
        '[class*="sale-price"]', '[class*="regular-price"]',
        '[class*="offer-price"]', '[class*="deal-price"]',
        '[data-price]', '[data-original-price]', '[data-sale-price]',
        '[itemprop="price"]', '[itemprop="priceSpecification"]',
        '.price', '.cost', '.amount',
    ];

    const CURRENCY_REGEX = /[\$\£\€\₹\¥\₩\₺\₱\R\฿][\d,]+\.?\d*/;
    const NUMBER_WITH_CURRENCY = /(?:[\$\£\€\₹\¥\₩\₺\₱\฿])\s*[\d,]+(?:\.\d{1,2})?|[\d,]+(?:\.\d{1,2})?\s*(?:USD|EUR|GBP|INR|JPY)/g;

    const priceEls = document.querySelectorAll(PRICE_SELECTORS.join(','));
    priceEls.forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const text = (el.innerText || el.textContent || '').trim();
            if (!text || text.length > 50) return;

            const match = text.match(NUMBER_WITH_CURRENCY);
            if (!match && !el.getAttribute('data-price')) return;

            const rawAmount = el.getAttribute('data-price') ||
                              el.getAttribute('data-sale-price') ||
                              (match ? match[0].replace(/[^\d.]/g, '') : null);
            const origRaw = el.getAttribute('data-original-price') ||
                            el.getAttribute('data-regular-price');

            // Location detection
            let location = 'page';
            const path = el.closest('[class*="cart"]') ? 'cart_summary' :
                         el.closest('[class*="checkout"]') ? 'checkout_total' :
                         el.closest('[class*="product"]') ? 'product_section' :
                         el.closest('[class*="order"]') ? 'order_summary' : 'page';

            // Context siblings
            const prev = el.previousElementSibling?.innerText?.trim() || null;
            const next = el.nextElementSibling?.innerText?.trim() || null;

            results.push({
                text,
                amount: rawAmount ? parseFloat(rawAmount) : null,
                currency: null,
                original_price: origRaw ? parseFloat(origRaw) : null,
                context_before: prev,
                context_after: next,
                location: path,
                css_selector: getCssSelector(el),
                bounding_box: getBbox(el),
                schema_sourced: false,
            });
        } catch(e) {}
    });

    // ── Layer 3: Full-text currency regex sweep ───────────────
    const allTextNodes = [];
    const walker = document.createTreeWalker(
        document.body, NodeFilter.SHOW_TEXT, null
    );
    let node;
    while ((node = walker.nextNode())) {
        const txt = node.textContent.trim();
        if (CURRENCY_REGEX.test(txt) && txt.length < 30) {
            const parentEl = node.parentElement;
            if (parentEl && !seen.has(parentEl)) {
                seen.add(parentEl);
                const matches = txt.match(NUMBER_WITH_CURRENCY);
                if (matches) {
                    matches.forEach(m => {
                        const amount = parseFloat(m.replace(/[^\d.]/g, ''));
                        if (!isNaN(amount)) {
                            results.push({
                                text: txt,
                                amount,
                                currency: null,
                                original_price: null,
                                context_before: null,
                                context_after: null,
                                location: 'text_node',
                                css_selector: getCssSelector(parentEl),
                                bounding_box: getBbox(parentEl),
                                schema_sourced: false,
                            });
                        }
                    });
                }
            }
        }
    }

    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 4. SUPPLEMENTAL CHARGES EXTRACTOR  (cart/checkout)
# ─────────────────────────────────────────────────────────────

EXTRACT_SUPPLEMENTAL_CHARGES_JS = _CSS_SELECTOR_HELPER + """
(function extractSupplementalCharges() {
    const CHARGE_KEYWORDS = [
        'service fee', 'convenience fee', 'platform fee',
        'processing fee', 'handling fee', 'insurance',
        'protection plan', 'priority', 'shipping protection',
        'donation', 'tip', 'gratuity', 'surcharge',
        'booking fee', 'transaction fee',
    ];
    const results = [];
    const CURRENCY_RE = /[\$\£\€\₹\¥]?\s*[\d,]+\.?\d*/;

    document.querySelectorAll(
        '[class*="fee"], [class*="charge"], [class*="extra"], ' +
        '[class*="surcharge"], [class*="add-on"], [class*="addon"], ' +
        '[class*="upsell"], [class*="insurance"], [class*="protection"]'
    ).forEach(el => {
        try {
            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            if (!text) return;

            const isCharge = CHARGE_KEYWORDS.some(k => text.includes(k));
            if (!isCharge) return;

            const amountMatch = el.innerText.match(CURRENCY_RE);
            const amount = amountMatch ? parseFloat(amountMatch[0].replace(/[^\d.]/g, '')) : null;

            // Is it pre-selected (an opt-out hidden cost)?
            const checkbox = el.querySelector('input[type="checkbox"]');
            const isPreSelected = checkbox ? (checkbox.checked && checkbox.defaultChecked) : false;
            const isOptional = checkbox !== null;

            results.push({
                label: el.innerText.trim().split('\n')[0].slice(0, 100),
                amount,
                currency: null,
                is_pre_selected: isPreSelected,
                is_optional: isOptional,
                css_selector: null,
            });
        } catch(e) {}
    });

    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 5. OVERLAY DETECTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_OVERLAYS_JS = _CSS_SELECTOR_HELPER + _BBOX_HELPER + """
(function extractOverlays() {
    const results = [];
    const VW = window.innerWidth;
    const VH = window.innerHeight;

    document.querySelectorAll('*').forEach(el => {
        try {
            const style = window.getComputedStyle(el);
            const pos = style.getPropertyValue('position');
            const zIdx = parseInt(style.getPropertyValue('z-index') || '0');
            const display = style.getPropertyValue('display');
            const visibility = style.getPropertyValue('visibility');

            if ((pos !== 'fixed' && pos !== 'sticky') || zIdx < 50) return;
            if (display === 'none' || visibility === 'hidden') return;

            const text = (el.innerText || el.textContent || '').trim();
            if (!text || text.length < 5) return;

            const bbox = el.getBoundingClientRect();
            const coverage = (bbox.width * bbox.height) / (VW * VH);

            // Classify overlay type
            let overlayType;
            if (coverage > 0.15) {
                overlayType = 'modal';
            } else if (bbox.y < VH * 0.15) {
                overlayType = 'banner';
            } else if (bbox.y > VH * 0.75) {
                overlayType = 'banner';
            } else {
                overlayType = 'toast';
            }

            // Close button detection
            const closeKeywords = ['close', 'dismiss', '×', '✕', '✖', 'skip', 'no thanks'];
            const buttons = el.querySelectorAll('button, [role="button"], a');
            let hasClose = false;
            let closeProminent = false;
            buttons.forEach(btn => {
                const btnText = (btn.innerText || btn.getAttribute('aria-label') || '').toLowerCase();
                if (closeKeywords.some(k => btnText.includes(k))) {
                    hasClose = true;
                    const btnStyle = window.getComputedStyle(btn);
                    const size = parseFloat(btnStyle.fontSize);
                    closeProminent = size >= 14;
                }
            });

            // Pointer-events blocking
            const bgEl = document.querySelector('[class*="backdrop"], [class*="overlay"], [class*="mask"]');
            const blocks = bgEl ?
                window.getComputedStyle(bgEl).pointerEvents !== 'none' : false;

            results.push({
                overlay_type: overlayType,
                text: text.slice(0, 500),
                html: el.outerHTML.slice(0, 2000),
                trigger_delay_ms: 0,         // set by mutation observer
                appeared_autonomously: false, // set by mutation observer
                viewport_coverage_pct: parseFloat((coverage * 100).toFixed(2)),
                has_close_button: hasClose,
                close_button_prominent: closeProminent,
                blocks_interaction: blocks,
                css_selector: getCssSelector(el),
                bounding_box: { x: bbox.x, y: bbox.y, width: bbox.width, height: bbox.height },
                contains_form: el.querySelector('form, input') !== null,
                contains_cta: el.querySelector('button, [role="button"], a') !== null,
            });
        } catch(e) {}
    });

    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 6. TIMER EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_TIMERS_JS = _CSS_SELECTOR_HELPER + """
(function extractTimers() {
    const results = [];
    const TIMER_RE = /\\d{1,2}:\\d{2}(:\\d{2})?/;
    const COUNTDOWN_RE = /\\d+\\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?|days?)/i;

    // CSS class-based detection
    const timerSelectors = [
        '[class*="countdown"]', '[class*="timer"]', '[class*="clock"]',
        '[class*="expir"]', '[class*="limited"]', '[class*="hurry"]',
        '[data-countdown]', '[data-timer]', '[data-expiry]',
        '[id*="countdown"]', '[id*="timer"]',
    ];

    const seen = new WeakSet();

    document.querySelectorAll(timerSelectors.join(',')).forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const text = (el.innerText || el.textContent || '').trim();
            if (!text) return;
            const isCountdown = TIMER_RE.test(text) || COUNTDOWN_RE.test(text) ||
                                el.getAttribute('data-countdown') !== null;

            const context = el.parentElement?.innerText?.trim()?.slice(0, 200) || null;
            results.push({
                text: text.slice(0, 100),
                is_counting_down: isCountdown,
                css_selector: null,
                context,
            });
        } catch(e) {}
    });

    // Text-node sweep for countdown patterns
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
        const txt = node.textContent.trim();
        if ((TIMER_RE.test(txt) || COUNTDOWN_RE.test(txt)) && txt.length < 80) {
            const parent = node.parentElement;
            if (parent && !seen.has(parent)) {
                seen.add(parent);
                results.push({
                    text: txt,
                    is_counting_down: true,
                    css_selector: null,
                    context: parent.parentElement?.innerText?.trim()?.slice(0, 200) || null,
                });
            }
        }
    }

    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 7. HIDDEN ELEMENT EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_HIDDEN_ELEMENTS_JS = _CSS_SELECTOR_HELPER + """
(function extractHiddenElements() {
    const results = [];
    const seen = new WeakSet();

    document.querySelectorAll(
        'input[type="hidden"], [style*="display:none"], [style*="display: none"], ' +
        '[style*="visibility:hidden"], [style*="visibility: hidden"], ' +
        '[style*="opacity:0"], [style*="opacity: 0"]'
    ).forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            let reason = 'offscreen';
            const s = el.style;
            const type = el.getAttribute('type');

            if (type === 'hidden') reason = 'type_hidden';
            else if (s.display === 'none' || s.display?.includes('none')) reason = 'display:none';
            else if (s.visibility === 'hidden') reason = 'visibility:hidden';
            else if (s.opacity === '0') reason = 'opacity:0';

            results.push({
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || el.textContent || '').trim().slice(0, 200) || null,
                reason,
                is_form_field: ['INPUT','SELECT','TEXTAREA'].includes(el.tagName),
                name: el.getAttribute('name') || null,
                value: el.value || el.getAttribute('value') || null,
                css_selector: getCssSelector(el),
            });
        } catch(e) {}
    });

    // Detect off-screen positioned elements
    document.querySelectorAll('[style*="left:-"], [style*="top:-"], [style*="left: -"]').forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const r = el.getBoundingClientRect();
            if (r.x < -100 || r.y < -100) {
                results.push({
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || el.textContent || '').trim().slice(0, 200) || null,
                    reason: 'offscreen',
                    is_form_field: ['INPUT','SELECT','TEXTAREA'].includes(el.tagName),
                    name: el.getAttribute('name') || null,
                    value: el.value || el.getAttribute('value') || null,
                    css_selector: getCssSelector(el),
                });
            }
        } catch(e) {}
    });

    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 8. LINK / REDIRECT TRAP EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_LINKS_JS = _CSS_SELECTOR_HELPER + _BBOX_HELPER + """
(function extractLinks() {
    const results = [];
    const currentHost = window.location.hostname;

    document.querySelectorAll('a[href]').forEach(el => {
        try {
            const text = (el.innerText || el.textContent || '').trim().slice(0, 200);
            const href = el.getAttribute('href') || '';
            if (!href || href === '#' || href.startsWith('javascript:')) return;

            let resolvedUrl;
            try {
                resolvedUrl = new URL(href, window.location.href).href;
            } catch(e) { resolvedUrl = href; }

            let resolvedHost;
            try { resolvedHost = new URL(resolvedUrl).hostname; } catch(e) { resolvedHost = ''; }

            const isExternal = resolvedHost !== currentHost && resolvedHost !== '';

            // Domain mismatch: visible text contains a URL that differs from actual href
            const urlInText = text.match(/https?:\/\/([^/\\s]+)/);
            const textDomain = urlInText ? urlInText[1] : null;
            const domainMismatch = textDomain ? textDomain !== resolvedHost : false;

            // Sponsored / ad detection
            const parent = el.parentElement;
            const parentClasses = (parent?.className || '').toLowerCase();
            const isSponsored = parentClasses.includes('sponsor') ||
                                parentClasses.includes('ad') ||
                                parentClasses.includes('promo') ||
                                el.getAttribute('rel')?.includes('sponsored') ||
                                el.getAttribute('data-ad') !== null;

            results.push({
                text: text || '(no text)',
                displayed_url: href,
                actual_href: resolvedUrl,
                is_external: isExternal,
                domain_mismatch: domainMismatch,
                is_sponsored: isSponsored,
                css_selector: getCssSelector(el),
                bounding_box: getBbox(el),
            });
        } catch(e) {}
    });
    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 9. SCHEMA.ORG EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_SCHEMA_ORG_JS = """
(function extractSchemaOrg() {
    const results = [];
    document.querySelectorAll('script[type="application/ld+json"]').forEach(script => {
        try {
            const data = JSON.parse(script.textContent);
            const items = Array.isArray(data) ? data : [data];
            items.forEach(item => {
                if (!item || !item['@type']) return;
                const type = Array.isArray(item['@type']) ? item['@type'].join(',') : item['@type'];
                const offer = item.offers || {};
                const offers = Array.isArray(offer) ? offer[0] : offer;
                results.push({
                    type,
                    name: item.name || null,
                    price: offers.price !== undefined ? parseFloat(offers.price) : null,
                    currency: offers.priceCurrency || null,
                    original_price: item.highPrice ? parseFloat(item.highPrice) : null,
                    availability: offers.availability || null,
                    raw: item,
                });
            });
        } catch(e) {}
    });
    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 10. MUTATION OBSERVER SETUP  (injected at observation start)
# ─────────────────────────────────────────────────────────────

INJECT_MUTATION_OBSERVER_JS = """
window.__darkGuardMutations = [];
window.__darkGuardObserver = new MutationObserver(function(mutations) {
    const now = performance.now();
    mutations.forEach(function(m) {
        let targetSelector = '';
        try {
            const el = m.target;
            if (el.id) targetSelector = '#' + el.id;
            else if (el.className && typeof el.className === 'string')
                targetSelector = el.tagName.toLowerCase() + '.' +
                    el.className.trim().split(' ')[0];
            else targetSelector = el.tagName?.toLowerCase() || 'unknown';
        } catch(e) {}

        window.__darkGuardMutations.push({
            type: m.type,
            target_selector: targetSelector,
            added_nodes_count: m.addedNodes.length,
            removed_nodes_count: m.removedNodes.length,
            attribute_name: m.attributeName || null,
            old_value: m.oldValue ? String(m.oldValue).slice(0, 200) : null,
            new_value: m.target.getAttribute ? m.target.getAttribute(m.attributeName || '') : null,
            timestamp_ms: now,
        });
    });
});
window.__darkGuardObserver.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeOldValue: true,
    characterData: false,
});
'observer_injected';
"""

COLLECT_MUTATIONS_JS = """
(function() {
    if (window.__darkGuardObserver) {
        window.__darkGuardObserver.disconnect();
    }
    return window.__darkGuardMutations || [];
})();
"""


# ─────────────────────────────────────────────────────────────
# 11. CART LINE ITEMS EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_CART_ITEMS_JS = """
(function extractCartItems() {
    const results = [];
    const itemSelectors = [
        '[class*="cart-item"]', '[class*="cart_item"]',
        '[class*="basket-item"]', '[class*="line-item"]',
        '[class*="order-item"]', '[class*="product-row"]',
        'tr[class*="item"]', '[data-cart-item]',
    ];

    document.querySelectorAll(itemSelectors.join(',')).forEach(el => {
        try {
            const text = (el.innerText || '').trim();
            if (!text) return;

            // Try to extract product name and price from item row
            const nameEl = el.querySelector('[class*="name"], [class*="title"], h1, h2, h3, h4');
            const priceEl = el.querySelector('[class*="price"], [class*="amount"], [data-price]');
            const qtyEl = el.querySelector('[class*="qty"], [class*="quantity"], input[type="number"]');

            const PRICE_RE = /[\$\£\€\₹]?\s*[\d,]+\.?\d*/;

            results.push({
                name: nameEl?.innerText?.trim()?.slice(0, 100) || null,
                price_text: priceEl?.innerText?.trim() || null,
                price: priceEl?.innerText?.match(PRICE_RE)?.[0]?.replace(/[^\d.]/g,'') || null,
                quantity: qtyEl?.value || '1',
                full_text: text.slice(0, 300),
            });
        } catch(e) {}
    });
    return results;
})();
"""


# ─────────────────────────────────────────────────────────────
# 12. PAGE METADATA EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_METADATA_JS = """
(function extractMetadata() {
    const getMeta = (name) => {
        const el = document.querySelector(
            'meta[name="' + name + '"], meta[property="' + name + '"]'
        );
        return el ? el.getAttribute('content') : null;
    };
    return {
        title: document.title || '',
        lang: document.documentElement.lang || null,
        og_type: getMeta('og:type'),
        og_title: getMeta('og:title'),
        og_url: getMeta('og:url'),
        canonical: document.querySelector('link[rel="canonical"]')?.href || null,
        page_height: document.body.scrollHeight || document.documentElement.scrollHeight,
        viewport_width: window.innerWidth,
        viewport_height: window.innerHeight,
        final_url: window.location.href,
    };
})();
"""