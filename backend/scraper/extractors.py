"""
backend/scraper/extractors.py

Every extractor is a single self-contained IIFE so page.evaluate()
receives one expression — no top-level function declarations that
break Playwright's internal (expr) wrapping.
"""

# ─────────────────────────────────────────────────────────────
# 1. BUTTON EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_BUTTONS_JS = """
(() => {
    const getCssSelector = (el) => {
        try {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let cur = el;
            while (cur && cur !== document.body) {
                let sel = cur.tagName.toLowerCase();
                if (cur.className && typeof cur.className === 'string') {
                    const cls = cur.className.trim().split(/\\s+/).slice(0, 2);
                    if (cls.length) sel += '.' + cls.map(c => CSS.escape(c)).join('.');
                }
                const sibs = Array.from(cur.parentElement?.children || [])
                    .filter(s => s.tagName === cur.tagName);
                if (sibs.length > 1) sel += ':nth-of-type(' + (sibs.indexOf(cur) + 1) + ')';
                parts.unshift(sel);
                cur = cur.parentElement;
                if (parts.length >= 4) break;
            }
            return parts.join(' > ');
        } catch(e) { return el.tagName.toLowerCase(); }
    };

    const getBbox = (el) => {
        try {
            const r = el.getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height };
        } catch(e) { return null; }
    };

    const getStyle = (el, prop) => {
        try { return window.getComputedStyle(el).getPropertyValue(prop) || null; }
        catch(e) { return null; }
    };

    const results = [];
    const selectors = [
        'button', '[role="button"]', 'input[type="submit"]',
        'input[type="button"]', 'input[type="reset"]',
        'a.btn', 'a.button', '[class*="btn"]', '[class*="button"]', '[class*="cta"]'
    ];
    const seen = new WeakSet();

    document.querySelectorAll(selectors.join(',')).forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const text = (el.innerText || el.value || el.textContent || '').trim();
            const ariaLabel = el.getAttribute('aria-label') || null;
            const href = el.getAttribute('href') || null;

            let ancestor = el.parentElement;
            let isInModal = false, isInSticky = false;
            while (ancestor && ancestor !== document.body) {
                const pos = getStyle(ancestor, 'position');
                const z = parseInt(getStyle(ancestor, 'z-index') || '0');
                if ((pos === 'fixed' || pos === 'sticky') && z > 100) isInModal = true;
                if (pos === 'sticky') isInSticky = true;
                ancestor = ancestor.parentElement;
            }

            const closeKw = ['close','dismiss','cancel','×','✕','✖','x'];
            const isClose = closeKw.some(k => (text + (ariaLabel||'')).toLowerCase().includes(k))
                || el.getAttribute('data-dismiss') !== null;

            const dataAttrs = {};
            Array.from(el.attributes).filter(a => a.name.startsWith('data-'))
                .forEach(a => { dataAttrs[a.name] = a.value; });

            results.push({
                text, aria_label: ariaLabel, href, actual_href: href,
                domain_mismatch: false, redirect_chain: [],
                is_in_modal: isInModal, is_in_sticky: isInSticky,
                bg_color: getStyle(el, 'background-color'),
                text_color: getStyle(el, 'color'),
                font_size: getStyle(el, 'font-size'),
                css_selector: getCssSelector(el),
                bounding_box: getBbox(el),
                is_close_button: isClose,
                data_attributes: dataAttrs,
            });
        } catch(e) {}
    });
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 2. FORM EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_FORMS_JS = """
(() => {
    const getCssSelector = (el) => {
        try {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let cur = el;
            while (cur && cur !== document.body) {
                let sel = cur.tagName.toLowerCase();
                if (cur.className && typeof cur.className === 'string') {
                    const cls = cur.className.trim().split(/\\s+/).slice(0, 2);
                    if (cls.length) sel += '.' + cls.map(c => CSS.escape(c)).join('.');
                }
                parts.unshift(sel);
                cur = cur.parentElement;
                if (parts.length >= 4) break;
            }
            return parts.join(' > ');
        } catch(e) { return el.tagName.toLowerCase(); }
    };

    const processField = (el) => {
        const type = el.getAttribute('type') || el.tagName.toLowerCase();
        const name = el.getAttribute('name') || el.getAttribute('id') || null;
        let labelText = null;
        const id = el.getAttribute('id');
        if (id) {
            const lbl = document.querySelector('label[for="' + id + '"]');
            if (lbl) labelText = lbl.innerText.trim();
        }
        if (!labelText) {
            const pl = el.closest('label');
            if (pl) labelText = pl.innerText.trim();
        }
        return {
            tag: el.tagName.toLowerCase(), input_type: type, name,
            label_text: labelText,
            placeholder: el.getAttribute('placeholder') || null,
            value: el.value || el.getAttribute('value') || null,
            is_checked: el.checked || false,
            is_pre_checked: el.hasAttribute('checked') || el.defaultChecked || false,
            is_required: el.required || el.hasAttribute('required'),
            is_hidden: type === 'hidden' || el.style.display === 'none'
                       || el.style.visibility === 'hidden',
            css_selector: getCssSelector(el),
        };
    };

    const results = [];

    document.querySelectorAll('form').forEach(form => {
        const fields = [];
        let hasHiddenConsent = false, preCheckedCount = 0;
        form.querySelectorAll('input, select, textarea').forEach(el => {
            const f = processField(el);
            fields.push(f);
            if (f.is_hidden && f.value) hasHiddenConsent = true;
            if (f.input_type === 'checkbox' && f.is_pre_checked) preCheckedCount++;
        });
        results.push({
            form_id: form.getAttribute('id') || form.getAttribute('name') || null,
            action: form.getAttribute('action') || null,
            method: (form.getAttribute('method') || 'GET').toUpperCase(),
            fields, has_hidden_consent: hasHiddenConsent,
            pre_checked_count: preCheckedCount,
        });
    });

    // Standalone checkboxes outside any form
    const standalone = Array.from(document.querySelectorAll('input[type="checkbox"]'))
        .filter(cb => !cb.closest('form'));
    if (standalone.length) {
        const fields = standalone.map(processField);
        results.push({
            form_id: '__standalone_checkboxes__', action: null, method: 'N/A',
            fields, has_hidden_consent: false,
            pre_checked_count: fields.filter(f => f.is_pre_checked).length,
        });
    }
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 3. PRICE EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_PRICES_JS = """
(() => {
    const getCssSelector = (el) => {
        try {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let cur = el;
            while (cur && cur !== document.body) {
                let sel = cur.tagName.toLowerCase();
                if (cur.className && typeof cur.className === 'string') {
                    const cls = cur.className.trim().split(/\\s+/).slice(0, 2);
                    if (cls.length) sel += '.' + cls.map(c => CSS.escape(c)).join('.');
                }
                parts.unshift(sel);
                cur = cur.parentElement;
                if (parts.length >= 4) break;
            }
            return parts.join(' > ');
        } catch(e) { return el.tagName.toLowerCase(); }
    };

    const getBbox = (el) => {
        try {
            const r = el.getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height };
        } catch(e) { return null; }
    };

    const results = [];
    const seen = new WeakSet();
    const CURRENCY_RE = /(?:[$£€₹¥₩₺₱฿])\\s*[\\d,]+(?:\\.\\d{1,2})?|[\\d,]+(?:\\.\\d{1,2})?\\s*(?:USD|EUR|GBP|INR|JPY)/g;

    // Layer 1: Schema.org
    document.querySelectorAll('script[type="application/ld+json"]').forEach(script => {
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
                        if (o.price !== undefined) { price = parseFloat(o.price); currency = o.priceCurrency || null; }
                    });
                    origPrice = item.highPrice ? parseFloat(item.highPrice) : null;
                }
                if (price !== null) {
                    results.push({ text: String(price), amount: price, currency, original_price: origPrice,
                        context_before: null, context_after: null, location: 'schema_org',
                        css_selector: null, bounding_box: null, schema_sourced: true });
                }
            });
        } catch(e) {}
    });

    // Layer 2: Semantic selectors
    const PRICE_SELS = [
        '[class*="price"]','[class*="Price"]','[class*="cost"]','[class*="amount"]',
        '[class*="total"]','[class*="subtotal"]','[data-price]','[data-original-price]',
        '[itemprop="price"]','.price','.cost','.amount'
    ];
    document.querySelectorAll(PRICE_SELS.join(',')).forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const text = (el.innerText || el.textContent || '').trim();
            if (!text || text.length > 50) return;
            const match = text.match(CURRENCY_RE);
            const rawAmount = el.getAttribute('data-price') || el.getAttribute('data-sale-price')
                || (match ? match[0].replace(/[^\\d.]/g, '') : null);
            if (!rawAmount && !match) return;
            const origRaw = el.getAttribute('data-original-price') || el.getAttribute('data-regular-price');
            const location = el.closest('[class*="cart"]') ? 'cart_summary'
                : el.closest('[class*="checkout"]') ? 'checkout_total'
                : el.closest('[class*="product"]') ? 'product_section'
                : el.closest('[class*="order"]') ? 'order_summary' : 'page';
            results.push({
                text, amount: rawAmount ? parseFloat(rawAmount) : null,
                currency: null, original_price: origRaw ? parseFloat(origRaw) : null,
                context_before: el.previousElementSibling?.innerText?.trim() || null,
                context_after: el.nextElementSibling?.innerText?.trim() || null,
                location, css_selector: getCssSelector(el), bounding_box: getBbox(el),
                schema_sourced: false,
            });
        } catch(e) {}
    });

    // Layer 3: Text node sweep
    const SIMPLE_CURRENCY = /[$£€₹¥]/;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
        const txt = node.textContent.trim();
        if (SIMPLE_CURRENCY.test(txt) && txt.length < 30) {
            const parent = node.parentElement;
            if (parent && !seen.has(parent)) {
                seen.add(parent);
                const matches = txt.match(CURRENCY_RE);
                if (matches) {
                    matches.forEach(m => {
                        const amount = parseFloat(m.replace(/[^\\d.]/g, ''));
                        if (!isNaN(amount)) {
                            results.push({
                                text: txt, amount, currency: null, original_price: null,
                                context_before: null, context_after: null, location: 'text_node',
                                css_selector: getCssSelector(parent), bounding_box: getBbox(parent),
                                schema_sourced: false,
                            });
                        }
                    });
                }
            }
        }
    }
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 4. SUPPLEMENTAL CHARGES EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_SUPPLEMENTAL_CHARGES_JS = """
(() => {
    const CHARGE_KEYWORDS = [
        'service fee','convenience fee','platform fee','processing fee',
        'handling fee','insurance','protection plan','priority',
        'shipping protection','donation','tip','gratuity','surcharge',
        'booking fee','transaction fee'
    ];
    const CURRENCY_RE = /[$£€₹¥]?\\s*[\\d,]+\\.?\\d*/;
    const results = [];

    document.querySelectorAll(
        '[class*="fee"],[class*="charge"],[class*="extra"],[class*="surcharge"],' +
        '[class*="add-on"],[class*="addon"],[class*="upsell"],[class*="insurance"],' +
        '[class*="protection"]'
    ).forEach(el => {
        try {
            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            if (!text) return;
            if (!CHARGE_KEYWORDS.some(k => text.includes(k))) return;
            const amountMatch = el.innerText.match(CURRENCY_RE);
            const amount = amountMatch ? parseFloat(amountMatch[0].replace(/[^\\d.]/g,'')) : null;
            const checkbox = el.querySelector('input[type="checkbox"]');
            results.push({
                label: el.innerText.trim().split('\\n')[0].slice(0, 100),
                amount, currency: null,
                is_pre_selected: checkbox ? (checkbox.checked && checkbox.defaultChecked) : false,
                is_optional: checkbox !== null,
                css_selector: null,
            });
        } catch(e) {}
    });
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 5. OVERLAY EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_OVERLAYS_JS = """
(() => {
    const getCssSelector = (el) => {
        try {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let cur = el;
            while (cur && cur !== document.body) {
                let sel = cur.tagName.toLowerCase();
                if (cur.className && typeof cur.className === 'string') {
                    const cls = cur.className.trim().split(/\\s+/).slice(0,2);
                    if (cls.length) sel += '.' + cls.map(c => CSS.escape(c)).join('.');
                }
                parts.unshift(sel);
                cur = cur.parentElement;
                if (parts.length >= 4) break;
            }
            return parts.join(' > ');
        } catch(e) { return el.tagName.toLowerCase(); }
    };

    const results = [];
    const VW = window.innerWidth, VH = window.innerHeight;

    document.querySelectorAll('*').forEach(el => {
        try {
            const style = window.getComputedStyle(el);
            const pos = style.getPropertyValue('position');
            const zIdx = parseInt(style.getPropertyValue('z-index') || '0');
            if ((pos !== 'fixed' && pos !== 'sticky') || zIdx < 50) return;
            if (style.display === 'none' || style.visibility === 'hidden') return;
            const text = (el.innerText || el.textContent || '').trim();
            if (!text || text.length < 5) return;

            const bbox = el.getBoundingClientRect();
            const coverage = (bbox.width * bbox.height) / (VW * VH);
            const overlayType = coverage > 0.15 ? 'modal'
                : (bbox.y < VH * 0.15 || bbox.y > VH * 0.75) ? 'banner' : 'toast';

            const closeKw = ['close','dismiss','×','✕','✖','skip','no thanks'];
            let hasClose = false, closeProminent = false;
            el.querySelectorAll('button,[role="button"],a').forEach(btn => {
                const t = (btn.innerText || btn.getAttribute('aria-label') || '').toLowerCase();
                if (closeKw.some(k => t.includes(k))) {
                    hasClose = true;
                    closeProminent = parseFloat(window.getComputedStyle(btn).fontSize) >= 14;
                }
            });

            results.push({
                overlay_type: overlayType,
                text: text.slice(0, 500),
                html: el.outerHTML.slice(0, 2000),
                trigger_delay_ms: 0,
                appeared_autonomously: false,
                viewport_coverage_pct: parseFloat((coverage * 100).toFixed(2)),
                has_close_button: hasClose,
                close_button_prominent: closeProminent,
                blocks_interaction: false,
                css_selector: getCssSelector(el),
                bounding_box: { x: bbox.x, y: bbox.y, width: bbox.width, height: bbox.height },
                contains_form: el.querySelector('form,input') !== null,
                contains_cta: el.querySelector('button,[role="button"],a') !== null,
            });
        } catch(e) {}
    });
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 6. TIMER EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_TIMERS_JS = """
(() => {
    const TIMER_RE = /\\d{1,2}:\\d{2}(:\\d{2})?/;
    const COUNTDOWN_RE = /\\d+\\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?|days?)/i;
    const results = [];
    const seen = new WeakSet();

    const timerSels = [
        '[class*="countdown"],[class*="timer"],[class*="clock"]',
        '[class*="expir"],[class*="limited"],[class*="hurry"]',
        '[data-countdown],[data-timer],[data-expiry]',
        '[id*="countdown"],[id*="timer"]'
    ];
    document.querySelectorAll(timerSels.join(',')).forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const text = (el.innerText || el.textContent || '').trim();
            if (!text) return;
            results.push({
                text: text.slice(0, 100),
                is_counting_down: TIMER_RE.test(text) || COUNTDOWN_RE.test(text)
                    || el.getAttribute('data-countdown') !== null,
                css_selector: null,
                context: el.parentElement?.innerText?.trim()?.slice(0, 200) || null,
            });
        } catch(e) {}
    });

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
        const txt = node.textContent.trim();
        if ((TIMER_RE.test(txt) || COUNTDOWN_RE.test(txt)) && txt.length < 80) {
            const parent = node.parentElement;
            if (parent && !seen.has(parent)) {
                seen.add(parent);
                results.push({
                    text: txt, is_counting_down: true, css_selector: null,
                    context: parent.parentElement?.innerText?.trim()?.slice(0, 200) || null,
                });
            }
        }
    }
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 7. HIDDEN ELEMENT EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_HIDDEN_ELEMENTS_JS = """
(() => {
    const getCssSelector = (el) => {
        try {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let cur = el;
            while (cur && cur !== document.body) {
                let sel = cur.tagName.toLowerCase();
                if (cur.className && typeof cur.className === 'string') {
                    const cls = cur.className.trim().split(/\\s+/).slice(0, 2);
                    if (cls.length) sel += '.' + cls.map(c => CSS.escape(c)).join('.');
                }
                parts.unshift(sel);
                cur = cur.parentElement;
                if (parts.length >= 4) break;
            }
            return parts.join(' > ');
        } catch(e) { return el.tagName.toLowerCase(); }
    };

    const results = [];
    const seen = new WeakSet();

    document.querySelectorAll(
        'input[type="hidden"],[style*="display:none"],[style*="display: none"],' +
        '[style*="visibility:hidden"],[style*="visibility: hidden"],' +
        '[style*="opacity:0"],[style*="opacity: 0"]'
    ).forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        try {
            const type = el.getAttribute('type');
            let reason = 'offscreen';
            if (type === 'hidden') reason = 'type_hidden';
            else if (el.style.display?.includes('none')) reason = 'display:none';
            else if (el.style.visibility === 'hidden') reason = 'visibility:hidden';
            else if (el.style.opacity === '0') reason = 'opacity:0';
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
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 8. LINK EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_LINKS_JS = """
(() => {
    const getCssSelector = (el) => {
        try {
            if (el.id) return '#' + CSS.escape(el.id);
            const parts = [];
            let cur = el;
            while (cur && cur !== document.body) {
                let sel = cur.tagName.toLowerCase();
                if (cur.className && typeof cur.className === 'string') {
                    const cls = cur.className.trim().split(/\\s+/).slice(0, 2);
                    if (cls.length) sel += '.' + cls.map(c => CSS.escape(c)).join('.');
                }
                parts.unshift(sel);
                cur = cur.parentElement;
                if (parts.length >= 4) break;
            }
            return parts.join(' > ');
        } catch(e) { return el.tagName.toLowerCase(); }
    };

    const getBbox = (el) => {
        try { const r = el.getBoundingClientRect(); return { x:r.x, y:r.y, width:r.width, height:r.height }; }
        catch(e) { return null; }
    };

    const results = [];
    const currentHost = window.location.hostname;

    document.querySelectorAll('a[href]').forEach(el => {
        try {
            const text = (el.innerText || el.textContent || '').trim().slice(0, 200);
            const href = el.getAttribute('href') || '';
            if (!href || href === '#' || href.startsWith('javascript:')) return;
            let resolvedUrl = href;
            try { resolvedUrl = new URL(href, window.location.href).href; } catch(e) {}
            let resolvedHost = '';
            try { resolvedHost = new URL(resolvedUrl).hostname; } catch(e) {}
            const isExternal = resolvedHost !== currentHost && resolvedHost !== '';
            const urlInText = text.match(/https?:\\/\\/([^/\\s]+)/);
            const textDomain = urlInText ? urlInText[1] : null;
            const domainMismatch = textDomain ? textDomain !== resolvedHost : false;
            const parentCls = (el.parentElement?.className || '').toLowerCase();
            const isSponsored = parentCls.includes('sponsor') || parentCls.includes(' ad')
                || el.getAttribute('rel')?.includes('sponsored')
                || el.getAttribute('data-ad') !== null;
            results.push({
                text: text || '(no text)',
                displayed_url: href, actual_href: resolvedUrl,
                is_external: isExternal, domain_mismatch: domainMismatch,
                is_sponsored: isSponsored,
                css_selector: getCssSelector(el), bounding_box: getBbox(el),
            });
        } catch(e) {}
    });
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 9. SCHEMA.ORG EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_SCHEMA_ORG_JS = """
(() => {
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
                    type, name: item.name || null,
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
})()
"""


# ─────────────────────────────────────────────────────────────
# 10. MUTATION OBSERVER SETUP
# ─────────────────────────────────────────────────────────────

INJECT_MUTATION_OBSERVER_JS = """
(() => {
    window.__darkGuardMutations = [];
    window.__darkGuardObserver = new MutationObserver((mutations) => {
        const now = performance.now();
        mutations.forEach((m) => {
            let targetSelector = '';
            try {
                const el = m.target;
                if (el.id) targetSelector = '#' + el.id;
                else if (el.className && typeof el.className === 'string')
                    targetSelector = (el.tagName?.toLowerCase() || '') + '.' +
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
                new_value: m.target.getAttribute
                    ? m.target.getAttribute(m.attributeName || '') : null,
                timestamp_ms: now,
            });
        });
    });
    window.__darkGuardObserver.observe(document.body, {
        childList: true, subtree: true,
        attributes: true, attributeOldValue: true, characterData: false,
    });
    return 'observer_injected';
})()
"""

COLLECT_MUTATIONS_JS = """
(() => {
    if (window.__darkGuardObserver) window.__darkGuardObserver.disconnect();
    return window.__darkGuardMutations || [];
})()
"""


# ─────────────────────────────────────────────────────────────
# 11. CART ITEMS EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_CART_ITEMS_JS = """
(() => {
    const results = [];
    const PRICE_RE = /[$£€₹¥]?\\s*[\\d,]+\\.?\\d*/;
    const sels = [
        '[class*="cart-item"],[class*="cart_item"],[class*="basket-item"]',
        '[class*="line-item"],[class*="order-item"],[class*="product-row"]',
        'tr[class*="item"],[data-cart-item]'
    ];
    document.querySelectorAll(sels.join(',')).forEach(el => {
        try {
            const text = (el.innerText || '').trim();
            if (!text) return;
            const nameEl  = el.querySelector('[class*="name"],[class*="title"],h1,h2,h3,h4');
            const priceEl = el.querySelector('[class*="price"],[class*="amount"],[data-price]');
            const qtyEl   = el.querySelector('[class*="qty"],[class*="quantity"],input[type="number"]');
            results.push({
                name: nameEl?.innerText?.trim()?.slice(0, 100) || null,
                price_text: priceEl?.innerText?.trim() || null,
                price: priceEl?.innerText?.match(PRICE_RE)?.[0]?.replace(/[^\\d.]/g,'') || null,
                quantity: qtyEl?.value || '1',
                full_text: text.slice(0, 300),
            });
        } catch(e) {}
    });
    return results;
})()
"""


# ─────────────────────────────────────────────────────────────
# 12. METADATA EXTRACTOR
# ─────────────────────────────────────────────────────────────

EXTRACT_METADATA_JS = """
(() => {
    const getMeta = (name) => {
        const el = document.querySelector(
            'meta[name="' + name + '"],meta[property="' + name + '"]'
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
})()
"""

# ─────────────────────────────────────────────────────────────
# 13. FULL TEXT CONTENT EXTRACTOR
# Captures every visible text node with its tag, location,
# and surrounding context so agents can analyse any text on
# the page — including "Only 2 left!", urgency banners, etc.
# ─────────────────────────────────────────────────────────────

EXTRACT_ALL_TEXT_JS = """
(() => {
    const results = [];
    const seen = new WeakSet();

    // Tags whose text is meaningful for dark pattern detection
    const TARGET_TAGS = new Set([
        'P','H1','H2','H3','H4','H5','H6',
        'SPAN','DIV','SECTION','ARTICLE','ASIDE',
        'LI','TD','TH','LABEL','LEGEND','FIGCAPTION',
        'STRONG','EM','B','I','SMALL','MARK',
        'BUTTON','A','HEADER','FOOTER','NAV',
        'CAPTION','BLOCKQUOTE','PRE',
    ]);

    // Skip these — they contain no readable user-facing text
    const SKIP_TAGS = new Set([
        'SCRIPT','STYLE','NOSCRIPT','TEMPLATE',
        'SVG','PATH','DEFS','USE','SYMBOL',
        'META','LINK','HEAD',
    ]);

    const isVisible = (el) => {
        try {
            const style = window.getComputedStyle(el);
            if (style.display === 'none') return false;
            if (style.visibility === 'hidden') return false;
            if (parseFloat(style.opacity) === 0) return false;
            const r = el.getBoundingClientRect();
            // Allow off-screen elements — they may still be dark patterns
            // (e.g. hidden consent text). Only skip zero-size invisible ones.
            if (r.width === 0 && r.height === 0) return false;
            return true;
        } catch(e) { return false; }
    };

    const getLocation = (el) => {
        // Walk up to find a meaningful ancestor label
        let ancestor = el.parentElement;
        while (ancestor && ancestor !== document.body) {
            const tag = ancestor.tagName;
            const cls = (ancestor.className || '').toLowerCase();
            const id  = (ancestor.id || '').toLowerCase();
            if (tag === 'NAV' || cls.includes('nav') || id.includes('nav')) return 'navigation';
            if (tag === 'HEADER' || cls.includes('header')) return 'header';
            if (tag === 'FOOTER' || cls.includes('footer')) return 'footer';
            if (cls.includes('modal') || cls.includes('dialog') || cls.includes('popup')) return 'modal';
            if (cls.includes('banner') || cls.includes('alert') || cls.includes('notice')) return 'banner';
            if (cls.includes('cart') || cls.includes('basket')) return 'cart';
            if (cls.includes('checkout')) return 'checkout';
            if (cls.includes('product') || cls.includes('item')) return 'product';
            if (cls.includes('price') || cls.includes('cost') || cls.includes('amount')) return 'price_area';
            if (cls.includes('form')) return 'form';
            if (cls.includes('hero') || cls.includes('jumbotron')) return 'hero';
            ancestor = ancestor.parentElement;
        }
        return 'body';
    };

    const getZIndex = (el) => {
        try { return parseInt(window.getComputedStyle(el).zIndex || '0') || 0; }
        catch(e) { return 0; }
    };

    const isInFixed = (el) => {
        let cur = el;
        while (cur && cur !== document.body) {
            try {
                const pos = window.getComputedStyle(cur).position;
                if (pos === 'fixed' || pos === 'sticky') return true;
            } catch(e) {}
            cur = cur.parentElement;
        }
        return false;
    };

    // Walk every element in the DOM
    const allEls = document.querySelectorAll('*');
    allEls.forEach(el => {
        if (SKIP_TAGS.has(el.tagName)) return;
        if (!TARGET_TAGS.has(el.tagName)) return;
        if (seen.has(el)) return;

        // Only take leaf-ish nodes — elements whose direct text is meaningful.
        // An element qualifies if it has at least one direct text node child
        // with non-whitespace content.
        let directText = '';
        el.childNodes.forEach(node => {
            if (node.nodeType === Node.TEXT_NODE) {
                directText += node.textContent;
            }
        });
        directText = directText.trim();

        // Also take short elements where ALL text is direct (no nested elements
        // with separate meaning) — catches <span>Only 2 left!</span> patterns
        const fullText = (el.innerText || el.textContent || '').trim();

        // Choose the best text representation
        let text = directText || fullText;
        if (!text || text.length < 2) return;
        if (text.length > 2000) return; // skip massive blocks, full_text covers those

        seen.add(el);

        // Get bounding box for position context
        let bbox = null;
        try {
            const r = el.getBoundingClientRect();
            bbox = { x: Math.round(r.x), y: Math.round(r.y),
                     width: Math.round(r.width), height: Math.round(r.height) };
        } catch(e) {}

        results.push({
            tag:         el.tagName.toLowerCase(),
            text:        text.slice(0, 500),
            location:    getLocation(el),
            is_visible:  isVisible(el),
            is_in_fixed: isInFixed(el),    // fixed/sticky = likely overlay/banner
            z_index:     getZIndex(el),
            bbox:        bbox,
            // Parent context — what contains this text
            parent_tag:  el.parentElement?.tagName?.toLowerCase() || null,
            parent_class:(el.parentElement?.className || '').slice(0, 100) || null,
            // Nearby text for context (previous + next sibling text)
            prev_text:   el.previousElementSibling
                            ? (el.previousElementSibling.innerText||'').trim().slice(0,100)
                            : null,
            next_text:   el.nextElementSibling
                            ? (el.nextElementSibling.innerText||'').trim().slice(0,100)
                            : null,
        });
    });

    return results;
})()
"""