async function runJevBrowser(page, cfg) {
// Fixed server-side Playwright code. cfg is JSON data, never executable input.
// The private map lives on the Node BrowserContext, NOT on the web page.
const key = Symbol.for(cfg.namespace);
const context = page.context();
if (!context[key]) context[key] = new Map();
const pending = context[key];
const fail = reason => { const error = new Error(); error.jevReason = reason; throw error; };
const dispose = async p => {
  if (!p) return;
  p.context.removeListener('page', p.changed);
  p.page.removeListener('popup', p.changed);
  p.page.removeListener('close', p.changed);
  p.page.removeListener('framenavigated', p.navigated);
  if (p.identity) {
    await p.identity.evaluate(s => s.observer.disconnect()).catch(() => {});
    await p.identity.dispose().catch(() => {});
  }
  for (const entry of p.elements.values()) await entry.element.dispose().catch(() => {});
};
// Render a detached copy only. NEVER access a sensitive control's .value.
// Whitelisted attributes omit inline handlers, URLs, data attributes and defaults.
const render = (source, limit) => {
  const sensitive = el => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    const name = ((el.getAttribute('name') || '') + ' ' + (el.id || '')).toLowerCase();
    return type === 'password' || /cc-|one-time-code|password/.test(ac)
      || /password|passwd|card.?number|credit.?card|cvc|cvv|otp|verification.?code|api.?key|secret|access.?token/.test(name);
  };
  let nodes = 0;
  const doc = source.ownerDocument || source;
  const copy = node => {
    if (++nodes > 5000) return null;
    if (node.nodeType === 3) return doc.createTextNode(node.textContent || '');
    if (node.nodeType !== 1 || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|META|LINK|IFRAME)$/.test(node.tagName)) return null;
    const style = doc.defaultView.getComputedStyle(node);
    if (node.hidden || node.getAttribute('aria-hidden') === 'true' || style.display === 'none' || style.visibility === 'hidden') return null;
    const clone = doc.createElement('div');
    const control = /^(INPUT|TEXTAREA|SELECT|BUTTON|A)$/.test(node.tagName) || node.getAttribute('role');
    if (sensitive(node)) {
      clone.textContent = '[sensitive control redacted]';
      return clone;
    }
    if (control) {
      const attrs = ['id', 'role', 'aria-label', 'placeholder', 'type', 'name'].map(a => {
        const value = node.getAttribute(a); return value ? a + '=' + value.slice(0, 150) : '';
      }).filter(Boolean).join(' ');
      clone.appendChild(doc.createTextNode('\n[' + node.tagName + (attrs ? ' ' + attrs : '') + (node.disabled ? ' disabled' : '') + '] '));
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(node.tagName)) {
        clone.appendChild(doc.createTextNode(String(node.value || '').slice(0, 1000)));
        if (node.checked) clone.appendChild(doc.createTextNode(' [checked]'));
      }
    }
    if (!/^(TEXTAREA|INPUT)$/.test(node.tagName)) for (const child of node.childNodes) {
      const next = copy(child); if (next) clone.appendChild(next);
    }
    clone.appendChild(doc.createTextNode('\n'));
    return clone;
  };
  const clone = copy(source);
  const text = clone ? (clone.textContent || '').replace(/[ \t]+/g, ' ').replace(/\n\s*\n/g, '\n').trim() : '';
  return {text: text.slice(0, limit), truncated: text.length > limit || nodes > 5000};
};
// Source is fixed; this renderer receives a retained root/ElementHandle, not selectors.
const renderSource = render.toString();
const same = async p => {
  if (!p || p.dirty || p.page !== page || page.isClosed()) return false;
  try {
    return await p.identity.evaluate(s => !s.dirty && s.root === document.documentElement && s.doc === document && s.url === location.href);
  } catch { return false; }
};
const ensure = async p => { if (!(await same(p))) fail('page_changed'); };
const fingerprint = async element => element.evaluate(el => {
  const type = (el.getAttribute('type') || '').toLowerCase();
  const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  const name = ((el.getAttribute('name') || '') + ' ' + (el.id || '')).toLowerCase();
  const sensitive = type === 'password' || /cc-|one-time-code|password/.test(ac)
    || /password|passwd|card.?number|credit.?card|cvc|cvv|otp|verification.?code|api.?key|secret|access.?token/.test(name);
  // Do not serialize outerHTML before ruling out password descendants/defaults.
  if (sensitive || el.querySelector('input[type="password"], [autocomplete*="password"], [autocomplete*="cc-"], [autocomplete="one-time-code"]'))
    return {eligible: false, reason: 'sensitive_field'};
  if (!el.isConnected || el.ownerDocument !== document || el.getRootNode() !== document)
    return {eligible: false, reason: 'element_changed'};
  const r = el.getBoundingClientRect(), style = getComputedStyle(el);
  if (!r.width || !r.height || style.display === 'none' || style.visibility === 'hidden' || el.disabled || el.readOnly)
    return {eligible: false, reason: 'not_actionable'};
  return {eligible: true, signature: JSON.stringify({html: el.outerHTML, value: 'value' in el ? el.value : null,
    checked: 'checked' in el ? el.checked : null, rect: [r.x,r.y,r.width,r.height],
    style: [style.display,style.visibility,style.pointerEvents]})};
});
const readChecks = async p => {
  const matches = [];
  for (const check of cfg.success_checks || []) {
    await ensure(p);
    const handles = await page.locator(check.target).elementHandles();
    try {
      if (handles.length !== 1) { matches.push(false); continue; }
      const observed = await handles[0].evaluate((el, limit) => {
        // Clone visible text only; CSS-hidden messages and form defaults are
        // not business-success evidence. Never inspect control .value here.
        if (!el.isConnected || el.ownerDocument !== document || !el.getClientRects().length) return null;
        const hidden = node => {
          const style = getComputedStyle(node);
          return node.hidden || node.getAttribute('aria-hidden') === 'true' || style.display === 'none'
            || style.visibility === 'hidden' || style.visibility === 'collapse' || style.opacity === '0'
            || style.contentVisibility === 'hidden';
        };
        // A selected span can have a box even under opacity/ARIA-hidden ancestors.
        // Walk above the selected root as well as pruning its hidden descendants.
        for (let node = el; node; node = node.parentElement) if (hidden(node)) return null;
        let nodes = 0, truncated = false;
        const copy = node => {
          if (++nodes > 5000) { truncated = true; return null; }
          if (node.nodeType === 3) return document.createTextNode(node.textContent || '');
          if (node.nodeType !== 1 || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|INPUT|TEXTAREA|SELECT|IFRAME)$/.test(node.tagName)) return null;
          if (hidden(node)) return null;
          const clone = document.createElement('div');
          for (const child of node.childNodes) { const c = copy(child); if (c) clone.appendChild(c); }
          return clone;
        };
        const clone = copy(el);
        if (!clone) return null;
        const text = (clone.textContent || '').trim();
        return {text: text.slice(0, limit), truncated: truncated || text.length > limit};
      }, 4000);
      matches.push(observed !== null && (check.match === 'exact'
        ? !observed.truncated && observed.text === check.text : observed.text.includes(check.text)));
    } finally { for (const handle of handles) await handle.dispose().catch(() => {}); }
  }
  await ensure(p);
  return matches;
};
let p = pending.get(cfg.op_id);
try {
  if (cfg.phase === 'cleanup') {
    pending.delete(cfg.op_id); await dispose(p); return {ok: true};
  }
  if (cfg.phase === 'prepare') {
    if (p) fail('invalid_operation');
    p = {context, page, dirty: false, elements: new Map(), identity: null};
    pending.set(cfg.op_id, p);
    p.changed = () => { p.dirty = true; };
    p.navigated = frame => { if (frame === page.mainFrame()) p.changed(); };
    context.on('page', p.changed); page.on('popup', p.changed); page.on('close', p.changed); page.on('framenavigated', p.navigated);
    p.identity = await page.evaluateHandle(() => {
      const state = {root: document.documentElement, doc: document, url: location.href, dirty: false};
      state.observer = new MutationObserver(() => { state.dirty = true; });
      state.observer.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
      return state;
    });
    const candidate_status = [], eligible_ids = [];
    for (const candidate of cfg.candidates || []) {
      await ensure(p);
      const handles = await page.locator(candidate.action.target).elementHandles();
      if (handles.length !== 1) {
        for (const handle of handles) await handle.dispose().catch(() => {});
        candidate_status.push({id: candidate.id, eligible: false, reason: 'not_unique_or_missing'}); continue;
      }
      const element = handles[0];
      p.elements.set(candidate.id, {element, action: candidate.action, signature: null});
      const f = await fingerprint(element);
      if (f.eligible) { p.elements.get(candidate.id).signature = f.signature; eligible_ids.push(candidate.id); }
      candidate_status.push({id: candidate.id, eligible: f.eligible, ...(!f.eligible ? {reason: f.reason} : {})});
    }
    await ensure(p);
    // This is fixed source, not cfg content. Playwright accepts a function string.
    const observation = await page.evaluate('(' + renderSource + ')(document.body, ' + cfg.max_chars + ')');
    p.pageText = observation.text;
    p.maxChars = cfg.max_chars;
    const checks = await readChecks(p);
    await ensure(p);
    return {ok: true, page_text: observation.text, truncated: observation.truncated, eligible_ids, candidate_status, checks};
  }
  await ensure(p);
  if (cfg.phase === 'verify') return {ok: true, checks: await readChecks(p)};
  if (cfg.phase === 'validate') {
    const observation = await page.evaluate('(' + renderSource + ')(document.body, ' + p.maxChars + ')');
    if (observation.text !== p.pageText) fail('page_changed');
    await ensure(p);
    return {ok: true};
  }
  if (cfg.phase !== 'execute') fail('invalid_operation');
  const entry = p.elements.get(cfg.candidate_id);
  if (!entry || !entry.signature) fail('invalid_candidate');
  const current = await fingerprint(entry.element);
  if (!current.eligible || current.signature !== entry.signature) fail('element_changed');
  const observation = await page.evaluate('(' + renderSource + ')(document.body, ' + cfg.max_chars + ')');
  if (observation.text !== p.pageText) fail('page_changed');
  await ensure(p);
  // Consume before submission. A failed/uncertain action is NEVER retried.
  p.elements.delete(cfg.candidate_id);
  const opt = {timeout: 1000};
  // Public locator handlers run BEFORE actionability, not atomically at dispatch.
  // A changed overlay can disappear between that check and input delivery. Do
  // not auto-wait across retries at all: a second checkpoint hands off safely.
  // Throwing from a locator handler does NOT cancel Playwright: its finally
  // acknowledges the handler and resumes the action. On stale evidence, hold
  // the checkpoint until the native action's own timeout has actually settled.
  // This is a retry guard, NOT atomic with browser input dispatch: page script
  // may still change state after a checkpoint, including in input event handlers.
  const trigger = page.locator('body');
  let registered = false, guardReason = null, releaseGuard, checkpoints = 0;
  let runningGuard = Promise.resolve();
  const blocked = new Promise(resolve => { releaseGuard = resolve; });
  const guard = async () => {
    try {
      if (++checkpoints > 1) fail('not_actionable');
      await ensure(p);
      const fresh = await fingerprint(entry.element);
      if (!fresh.eligible || fresh.signature !== entry.signature) fail('element_changed');
      const text = await page.evaluate('(' + renderSource + ')(document.body, ' + p.maxChars + ')');
      if (text.text !== p.pageText) fail('page_changed');
      await ensure(p);
    } catch (error) {
      guardReason = error.jevReason || 'page_changed';
      await blocked;
    }
  };
  try {
    // press has no actionability auto-wait; the checks above precede it directly.
    if (entry.action.op !== 'press') {
      if (typeof page.addLocatorHandler !== 'function' || typeof page.removeLocatorHandler !== 'function'
          || !(await trigger.isVisible())) fail('not_actionable');
      await page.addLocatorHandler(trigger, () => { runningGuard = guard(); return runningGuard; }, {noWaitAfter: true});
      registered = true;
    }
    switch (entry.action.op) {
      case 'click': await entry.element.click(opt); break;
      case 'fill': await entry.element.fill(entry.action.value, opt); break;
      case 'select': await entry.element.selectOption(entry.action.value, opt); break;
      case 'check': await entry.element.check(opt); break;
      case 'press': await entry.element.press(entry.action.value, opt); break;
      default: fail('invalid_candidate');
    }
  } catch (error) {
    if (guardReason) fail(guardReason);
    throw error;
  } finally {
    // Never release a stale checkpoint while the native write is still pending.
    releaseGuard();
    await runningGuard;
    if (registered) await page.removeLocatorHandler(trigger).catch(() => {});
    await entry.element.dispose().catch(() => {});
  }
  // Own action may legitimately mutate the DOM. Navigation/popup never chains.
  if (p.dirty || page.isClosed()) fail('page_changed');
  const rootMatches = await p.identity.evaluate(s => s.root === document.documentElement && s.doc === document);
  if (!rootMatches) fail('page_changed');
  return {ok: true, completed: 1};
} catch (error) {
  const allowed = ['page_changed','element_changed','not_actionable','sensitive_field','invalid_candidate','invalid_operation'];
  const reason = error.jevReason && allowed.includes(error.jevReason) ? error.jevReason
    : error.name === 'TimeoutError' ? 'action_timeout' : 'action_failed';
  // No raw Playwright error/call log, DOM preview, fingerprint or handle escapes.
  return {ok: false, reason};
}
}
