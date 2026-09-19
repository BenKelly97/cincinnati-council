/*
 * Suggest-a-title / flag-inaccurate widget.
 * Shared by index.html, alternative.html, and members.html so the logic
 * lives in one place. Each page just needs:
 *   1. <script src="suggest.js"></script> before its own closing </body>
 *   2. A `<div class="suggest-slot" data-f="..." data-t="..." data-legistar="..." data-page="...">`
 *      placed inside each card's template string (see integration notes).
 *   3. A call to `mountSuggestWidgets()` right after that page's own
 *      `res.innerHTML = ...` render step, so newly-rendered slots get
 *      the button/form attached (cards are re-rendered on every filter
 *      change, so this has to run every time, not just once on load).
 *
 * ============================================================================
 * FILL THESE IN after creating the Google Form (see SETUP.md for exact steps
 * and how to find each entry ID). Nothing here works until you do.
 * ============================================================================
 */
const SUGGEST_FORM_ACTION = 'https://docs.google.com/forms/d/e/1FAIpQLScl7dMVVwZ8JgCcDJcXuTmEB81p3pvIuL8jVM_rpjr8-2pEWw/formResponse';
const SUGGEST_ENTRY = {
  fileNumber:     'entry.2126325988',
  currentTitle:   'entry.699636265',
  legistarUrl:    'entry.918148672',
  suggestionType: 'entry.1423495741',
  suggestedTitle: 'entry.1576642602',
  comment:        'entry.82458550',
  sourcePage:     'entry.1327166660',
};
/* ========================================================================= */

(function () {
  const STYLE = `
    .suggest-slot{margin-top:10px}
    .suggest-trigger{
      background:none;border:none;padding:0;cursor:pointer;
      font-size:12px;color:var(--text3,#888);text-decoration:underline;
      text-underline-offset:2px;
    }
    .suggest-trigger:hover{color:var(--accent,#2563eb)}
    .suggest-form{
      margin-top:8px;padding:12px;border:1px solid var(--border,#ddd);
      border-radius:8px;background:var(--card-bg,var(--bg,#fafafa));
      font-size:13px;
    }
    .suggest-form label{display:block;font-weight:600;margin:8px 0 3px;color:var(--text,#111)}
    .suggest-form label:first-child{margin-top:0}
    .suggest-form select,.suggest-form input[type=text],.suggest-form textarea{
      width:100%;box-sizing:border-box;padding:6px 8px;border:1px solid var(--border,#ccc);
      border-radius:5px;font-size:13px;font-family:inherit;background:var(--bg,#fff);color:var(--text,#111);
    }
    .suggest-form textarea{min-height:50px;resize:vertical}
    .suggest-form .row{margin-top:8px}
    .suggest-form .actions{margin-top:10px;display:flex;gap:8px;align-items:center}
    .suggest-submit{
      background:var(--accent,#2563eb);color:#fff;border:none;border-radius:5px;
      padding:6px 14px;font-size:13px;cursor:pointer;font-weight:600;
    }
    .suggest-submit:disabled{opacity:0.6;cursor:default}
    .suggest-cancel{background:none;border:none;color:var(--text3,#888);font-size:13px;cursor:pointer}
    .suggest-note{font-size:11px;color:var(--text3,#888);margin-top:4px}
    .suggest-done{font-size:13px;color:var(--text,#111);padding:4px 0}
  `;

  function ensureStyle() {
    if (document.getElementById('suggest-widget-style')) return;
    const s = document.createElement('style');
    s.id = 'suggest-widget-style';
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  function escapeHtml(str) {
    return String(str || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function buildForm(slot) {
    const f = slot.dataset.f || '';
    const t = slot.dataset.t || '';
    const form = document.createElement('div');
    form.className = 'suggest-form';
    form.innerHTML = `
      <label>What's wrong?</label>
      <select class="s-type">
        <option value="Suggest better title">Suggest a better title</option>
        <option value="Flag inaccurate">Flag this title as inaccurate</option>
      </select>
      <div class="row">
        <label>Suggested title <span style="font-weight:400;color:var(--text3,#888)">(optional)</span></label>
        <input type="text" class="s-title" maxlength="300" placeholder="${escapeHtml(t)}">
      </div>
      <div class="row">
        <label>Why? <span style="font-weight:400;color:var(--text3,#888)">(optional)</span></label>
        <textarea class="s-comment" maxlength="1000" placeholder="What's inaccurate, missing, or unclear?"></textarea>
      </div>
      <div class="actions">
        <button type="button" class="suggest-submit">Submit</button>
        <button type="button" class="suggest-cancel">Cancel</button>
      </div>
      <div class="suggest-note">Goes to the site admins for review — not published automatically.</div>
    `;

    form.querySelector('.suggest-cancel').addEventListener('click', (e) => {
      e.stopPropagation();
      form.remove();
      slot.querySelector('.suggest-trigger').style.display = '';
    });

    form.querySelector('.suggest-submit').addEventListener('click', async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.textContent = 'Submitting…';

      const params = new URLSearchParams();
      params.set(SUGGEST_ENTRY.fileNumber, slot.dataset.f || '');
      params.set(SUGGEST_ENTRY.currentTitle, slot.dataset.t || '');
      params.set(SUGGEST_ENTRY.legistarUrl, slot.dataset.legistar || '');
      params.set(SUGGEST_ENTRY.suggestionType, form.querySelector('.s-type').value);
      params.set(SUGGEST_ENTRY.suggestedTitle, form.querySelector('.s-title').value);
      params.set(SUGGEST_ENTRY.comment, form.querySelector('.s-comment').value);
      params.set(SUGGEST_ENTRY.sourcePage, slot.dataset.page || '');

      try {
        // no-cors: Google Forms doesn't send CORS headers on formResponse,
        // so the response is opaque and we can't check status. A network
        // exception (offline, blocked, bad URL) is still catchable.
        await fetch(SUGGEST_FORM_ACTION, { method: 'POST', mode: 'no-cors', body: params });
        form.innerHTML = '<div class="suggest-done">Thanks — sent for review.</div>';
      } catch (err) {
        btn.disabled = false;
        btn.textContent = 'Submit';
        const note = form.querySelector('.suggest-note');
        note.textContent = 'Something went wrong sending that — try again in a moment.';
        note.style.color = '#c0392b';
      }
    });

    return form;
  }

  function mountOne(slot) {
    if (slot.dataset.mounted === '1') return;
    slot.dataset.mounted = '1';
    ensureStyle();

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'suggest-trigger';
    trigger.textContent = 'Suggest a better title / flag as inaccurate';
    trigger.addEventListener('click', (e) => {
      e.stopPropagation(); // don't trigger the card's own expand/collapse
      trigger.style.display = 'none';
      slot.appendChild(buildForm(slot));
    });

    slot.appendChild(trigger);
  }

  // Exposed globally: call this after every render pass (initial load AND
  // every re-render triggered by search/filter), since innerHTML rewrites
  // wipe out any slots mounted before.
  window.mountSuggestWidgets = function () {
    document.querySelectorAll('.suggest-slot').forEach(mountOne);
  };
})();
