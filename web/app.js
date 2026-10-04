// Scoreboard phone display: Web Bluetooth client for pi/scoreboard_link.py.
// Shows the four digits the scoreboard is drawing (same glyphs, team colors and rainbow) as bold solid
// seven-segment digits, mirrored by default because the phone sits on top of the scoreboard facing the
// scorekeeper behind it. Day theme (white, dark digits) for noon sun; night theme (black, bright digits).
(() => {
  'use strict';
  const P = window.ScoreboardProtocol;
  const VERSION = '1.2.0';
  const NS = 'http://www.w3.org/2000/svg';
  const $ = (sel) => document.querySelector(sel);

  // ---- settings (per phone, in localStorage) ---------------------------------------------------------
  const SETTINGS_KEY = 'scoreboard.settings';
  const DEFAULTS = { layout: 'behind', colorStyle: 'digits', theme: 'day', wakeLock: true, scoreButtons: true, autoReconnect: false };
  let settings = { ...DEFAULTS };
  try { settings = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') }; } catch (e) { /* defaults */ }
  function saveSettings() {
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch (e) { /* private mode */ }
  }

  // ---- bold seven-segment digits -------------------------------------------------------------------------
  // Segment A..G centerlines [x1, y1, x2, y2] in a 100 x 180 digit, in the direction the scoreboard's LEDs run
  // (a rainbow digit sweeps its hue along each segment, so the gradient follows the same direction).
  const SEGMENTS = [
    [9, 171, 9, 90],     // A lower left
    [9, 90, 9, 9],       // B upper left
    [9, 9, 91, 9],       // C top
    [91, 9, 91, 90],     // D upper right
    [91, 90, 9, 90],     // E middle
    [91, 90, 91, 171],   // F lower right
    [91, 171, 9, 171],   // G bottom
  ];
  const THICK = 18;        // segment thickness
  const GAP = 2.5;         // gap between segments
  const DIGIT_PITCH = 122;

  function segmentPoints([x1, y1, x2, y2], dx) {
    const h = THICK / 2;
    if (y1 === y2) {
      const a = Math.min(x1, x2) + GAP + dx, b = Math.max(x1, x2) - GAP + dx, y = y1;
      return [[a, y], [a + h, y - h], [b - h, y - h], [b, y], [b - h, y + h], [a + h, y + h]];
    }
    const a = Math.min(y1, y2) + GAP, b = Math.max(y1, y2) - GAP, x = x1 + dx;
    return [[x, a], [x + h, a + h], [x + h, b - h], [x, b], [x - h, b - h], [x - h, a + h]];
  }

  function buildDigits(svg, id) {
    svg.innerHTML = '';
    const defs = document.createElementNS(NS, 'defs');
    defs.innerHTML = `<filter id="glow-${id}" x="-15%" y="-15%" width="130%" height="130%">
      <feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;
    svg.appendChild(defs);
    const group = document.createElementNS(NS, 'g');
    svg.appendChild(group);
    const segments = [];
    for (let d = 0; d < 2; d++) {
      const digit = [];
      SEGMENTS.forEach((line, s) => {
        // every segment gets its own gradient (along the LED direction); solid colors use two equal stops
        const grad = document.createElementNS(NS, 'linearGradient');
        grad.id = `g-${id}-${d}-${s}`;
        grad.setAttribute('gradientUnits', 'userSpaceOnUse');
        grad.setAttribute('x1', line[0] + d * DIGIT_PITCH); grad.setAttribute('y1', line[1]);
        grad.setAttribute('x2', line[2] + d * DIGIT_PITCH); grad.setAttribute('y2', line[3]);
        const stops = [0, 1].map((o) => {
          const stop = document.createElementNS(NS, 'stop');
          stop.setAttribute('offset', o);
          grad.appendChild(stop);
          return stop;
        });
        defs.appendChild(grad);
        const poly = document.createElementNS(NS, 'polygon');
        poly.setAttribute('points', segmentPoints(line, d * DIGIT_PITCH).map((p) => p.join(',')).join(' '));
        group.appendChild(poly);
        digit.push({ poly, stops, gradUrl: `url(#${grad.id})` });
      });
      segments.push(digit);
    }
    return { group, segments, glowUrl: `url(#glow-${id})` };
  }

  const sides = ['left', 'right'].map((pos) => {
    const el = $(`#side-${pos}`);
    return { el, label: el.querySelector('.team-label'), ...buildDigits(el.querySelector('svg'), pos) };
  });

  // ---- color: keep the team color, but always readable on the current background ---------------------
  const rgb = ([r, g, b]) => `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`;
  const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const relLum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);

  // Day: darken until the contrast against white is at least ~4.5:1 (relative luminance <= 0.18)
  function forLightBackground(c) {
    let out = c.slice();
    for (let i = 0; i < 40 && relLum(out) > 0.18; i++) out = out.map((v) => v * 0.93);
    return out;
  }
  // Night: lighten toward white only until it stands out on black (relative luminance >= 0.12), so pure blue
  // stays clearly blue instead of washing out to white
  function forDarkBackground(c) {
    let out = c.slice();
    for (let i = 0; i < 40 && relLum(out) < 0.12; i++) out = out.map((v) => v + (255 - v) * 0.08);
    return out;
  }

  const RAINBOW_HUES = [0, 32, 64, 96, 128, 160, 192, 224, 255];

  // The scoreboard's own color for a segment end (0 or 1), then adapted to the theme
  function segmentColor(colorCode, s, end, theme) {
    if (colorCode === P.COLOR_WHITE || colorCode > P.COLOR_RAINBOW) return theme === 'day' ? [17, 17, 17] : [255, 255, 255];
    const c = P.ledColor(colorCode, s, end ? 8 : 0);
    return theme === 'day' ? forLightBackground(c) : forDarkBackground(c);
  }

  // A swatch of the raw team color for backgrounds and the color bar
  function teamSwatch(colorCode) {
    if (colorCode === P.COLOR_RAINBOW) {
      return { css: `linear-gradient(120deg, ${RAINBOW_HUES.map((h) => rgb(P.ledRgb(P.rainbowHue(h)))).join(', ')})`, solid: null, lum: 0.3 };
    }
    const c = colorCode === P.COLOR_WHITE || colorCode > P.COLOR_RAINBOW ? [240, 240, 240] : P.ledRgb(P.rainbowHue(colorCode));
    return { css: rgb(c), solid: c, lum: relLum(c) };
  }

  function setStop(stop, color) {
    if (stop.__c !== color) { stop.setAttribute('stop-color', color); stop.__c = color; }
  }
  function setAttr(el, name, value) {
    const key = '__' + name;
    if (el[key] !== value) { el.setAttribute(name, value); el[key] = value; }
  }

  function renderSide(side, team, glyphs, colorCode) {
    const theme = settings.theme;
    const bgStyle = settings.colorStyle === 'background';
    const swatch = teamSwatch(colorCode);
    side.label.textContent = team.toUpperCase();
    side.el.style.setProperty('--team', swatch.css);

    let ink = null;      // single color for all lit segments (background style), else per-segment team colors
    let ghost;
    if (bgStyle) {
      side.el.style.background = swatch.css;
      const dark = swatch.lum > 0.3;     // light team color: black digits; dark or saturated: white digits
      ink = dark ? '#000' : '#fff';
      ghost = dark ? 'rgba(0,0,0,0.10)' : 'rgba(255,255,255,0.13)';
      side.label.style.color = ink;
    } else {
      side.el.style.background = '';
      ghost = theme === 'day' ? 'rgba(0,0,0,0.055)' : 'rgba(255,255,255,0.07)';
      side.label.style.color = swatch.solid ? rgb(theme === 'day' ? forLightBackground(swatch.solid) : forDarkBackground(swatch.solid))
        : (theme === 'day' ? '#111' : '#fff');
    }
    // soft glow only at night (in sunlight it just blurs the edges)
    setAttr(side.group, 'filter', theme === 'night' && !bgStyle ? side.glowUrl : 'none');

    for (let d = 0; d < 2; d++) {
      const glyph = glyphs[d];
      const segsOn = glyph >= 0 && glyph < P.DIGIT_TABLE.length ? P.DIGIT_TABLE[glyph] : null;
      for (let s = 0; s < 7; s++) {
        const seg = side.segments[d][s];
        if (!(segsOn && segsOn[s])) { setAttr(seg.poly, 'fill', ghost); continue; }
        if (ink) { setAttr(seg.poly, 'fill', ink); continue; }
        setStop(seg.stops[0], rgb(segmentColor(colorCode, s, 0, theme)));
        setStop(seg.stops[1], rgb(segmentColor(colorCode, s, 1, theme)));
        setAttr(seg.poly, 'fill', seg.gradUrl);
      }
    }
  }

  // ---- state -> screen ------------------------------------------------------------------------------------
  let state = null;          // last decoded state
  let lastEventSeq = null;   // to spot new events (null right after connecting: no toast for old events)

  function applyTheme() {
    document.body.classList.toggle('theme-day', settings.theme === 'day');
    document.body.classList.toggle('theme-night', settings.theme !== 'day');
    document.querySelector('meta[name="theme-color"]').setAttribute('content', settings.theme === 'day' ? '#ffffff' : '#000000');
    $('#btn-theme').setAttribute('aria-label', settings.theme === 'day' ? 'Switch to night mode' : 'Switch to day mode');
  }

  function render() {
    applyTheme();
    const board = $('#board');
    board.classList.toggle('bg-style', settings.colorStyle === 'background');
    board.classList.toggle('no-score-buttons', !settings.scoreButtons);
    const s = state || { digits: [-1, -1, -1, -1], homeColor: P.COLOR_WHITE, awayColor: P.COLOR_WHITE, mode: 0, scoreTo: 21 };
    const order = settings.layout === 'front' ? ['home', 'away'] : ['away', 'home'];
    order.forEach((team, i) => {
      const glyphs = team === 'home' ? s.digits.slice(0, 2) : s.digits.slice(2, 4);
      renderSide(sides[i], team, glyphs, team === 'home' ? s.homeColor : s.awayColor);
      sides[i].team = team;
    });
    if (state) {
      $('#game-info').textContent = state.mode === 1 ? 'Tennis' : `Volleyball · game to ${state.scoreTo}`;
      $('#score-text').textContent = `Home ${state.home}, Away ${state.away}`;
      const gp = $('#gesture-pill');
      gp.hidden = false;
      gp.className = 'pill ' + (state.tposeOn ? 'ok' : 'off');
      gp.setAttribute('aria-pressed', String(!!state.tposeOn));
      gp.disabled = !canSend();
      gp.title = (state.tposeOn ? 'T-Pose Detection is ON: a T-pose gives +1 and hands on head gives −1. Tap to turn it off.'
                                : 'T-Pose Detection is OFF: gestures are ignored (the camera still records them). Tap to turn it on.') +
                 (state.piOn ? '' : ' (The Pi is not connected right now.)');
    }
    document.querySelectorAll('.score-btn').forEach((b) => { b.disabled = !canSend(); });
    syncBoardSettings();
  }

  // ---- scoreboard settings: sport and volleyball game-to, sent to the Arduino through the Pi --------------
  let boardNote = '';
  function syncBoardSettings() {
    const canSend = demo || (connected && !!commandChar);
    document.querySelectorAll('#board-settings [data-cmd]').forEach((btn) => {
      const name = btn.dataset.cmd, value = Number(btn.dataset.value);
      const current = !state ? null : name === 'MODE' ? state.mode : name === 'SOUND' ? state.soundMode : state.scoreTo;
      btn.classList.toggle('on', current === value);
      btn.disabled = !canSend || (name === 'TO' && state && state.mode === 1);
    });
    $('#board-settings-note').textContent = boardNote ||
      (canSend ? '(changes the scoreboard)' : connected ? '(update the Pi service to change these)' : '(connect to change)');
  }

  function canSend() { return demo || (connected && !!commandChar); }

  // The Pi disconnects phones that don't say hello within a few seconds (keeps other Bluetooth apps out)
  function sayHello() {
    if (demo || !connected || !commandChar) return;
    writeCommand(P.helloText()).catch(() => {});
  }
  setInterval(sayHello, 30000);
  setTimeout(sayHello, 2500);   // once more shortly after connecting, in case the first write was lost

  // Some browsers (Bluefy on iPhone) stop delivering notifications: if the score goes quiet, poll it with reads
  // and try to re-subscribe, so the display keeps working either way.
  let recovering = false;
  let lastResubscribe = 0;
  setInterval(async () => {
    if (!connected || !stateChar || recovering || Date.now() - lastPacketAt < 3500) return;
    recovering = true;
    try {
      onPacket(await withTimeout(stateChar.readValue(), 3000));
      if (Date.now() - lastResubscribe > 10000) {
        lastResubscribe = Date.now();
        try { await stateChar.stopNotifications(); } catch (_) { /* already stopped */ }
        await stateChar.startNotifications();
      }
    } catch (e) { /* try again next second */ } finally { recovering = false; }
  }, 1000);

  // One write at a time: Web Bluetooth rejects overlapping GATT operations, and fast taps on + would collide
  let writeChain = Promise.resolve();
  function writeCommand(text) {
    const bytes = new TextEncoder().encode(text);
    const job = writeChain.then(() => {
      if (commandChar.properties && commandChar.properties.writeWithoutResponse && commandChar.writeValueWithoutResponse) {
        return withTimeout(commandChar.writeValueWithoutResponse(bytes), 4000);
      }
      return withTimeout(commandChar.writeValueWithResponse(bytes), 4000);
    });
    writeChain = job.catch(() => {});
    return job;
  }

  // + / - under each team: the scoreboard changes its score exactly as if its own button was pressed
  document.querySelectorAll('.score-btn').forEach((btn) => btn.addEventListener('click', async () => {
    const side = sides.find((x) => x.el === btn.closest('.side'));
    if (!side || !side.team || !canSend()) return;
    const code = (side.team === 'home' ? 'H' : 'A') + btn.dataset.act;   // HU HD AU AD
    if (navigator.vibrate) navigator.vibrate(15);
    if (demo) { applyDemoCommand('SCORE', code); return; }
    try { await writeCommand(P.commandText('SCORE', code)); }
    catch (e) { toast('NOT SENT', e.message); }
  }));

  // T-Pose Detection switch (handled by the Pi: when off, the camera still sees gestures but they don't score)
  $('#gesture-pill').addEventListener('click', async () => {
    if (!state || !canSend()) return;
    const turnOn = !state.tposeOn;
    if (demo) { applyDemoCommand('TPOSE', turnOn ? 1 : 0); return; }
    try { await writeCommand(P.commandText('TPOSE', turnOn ? 1 : 0)); }
    catch (e) { toast('NOT SENT', e.message); }
  });

  async function sendBoardSetting(btn) {
    const name = btn.dataset.cmd, value = Number(btn.dataset.value);
    if (state && (name === 'MODE' ? state.mode : state.scoreTo) === value) return;
    if (name === 'MODE' && !confirm(`Switch the scoreboard to ${value ? 'tennis' : 'volleyball'}? This resets the score to 0–0.`)) return;
    const text = P.commandText(name, value);
    if (demo) { applyDemoCommand(name, value); return; }
    if (!connected || !commandChar) return;
    btn.classList.add('sending');
    try {
      await writeCommand(text);   // write-without-response when offered: the scoreboard's own update confirms it
      boardNote = '';   // the scoreboard's own state update confirms it
    } catch (e) {
      boardNote = '(not sent: ' + e.message + ')';
    } finally {
      btn.classList.remove('sending');
      syncBoardSettings();
    }
  }
  document.querySelectorAll('#board-settings [data-cmd]').forEach((btn) =>
    btn.addEventListener('click', () => sendBoardSetting(btn)));

  const EVENT_TEXT = {
    HU: ['home', '+1', 'button'], HD: ['home', '−1', 'button'],
    AU: ['away', '+1', 'button'], AD: ['away', '−1', 'button'],
    HP: ['home', '+1', 'T-pose'], AP: ['away', '+1', 'T-pose'],
    HC: ['home', '−1', 'cobra'], AC: ['away', '−1', 'cobra'],
    HW: ['home', 'WINS!', ''], AW: ['away', 'WINS!', ''],
  };

  let toastTimer = null;
  function toast(main, sub, colorCode) {
    const t = $('#toast');
    t.querySelector('.toast-main').textContent = main;
    t.querySelector('.toast-sub').textContent = sub || '';
    const sw = colorCode === undefined ? null : teamSwatch(colorCode);
    t.style.borderColor = sw && sw.solid ? rgb(sw.solid) : '';
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
  }

  function announce(s) {
    const e = EVENT_TEXT[s.event];
    if (e) {
      const [team, what, how] = e;
      const color = team === 'home' ? s.homeColor : s.awayColor;
      toast(`${team.toUpperCase()} ${what}`, how, color);
      const side = sides.find((x) => x.team === team);
      if (side) { side.el.classList.remove('flash'); void side.el.offsetWidth; side.el.classList.add('flash'); }
    } else if (s.event === 'RS') toast('RESET', '0 – 0');
    else if (s.event === 'GT') toast(`GAME TO ${s.scoreTo}`);
    else if (s.event === 'SM') toast('SOUND', ['effects', 'voice: point home / away', 'tones'][s.soundMode] || '');
    else if (s.event === 'MD') toast(s.mode === 1 ? 'TENNIS' : 'VOLLEYBALL', 'scoring mode');
  }

  // ---- game clock: starts at the first point after 0-0, freezes when the game is won, resets at 0-0 ------
  const CLOCK_KEY = 'scoreboard-clock-v1';
  const CLOCK_MAX_AGE_MS = 6 * 3600 * 1000;
  let clock = { start: null, frozen: null, approx: false };
  try {
    const saved = JSON.parse(localStorage.getItem(CLOCK_KEY) || 'null');
    if (saved && saved.start && Date.now() - saved.start < CLOCK_MAX_AGE_MS) clock = saved;
  } catch (e) { /* no saved clock */ }
  function saveClock() {
    try { localStorage.setItem(CLOCK_KEY, JSON.stringify(clock)); } catch (e) { /* private mode */ }
  }
  function updateClockState(s, isNew) {
    const zero = s.home === 0 && s.away === 0;
    if (zero) {
      if (clock.start !== null || clock.frozen !== null) { clock = { start: null, frozen: null, approx: false }; saveClock(); }
    } else if (clock.start === null) {
      // first point seen; if we connected mid-game the true start is unknown, so mark it approximate
      clock = { start: Date.now(), frozen: null, approx: !clockSawZero };
      saveClock();
    }
    clockSawZero = zero || clockSawZero;
    if (isNew && clock.start !== null) {
      if (s.event === 'HW' || s.event === 'AW') { if (clock.frozen === null) { clock.frozen = Date.now() - clock.start; saveClock(); } }
      else if (clock.frozen !== null) { clock.frozen = null; saveClock(); }   // winning point was undone
    }
    renderClock();
  }
  let clockSawZero = false;
  function renderClock() {
    const el = $('#game-clock');
    if (!state) { el.hidden = true; return; }
    el.hidden = false;
    const ms = clock.start === null ? 0 : (clock.frozen !== null ? clock.frozen : Date.now() - clock.start);
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), sec = total % 60;
    const text = h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`;
    el.textContent = (clock.approx && clock.start !== null ? '~' : '') + text;
    el.classList.toggle('idle', clock.start === null);
    el.classList.toggle('done', clock.frozen !== null);
  }
  setInterval(renderClock, 500);

  let prevTposeOn = null;
  function handleState(s) {
    if (prevTposeOn !== null && s.tposeOn !== prevTposeOn) {
      toast('T-POSE DETECTION ' + (s.tposeOn ? 'ON' : 'OFF'), s.tposeOn ? 'gestures score again' : 'gestures are ignored');
    }
    prevTposeOn = s.tposeOn;
    const isNew = lastEventSeq !== null && s.eventSeq !== lastEventSeq;
    lastEventSeq = s.eventSeq;
    state = s;
    updateClockState(s, isNew);
    lastPacketAt = Date.now();
    render();
    if (isNew) announce(s);
    updateStale();
  }

  // ---- connection status ------------------------------------------------------------------------------
  let lastPacketAt = 0;
  let linkTipText = 'Bluetooth not connected';
  function setLink(text, kind) {
    const pill = $('#link-pill');
    pill.className = 'pill pill-bt ' + (kind || '');
    pill.querySelector('.pill-text').textContent = text;
    linkTipText = text === 'Demo' ? 'Demo mode (no scoreboard)' : 'Bluetooth ' + text.charAt(0).toLowerCase() + text.slice(1);
    pill.title = linkTipText;
    pill.setAttribute('aria-label', linkTipText);
  }
  let linkTipTimer = null;
  $('#link-pill').addEventListener('click', () => {
    const tip = $('#link-tip');
    tip.textContent = linkTipText;
    tip.hidden = false;
    clearTimeout(linkTipTimer);
    linkTipTimer = setTimeout(() => { tip.hidden = true; }, 2500);
  });
  function updateStale() {
    const note = $('#stale-note');
    let msg = '';
    if (connected && Date.now() - lastPacketAt > 6000) msg = 'No updates from the Pi';
    else if ((connected || demo) && state && !state.fresh) msg = 'Scoreboard not sending (Arduino link)';
    note.hidden = !msg;
    note.textContent = msg;
    $('#board').classList.toggle('stale', !!msg);
    if (connected) setLink(msg ? 'Connected, no data' : 'Connected', msg ? 'warn' : 'ok');
  }
  setInterval(updateStale, 1000);

  function showOverlay(msg) {
    if (msg) $('#connect-msg').textContent = msg;
    $('#connect').hidden = false;
  }
  function hideOverlay() { $('#connect').hidden = true; }

  // ---- Web Bluetooth ------------------------------------------------------------------------------------------
  let device = null;
  let commandChar = null;   // write: sport / game-to settings (absent on an older Pi service)
  let stateChar = null;     // read + notify: the score packets
  let connected = false;
  let connecting = false;
  let wantConnection = false;
  let attempt = 0;
  let retryTimer = null;

  const withTimeout = (promise, ms) => Promise.race([promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('timed out')), ms))]);

  function useDevice(d) {
    if (device === d) return;
    if (device) {
      device.removeEventListener('gattserverdisconnected', onDisconnected);
      device.removeEventListener('advertisementreceived', onAdvertisement);
    }
    device = d;
    device.addEventListener('gattserverdisconnected', onDisconnected);
    device.addEventListener('advertisementreceived', onAdvertisement);
  }

  async function chooseDevice() {
    try {
      const d = await navigator.bluetooth.requestDevice({
        filters: [{ name: P.DEVICE_NAME }],
        optionalServices: [P.SERVICE_UUID],
      });
      useDevice(d);
      wantConnection = true;
      attempt = 0;
      connect();
    } catch (e) {
      if (e.name !== 'NotFoundError') showOverlay('Could not open the Bluetooth chooser: ' + e.message);
    }
  }

  async function connect() {
    if (!device || connecting || connected || !wantConnection) return;
    clearTimeout(retryTimer);
    connecting = true;
    setLink(attempt ? 'Reconnecting…' : 'Connecting…', 'busy');
    try {
      const server = await withTimeout(device.gatt.connect(), 15000);
      const service = await server.getPrimaryService(P.SERVICE_UUID);
      const chrc = await service.getCharacteristic(P.STATE_CHAR_UUID);
      stateChar = chrc;
      chrc.addEventListener('characteristicvaluechanged', onValueChanged); // same function: never added twice
      await chrc.startNotifications();
      try { commandChar = await service.getCharacteristic(P.COMMAND_CHAR_UUID); } catch (_) { commandChar = null; }
      lastEventSeq = null;     // don't replay the last event as if it just happened
      onPacket(await chrc.readValue());
      connected = true;
      attempt = 0;
      hideOverlay();
      setLink('Connected', 'ok');
      render();
      sayHello();
      requestWakeLock();
    } catch (e) {
      console.warn('connect failed:', e);
      try { device.gatt.disconnect(); } catch (_) { /* not connected */ }
      scheduleReconnect();
    } finally {
      connecting = false;
    }
  }

  function scheduleReconnect() {
    if (!wantConnection) return;
    if (!settings.autoReconnect) {   // manual mode: one clear message, no retry loop, no surprise pairing prompts
      wantConnection = false;
      connected = false;
      setLink('Not connected', 'bad');
      showOverlay('Disconnected. Tap Connect to reconnect.');
      return;
    }
    attempt++;
    setLink('Reconnecting…', 'busy');
    clearTimeout(retryTimer);
    retryTimer = setTimeout(connect, Math.min(1000 * 2 ** (attempt - 1), 10000));
    // Reconnect the moment the scoreboard is heard again, where the browser supports it
    if (settings.autoReconnect && device.watchAdvertisements && !device.watchingAdvertisements) device.watchAdvertisements().catch(() => {});
  }

  function onAdvertisement() {
    if (!connected && !connecting && wantConnection) connect();
  }

  function onDisconnected() {
    connected = false;
    commandChar = null;
    if (wantConnection) scheduleReconnect();
    else setLink('Not connected', 'bad');
  }

  function onValueChanged(ev) { onPacket(ev.target.value); }

  function onPacket(dataView) {
    try { handleState(P.decodeState(dataView)); } catch (e) { console.warn('bad packet', e); }
  }

  async function tryRememberedDevice() {
    // Chrome remembers devices this page was allowed to use (getDevices); then no chooser is needed
    if (!navigator.bluetooth || !navigator.bluetooth.getDevices) return false;
    try {
      const devices = await navigator.bluetooth.getDevices();
      const d = devices.find((x) => x.name === P.DEVICE_NAME) || devices[0];
      if (!d) return false;
      useDevice(d);
      wantConnection = true;
      showOverlay('Looking for the scoreboard…');
      connect();
      return true;
    } catch (e) { return false; }
  }

  function disconnect() {
    wantConnection = false;
    clearTimeout(retryTimer);
    if (device && device.gatt.connected) device.gatt.disconnect();
    connected = false;
    stopDemo();
    setLink('Not connected', 'bad');
    showOverlay('Disconnected.');
  }

  // ---- demo mode (no scoreboard needed) ----------------------------------------------------------------
  let demo = false;
  let demoTimer = null;
  const DEMO_COLORS = [[160, P.COLOR_RAINBOW], [0, 96], [P.COLOR_WHITE, 224], [32, 192]];
  let demoState = null;
  let demoRound = 0;

  function demoDigits(score) { return [score >= 10 ? Math.floor(score / 10) % 16 : -1, score % 10]; }
  function demoPublish(event) {
    const s = demoState;
    s.digits = [...demoDigits(s.home), ...demoDigits(s.away)];
    if (event) { s.event = event; s.eventSeq = (s.eventSeq + 1) & 0xff; }
    handleState({ ...s, digits: s.digits.slice() });
  }
  function demoStep() {
    const s = demoState;
    if (s.event === 'HW' || s.event === 'AW') {
      demoRound++;
      [s.homeColor, s.awayColor] = DEMO_COLORS[demoRound % DEMO_COLORS.length];
      s.home = s.away = 0;
      return demoPublish('RS');
    }
    const r = Math.random();
    const homeLeads = s.home >= s.away;
    const team = r < (homeLeads ? 0.55 : 0.45) ? 'H' : 'A';
    let ev = team + (Math.random() < 0.6 ? 'P' : 'U');
    if (Math.random() < 0.08 && (team === 'H' ? s.home : s.away) > 0) ev = team + 'C';
    if (ev[1] === 'C') { if (team === 'H') s.home--; else s.away--; }
    else if (team === 'H') s.home++; else s.away++;
    if ((s.home >= s.scoreTo || s.away >= s.scoreTo) && Math.abs(s.home - s.away) >= 2) {
      demoPublish(ev);
      setTimeout(() => demoPublish(s.home > s.away ? 'HW' : 'AW'), 900);
      return;
    }
    demoPublish(ev);
  }
  function startDemo() {
    demo = true;
    wantConnection = false;
    hideOverlay();
    setLink('Demo', 'ok');
    demoState = { piOn: true, tposeOn: true, soundMode: 0, fresh: true, home: 17, away: 15, mode: 0, scoreTo: 21,
      homeColor: DEMO_COLORS[0][0], awayColor: DEMO_COLORS[0][1], digits: [], event: 'BOOT', eventSeq: 0, ageSeconds: 0 };
    lastEventSeq = null;
    demoPublish();
    clearInterval(demoTimer);
    demoTimer = setInterval(demoStep, 2600);
    requestWakeLock();
  }
  function stopDemo() { demo = false; clearInterval(demoTimer); }
  function applyDemoCommand(name, value) {
    if (name === 'MODE') { demoState.mode = value; demoState.home = demoState.away = 0; demoPublish('MD'); }
    else if (name === 'TPOSE') { demoState.tposeOn = !!value; demoPublish(); }
    else if (name === 'SOUND') { demoState.soundMode = value; demoPublish('SM'); }
    else if (name === 'SCORE') {
      const key = value[0] === 'H' ? 'home' : 'away';
      demoState[key] = Math.max(0, demoState[key] + (value[1] === 'U' ? 1 : -1));
      demoPublish(value);
    }
    else { demoState.scoreTo = value; demoPublish('GT'); }
  }

  // ---- screen wake lock ---------------------------------------------------------------------------------
  let wakeLock = null;
  async function requestWakeLock() {
    if (!settings.wakeLock || !('wakeLock' in navigator) || wakeLock || document.visibilityState !== 'visible') return;
    try {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } catch (e) { /* battery saver, or not allowed */ }
  }
  function releaseWakeLock() { if (wakeLock) wakeLock.release().catch(() => {}); }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (connected || demo) requestWakeLock();
    if (!connected && wantConnection) connect();
  });

  // ---- settings dialog ----------------------------------------------------------------------------------
  const dialog = $('#settings');
  const form = dialog.querySelector('form');
  function syncForm() {
    form.layout.value = settings.layout;
    form.theme.value = settings.theme;
    form.colorStyle.value = settings.colorStyle;
    form.wakeLock.checked = settings.wakeLock;
    form.scoreButtons.checked = settings.scoreButtons;
    form.autoReconnect.checked = settings.autoReconnect;
    boardNote = '';
    syncBoardSettings();
    $('#btn-disconnect').hidden = !(connected || demo || wantConnection);
  }
  form.addEventListener('change', () => {
    settings.layout = form.layout.value;
    settings.theme = form.theme.value;
    settings.colorStyle = form.colorStyle.value;
    settings.wakeLock = form.wakeLock.checked;
    settings.scoreButtons = form.scoreButtons.checked;
    settings.autoReconnect = form.autoReconnect.checked;
    saveSettings();
    if (settings.wakeLock) requestWakeLock(); else releaseWakeLock();
    render();
  });
  $('#btn-settings').addEventListener('click', () => { syncForm(); dialog.showModal(); });
  $('#btn-disconnect').addEventListener('click', () => { dialog.close(); disconnect(); });
  $('#version').textContent = `v${VERSION} · source: github.com/jakabo27/Gesture-Controlled-Volleyball-Scoreboard`;

  // one tap between the sun theme and the stadium-lights theme
  $('#btn-theme').addEventListener('click', () => {
    settings.theme = settings.theme === 'day' ? 'night' : 'day';
    saveSettings();
    render();
  });

  $('#btn-fullscreen').addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen({ navigationUI: 'hide' }).catch(() => {});
  });

  // ---- start -------------------------------------------------------------------------------------------------
  $('#btn-demo').addEventListener('click', startDemo);
  $('#btn-connect').addEventListener('click', () => { stopDemo(); chooseDevice(); });

  render();
  setLink('Not connected', 'bad');

  // iPhone/iPad browsers (all WebKit) have no Web Bluetooth; the Bluefy app adds it
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  // no fullscreen API on iPhone: hide the button instead of showing one that does nothing
  if (!document.documentElement.requestFullscreen || isIOS) $('#btn-fullscreen').hidden = true;   // Bluefy's fullscreen leaves a grey overlay

  if (!navigator.bluetooth) {
    $('#btn-connect').disabled = true;
    $('#ios-help').hidden = !isIOS;
    // Bluefy's URL scheme: opens this same page inside the Bluefy app (not verified against Bluefy's docs)
    $('#open-bluefy').href = 'bluefy://open?url=' + encodeURIComponent(location.href.split('#')[0]);
    showOverlay(isIOS ? 'This browser can\'t use Bluetooth.' : 'This browser can\'t use Bluetooth. Open this page in Chrome on Android.');
  } else if (navigator.bluetooth.getAvailability) {
    navigator.bluetooth.getAvailability().then((ok) => {
      if (!ok) showOverlay('Turn on Bluetooth, then tap Connect.');
    }).catch(() => {});
  }

  if (new URLSearchParams(location.search).has('demo')) startDemo();
  else if (settings.autoReconnect) tryRememberedDevice();

  if ('serviceWorker' in navigator) {
    const hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.register('sw.js').catch(() => {});
    // A new version took over: reload to use it, but never while connected (a reload drops the Bluetooth link)
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (hadController && !connected && !connecting && !demo) location.reload();
    });
  }
})();
