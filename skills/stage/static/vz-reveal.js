/* vz-reveal.js — plays a map or a lane sequence (svg.vz) one step at a time.

   Markup, as visuals/player.py writes it:
     <div class="vz-player" data-vz-player>
       <div class="vz-stage"><svg class="vz" …>…</svg></div>
       a JSON script element with class vz-steps: {"build": [{title, text}…], "route": [{title, text}…]}
     </div>
   The script adds the controls: a button per mode the diagram has (Whole, Build, Route), Previous,
   numbered step buttons, Next, Play, and a checkbox for outlines of what is still to come. The arrow
   keys move while the player has focus. A diagram is complete at rest: it starts whole, and a mode is
   something the reader starts.

   Each part says when it appears: data-b (build step) or data-r (route step). In a mode, a later part
   is .fut (hidden, or an outline), the current step's parts are .now (accent colour, arrows drawn in),
   and the svg carries mode-build or mode-route, which vz.css reads to show route arrows and dim the
   parts a route never touches. Nothing here reads the diagram's words, so it cannot run them. */
(() => {
  const still = matchMedia('(prefers-reduced-motion: reduce)');

  function esc(t) {
    return String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  }

  function button(label, cls) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    if (cls) b.className = cls;
    return b;
  }

  function setup(root) {
    const svg = root.querySelector('svg.vz');
    if (!svg || root.dataset.vzReady) return;
    root.dataset.vzReady = '1';
    let caps = {};
    try { caps = JSON.parse(root.querySelector('script.vz-steps')?.textContent || '{}'); } catch (e) { caps = {}; }
    const parts = [...svg.querySelectorAll('[data-p]')];
    const last = { build: 0, route: 0 };
    parts.forEach(el => {
      if (el.dataset.b) last.build = Math.max(last.build, +el.dataset.b);
      if (el.dataset.r) last.route = Math.max(last.route, +el.dataset.r);
      if (el.hasAttribute('marker-end')) el.dataset.mk = el.getAttribute('marker-end');
    });
    const onMarker = svg.querySelector('marker[id$="-on"]')?.id;
    const modes = [];
    if (last.build) modes.push(['build', caps.buildLabel || 'Build it up']);
    if (last.route) modes.push(['route', caps.routeLabel || (svg.dataset.vz === 'sequence' ? 'Step through' : 'Follow the request')]);
    if (!modes.length) return;

    const bar = document.createElement('div');
    bar.className = 'vz-bar';
    const modeBox = document.createElement('div');
    modeBox.className = 'vz-modes';
    const whole = button('Whole picture', 'vz-mode');
    modeBox.appendChild(whole);
    const modeBtns = modes.map(([m, label]) => { const b = button(label, 'vz-mode'); b.dataset.mode = m; modeBox.appendChild(b); return b; });
    const ctl = document.createElement('div');
    ctl.className = 'vz-ctl';
    const prev = button('Previous');
    const chips = document.createElement('div');
    chips.className = 'vz-chips';
    const next = button('Next', 'vz-primary');
    const play = button('Play');
    const opt = document.createElement('label');
    opt.className = 'vz-opt';
    opt.innerHTML = '<input type="checkbox" checked> Outline what is still to come';
    ctl.append(prev, chips, next, play, opt);
    bar.append(modeBox, ctl);
    const cap = document.createElement('div');
    cap.className = 'vz-cap';
    cap.innerHTML = '<span class="vz-n"></span><strong></strong><p></p>';
    root.append(bar, cap);
    svg.classList.add('outline');

    let mode = null, cur = 0, timer = null;

    function draw(el) {
      if (still.matches || el.classList.contains('dash') || !el.getTotalLength) return;
      const len = el.getTotalLength();
      el.style.strokeDasharray = len; el.style.strokeDashoffset = len;
      el.getBoundingClientRect();
      el.classList.add('draw'); el.style.strokeDashoffset = 0;
      setTimeout(() => { el.style.strokeDasharray = ''; el.style.strokeDashoffset = ''; el.classList.remove('draw'); }, 800);
    }

    function paint(fwd) {
      svg.classList.remove('mode-build', 'mode-route');
      const key = mode === 'build' ? 'b' : 'r';
      parts.forEach(el => {
        el.classList.remove('fut', 'now');
        if (el.dataset.mk) el.setAttribute('marker-end', el.dataset.mk);
        if (!mode) return;
        const s = el.dataset[key];
        if (s === undefined) return;
        if (+s > cur) el.classList.add('fut');
        if (+s === cur) {
          el.classList.add('now');
          if (el.dataset.mk && onMarker) el.setAttribute('marker-end', `url(#${onMarker})`);
          if (fwd && el.matches('.ar')) draw(el);
          if (fwd) el.querySelectorAll?.('.ar').forEach(draw);
        }
      });
      if (mode) svg.classList.add('mode-' + mode);
      whole.setAttribute('aria-pressed', String(!mode));
      modeBtns.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
      ctl.hidden = !mode;
      const n = mode ? last[mode] : 0;
      if (chips.childElementCount !== n + 1 || chips.dataset.mode !== mode) {
        chips.innerHTML = '';
        chips.dataset.mode = mode || '';
        for (let i = 0; i <= n; i++) {
          const b = button(String(i));
          b.addEventListener('click', () => { stop(); go(i); });
          chips.appendChild(b);
        }
      }
      [...chips.children].forEach((b, i) => {
        b.classList.toggle('cur', i === cur);
        b.classList.toggle('seen', i < cur);
        const c = mode && (caps[mode] || [])[i - 1];
        b.setAttribute('aria-label', i ? `Step ${i}${c ? ': ' + c.title : ''}` : 'Start');
      });
      prev.disabled = cur === 0;
      next.disabled = cur === n;
      const c = mode && cur ? (caps[mode] || [])[cur - 1] : null;
      cap.hidden = !mode;
      cap.querySelector('.vz-n').textContent = mode ? (cur ? `Step ${cur} of ${n}` : 'Start') : '';
      cap.querySelector('strong').textContent = c ? c.title : (mode && !cur ? (caps[mode + 'Start'] || 'Press Next to begin.') : '');
      cap.querySelector('p').innerHTML = c && c.text ? esc(c.text) : '';
    }

    function go(n) {
      const fwd = n === cur + 1;
      cur = Math.max(0, Math.min(mode ? last[mode] : 0, n));
      paint(fwd);
    }
    function stop() { clearInterval(timer); timer = null; play.textContent = 'Play'; }
    function setMode(m) { stop(); mode = m; cur = 0; paint(false); }

    whole.addEventListener('click', () => setMode(null));
    modeBtns.forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
    next.addEventListener('click', () => { stop(); go(cur + 1); });
    prev.addEventListener('click', () => { stop(); go(cur - 1); });
    play.addEventListener('click', () => {
      if (timer) return stop();
      if (cur === last[mode]) go(0);
      play.textContent = 'Pause';
      timer = setInterval(() => { if (cur >= last[mode]) return stop(); go(cur + 1); }, 2600);
    });
    opt.querySelector('input').addEventListener('change', (e) => svg.classList.toggle('outline', e.target.checked));
    root.tabIndex = root.tabIndex >= 0 ? root.tabIndex : 0;
    root.addEventListener('keydown', (e) => {
      if (!mode || e.target.closest('input, textarea')) return;
      if (e.key === 'ArrowRight') { e.preventDefault(); stop(); go(cur + 1); }
      if (e.key === 'ArrowLeft') { e.preventDefault(); stop(); go(cur - 1); }
    });
    root.vz = { setMode, go, state: () => ({ mode, cur, last: mode ? last[mode] : 0 }) };
    paint(false);
    if (root.dataset.vzStart) {
      const [m, n] = root.dataset.vzStart.split(':');
      if (last[m]) { setMode(m); go(+n || 0); }
    }
  }

  function boot() { document.querySelectorAll('[data-vz-player]').forEach(setup); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
  window.vzReveal = { boot };
})();
