/* MOSAIC dashboard: four pages over one /api/state poll. No libraries.
 * Wording comes from the server (feedback.py); this file only lays it out. */
(() => {
  "use strict";

  const POLL_MS = 1000;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PAGES = { live: "Live room", history: "History", sensors: "Sensors", setup: "Setup" };
  const OLD_PAGES = { overview: "live", map: "live" };  // Links from before the Live room
  const KICKER = { fine: "All good", heads_up: "Heads up", act_now: "Act now", none: "Waiting" };
  // Area looks on the Live room map (docs/ui_design.md): zone activity -> look
  const ACT_LOOK = { LECTURER: "speak", STILL: "settled", MOTION: "settled", TALKING: "talk", LOUD: "loud", NO_DATA: "none" };
  const LEVEL_LOOK = { fine: "settled", heads_up: "talk", act_now: "loud", none: "none" };
  const KEYS = {
    activity: [["speak", "Lecturer's voice"], ["settled", "Settled"], ["talk", "Talking"], ["loud", "Excessive noise"], ["none", "No signal"]],
    other: [["settled", "Fine"], ["talk", "Keep an eye on it"], ["loud", "Act now"], ["none", "No reading"]],
  };
  const LOUD_SPAN_MS = 120000;  // Loudness sparkline: last 2 minutes
  const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const LEVEL_ICON = { fine: "i-fine", heads_up: "i-alert", act_now: "i-stop", none: "i-none" };
  const LEVEL_WORD = { fine: "Fine", heads_up: "Keep an eye on it", act_now: "Act now", none: "No reading" };
  const MODE_LABEL = { LECTURE: "Lecture", DISCUSSION: "Group work", QUIET_WORK: "Quiet work" };
  const AUDIO = {
    background_noise: ["Background noise", "i-background"], speech: ["Speech", "i-discussion"],
    transient_noise: ["Sudden noise", "i-transient"], unknown: ["Not sure", "i-unsure"],
  };
  const STATUS = { online: ["Working", "i-check"], stale: ["Delayed", "i-clock"], offline: ["Not connected", "i-offline"] };
  const SOURCE = {
    simulated: ["Simulated", "All readings come from the simulator, not real sensors"],
    mixed: ["Partly simulated", "Some sensors are simulated: see the Sensors page"],
  };
  const CO2_LEVEL = { good: "Fresh", fair: "Getting stuffy", poor: "Stuffy", warmup: "Warming up", none: "—" };
  const DASHES = ["", "7 4", "2 4", "10 4 2 4"];  // Second cue besides colour
  const LINK_LABELS = { rssi: "Wi-Fi signal", loss: "Unrecovered message loss", rtt: "Round trip", age: "Last update" };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const announcer = $("#announcer");
  const alerter = $("#alerter");

  let state = null;
  let page = "live";
  let rangeS = 300;
  let mapMetric = "activity";
  let failures = 0;
  let lastHeadline = null;
  const seenAlerts = new Set();
  const hidden = new Set();
  const cards = new Map();

  const series = (id) => `var(--series-${((id - 1) % 6) + 1})`;
  const dash = (id) => DASHES[(id - 1) % DASHES.length];
  const fmt = (v, digits = 0) => (v == null ? "—" : v.toFixed(digits));
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const setIcon = (svg, id) => svg.querySelector("use").setAttribute("href", `#${id}`);
  const fb = () => state && state.feedback;

  function svg(tag, attrs, parent) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }
  function icon(id, cls = "icon") {
    const s = svg("svg", { class: cls, "aria-hidden": "true" });
    svg("use", { href: `#${id}` }, s);
    return s;
  }
  function make(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function levelLine(level, label, cls = "level-line") {
    const p = make("p", cls);
    p.dataset.level = level;
    p.append(icon(LEVEL_ICON[level] || LEVEL_ICON.none, `icon level-icon lvl-${level}`), make("span", "", label));
    return p;
  }
  function clockTime(ms) {
    return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  function ago(ms) {
    const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 60) return "just now";
    const m = Math.round(s / 60);
    return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
  }
  function minutesSince(ms) {
    const m = Math.floor((Date.now() - ms) / 60000);
    return m < 1 ? "less than a minute" : m === 1 ? "1 minute" : `${m} minutes`;
  }
  async function post(path, body = {}) {
    const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const reply = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(reply.error || "The request didn't go through. Try again.");
    return reply;
  }

  /* ---- Pages: #/live ... #/setup; Back/Forward and links work ---- */
  function route(fromUser) {
    const [raw, arg] = location.hash.replace(/^#\/?/, "").split("/");
    const id = OLD_PAGES[raw] || raw;
    page = PAGES[id] ? id : "live";
    if (raw === "map" && arg) selectedZone = decodeURIComponent(arg);
    $$(".page").forEach((s) => { s.hidden = s.dataset.page !== page; });
    $$(".pages a").forEach((a) => {
      if (a.dataset.page === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = `${PAGES[page]} · MOSAIC`;
    if (fromUser) {
      const h = $(`#h-${page}`);
      if (h) h.focus();  // Screen readers hear the new page; keyboard continues from here
      window.scrollTo(0, 0);
    }
    if (state) render();
  }
  window.addEventListener("hashchange", () => route(true));

  /* ---- Display settings ---- */
  function store(key, value) {
    try { if (value == null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (e) { /* Blocked */ }
  }
  const THEMES = { system: ["i-auto", "automatic"], light: ["i-sun", "light"], dark: ["i-moon", "dark"] };
  function applyTheme(mode) {
    const root = document.documentElement;
    if (mode === "system") delete root.dataset.theme; else root.dataset.theme = mode;
    store("mosaic-theme", mode === "system" ? null : mode);
    $$('input[name="theme"]').forEach((r) => { r.checked = r.value === mode; });
    const btn = $("#theme-btn");
    setIcon(btn, THEMES[mode][0]);
    btn.setAttribute("aria-label", `Theme: ${THEMES[mode][1]}. Change theme`);
    btn.title = `Theme: ${THEMES[mode][1]}`;
  }
  $$('input[name="theme"]').forEach((r) => r.addEventListener("change", () => applyTheme(r.value)));
  $("#theme-btn").addEventListener("click", () => {  // Automatic -> light -> dark
    const order = Object.keys(THEMES);
    const now = document.documentElement.dataset.theme || "system";
    const next = order[(order.indexOf(now) + 1) % order.length];
    applyTheme(next);
    announcer.textContent = `Theme: ${THEMES[next][1]}`;
  });
  applyTheme(document.documentElement.dataset.theme || "system");

  const techToggle = $("#tech-toggle");
  techToggle.checked = "tech" in document.documentElement.dataset;
  techToggle.addEventListener("change", () => {
    if (techToggle.checked) document.documentElement.dataset.tech = ""; else delete document.documentElement.dataset.tech;
    store("mosaic-tech", techToggle.checked ? "1" : null);
  });

  function setLive(mode) {
    $("#live").dataset.state = mode;
    $("#live-text").textContent = { live: "Live", lost: "Connection lost", connecting: "Connecting" }[mode];
  }

  /* Presenter mode: the room and one sentence, large. Button or the P key. */
  const presentBtn = $("#present-btn");
  function setPresent(on) {
    if (on) document.documentElement.dataset.present = ""; else delete document.documentElement.dataset.present;
    presentBtn.setAttribute("aria-pressed", String(on));
    store("mosaic-present", on ? "1" : null);
    if (on && page !== "live") location.hash = "#/live";
    if (state) render();  // The map changes height
  }
  presentBtn.addEventListener("click", () => {
    const on = !("present" in document.documentElement.dataset);
    setPresent(on);
    announcer.textContent = on ? "Presenter mode on" : "Presenter mode off";
  });
  presentBtn.setAttribute("aria-pressed", String("present" in document.documentElement.dataset));
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    const typing = t.closest && (t.closest("input, textarea, select, [contenteditable]") || t.closest("dialog[open]"));
    if (e.key === "Escape" && selectedZone && !document.querySelector("dialog[open]")) { closeZone(); return; }
    if ((e.key === "p" || e.key === "P") && !e.metaKey && !e.ctrlKey && !e.altKey && !typing) presentBtn.click();
  });

  /* Small motion helpers. Everything settles instantly when motion is reduced. */
  function replay(el, base) {  // Restart a keyframe animation by swapping two identical classes
    if (reduceMotion()) return;
    const wasA = el.classList.contains(`${base}-a`);
    el.classList.remove(`${base}-a`, `${base}-b`);
    el.classList.add(`${base}-${wasA ? "b" : "a"}`);
  }
  const tweens = new WeakMap();
  function countTo(el, value, format) {  // Numbers count to their new value over 0.8 s
    const from = tweens.get(el);
    if (value == null) { tweens.delete(el); el.textContent = "—"; return; }
    if (from == null || from.to === value || reduceMotion()) {
      if (from) cancelAnimationFrame(from.raf);
      tweens.set(el, { to: value, now: value });
      el.textContent = format(value);
      return;
    }
    cancelAnimationFrame(from.raf);
    const start = from.now, t0 = performance.now();
    const rec = { to: value, now: start, raf: 0 };
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 800);
      rec.now = start + (value - start) * (1 - (1 - k) ** 3);
      el.textContent = format(rec.now);
      if (k < 1) rec.raf = requestAnimationFrame(step);
    };
    rec.raf = requestAnimationFrame(step);
    tweens.set(el, rec);
  }
  function spark(svgEl, pts, lo, hi) {  // Sparkline in the svg's own viewBox; draws in the first time
    const line = $("polyline", svgEl);
    const [, , w, h] = svgEl.getAttribute("viewBox").split(" ").map(Number);
    if (pts.length < 2) { line.setAttribute("points", ""); return; }
    const t0 = pts[0][0], t1 = pts[pts.length - 1][0] || t0 + 1;
    const span = Math.max(1, t1 - t0), range = Math.max(1e-6, hi - lo);
    line.setAttribute("points", pts.map(([t, v]) =>
      `${(((t - t0) / span) * w).toFixed(1)},${(h - 2 - clamp((v - lo) / range, 0, 1) * (h - 4)).toFixed(1)}`).join(" "));
    line.setAttribute("pathLength", "1");
    if (!svgEl.dataset.drawn) { svgEl.dataset.drawn = "1"; svgEl.classList.add("draw"); }
  }

  /* ---- Header + alert banners (every page) ---- */
  function renderHeader() {
    const f = fb();
    const pill = $("#sensors-pill");
    const sensors = f ? f.sensors : { text: state.nodes.length ? "Sensors connected" : "No sensors connected yet", level: "none" };
    pill.dataset.level = sensors.level;
    setIcon($("svg", pill), LEVEL_ICON[sensors.level] || LEVEL_ICON.none);
    $("#sensors-text").textContent = sensors.text;

    const source = $("#source");
    source.hidden = !SOURCE[state.source];
    if (!source.hidden) {
      $("#source-text").textContent = SOURCE[state.source][0];
      source.title = SOURCE[state.source][1];
    }
  }

  function renderBanners() {
    const alerts = state.alerts || { banner: [], hidden: 0 };
    // On the Live room the alert sits in the side column, next to the map; elsewhere on top.
    const box = page === "live" ? $("#alert-slot") : $("#banners");
    const other = page === "live" ? $("#banners") : $("#alert-slot");
    if (other.childElementCount) { other.replaceChildren(); delete other.dataset.key; }
    $(".brand").toggleAttribute("data-alert", alerts.banner.some((a) => a.level === "act_now"));
    // Rebuild only when the alerts change, so focus on "Hide" survives the refresh.
    const key = alerts.banner.map((a) => `${a.id}:${a.message}`).join("|");
    if (box.dataset.key === key) {
      box.querySelectorAll(".banner-time").forEach((p, i) => {
        const a = alerts.banner[i];
        p.textContent = `Started ${clockTime(a.started_ms)} · ${minutesSince(a.started_ms)} ago`;
      });
    } else {
      box.dataset.key = key;
      box.replaceChildren(...alerts.banner.map((a) => {
      const card = make("div", "banner");
      card.dataset.level = a.level;
      const text = make("div", "banner-text");
      text.append(make("p", "banner-message", a.message), make("p", "banner-action", a.action),
                  make("p", "banner-time", `Started ${clockTime(a.started_ms)} · ${minutesSince(a.started_ms)} ago`));
      const hide = make("button", "btn", "Hide for 10 min");
      hide.type = "button";
      hide.setAttribute("aria-label", `Hide "${a.message}" for 10 minutes`);
      hide.addEventListener("click", async () => {
        hide.disabled = true;
        try {
          await post(`/api/alerts/${a.id}/hide`);
          announcer.textContent = "Alert hidden for 10 minutes. It stays in the history.";
          poll(true);
        } catch (e) { hide.disabled = false; }
      });
      const head = make("div", "banner-head");
      head.append(icon("i-stop", "icon banner-icon"), text);
      card.append(head, hide);
      return card;
    }));
    }
    // A new act-now alert is announced once, assertively.
    for (const a of alerts.banner) {
      if (!seenAlerts.has(a.id)) { seenAlerts.add(a.id); alerter.textContent = `${a.message} ${a.action}`; }
    }
    const note = $("#hidden-note");
    note.hidden = !alerts.hidden;
    note.textContent = alerts.hidden ? `${alerts.hidden} hidden alert${alerts.hidden > 1 ? "s" : ""} still active (see History).` : "";
  }

  /* ---- Class type: radio groups on Overview and Setup stay in sync ---- */
  let pendingMode = null;  // {mode, ids, at}
  $$('.mode-control input[type="radio"]').forEach((radio) => radio.addEventListener("change", async () => {
    const mode = radio.value;
    setModeDisabled(true);
    showModeStatus(`Switching to ${MODE_LABEL[mode]}…`);
    try {
      const { nodes } = await post("/api/mode", { mode });
      pendingMode = { mode, ids: nodes, at: Date.now() };
      if (!nodes.length) {
        showModeStatus(`Class type set to ${MODE_LABEL[mode]}. No sensors to update yet.`);
        pendingMode = null;
        setModeDisabled(false);
      }
      poll(true);
    } catch (e) {
      showModeStatus(e.message);
      setModeDisabled(false);
    }
  }));
  function setModeDisabled(on) { $$('.mode-control input').forEach((r) => { r.disabled = on; }); }
  function showModeStatus(text) { $$("[data-mode-status]").forEach((p) => { p.textContent = text; }); }

  function renderMode() {
    const mode = state.classroom && state.classroom.mode;
    if (!pendingMode) $$('.mode-control input').forEach((r) => { r.checked = r.value === mode; });
    if (!pendingMode) return;
    const nodes = state.nodes.filter((n) => pendingMode.ids.includes(n.id));
    const done = nodes.filter((n) => n.config && n.config.mode === pendingMode.mode && n.config.state === "applied").length;
    const label = MODE_LABEL[pendingMode.mode];
    const waited = Date.now() - pendingMode.at;
    if (done === nodes.length) {
      showModeStatus(`${label}: all ${done} sensors updated ✓`);
      pendingMode = null;
      setModeDisabled(false);
      setTimeout(() => { if (!pendingMode) showModeStatus(""); }, 8000);
    } else if (waited > 6000) {
      const missing = nodes.length - done;
      showModeStatus(`${label}: ${done} of ${nodes.length} sensors updated. ${missing} didn't confirm yet; it keeps trying.`);
      setModeDisabled(false);
      if (waited > 30000) pendingMode = null;  // The Sensors page shows which one
    }
  }

  /* ---- Live room: headline, map, side cards, the last 10 minutes ---- */
  function renderLive() {
    renderSim();
    const f = fb();
    if (!f) return;
    const hero = $("#hero");
    hero.dataset.level = f.level;
    $("#kicker").textContent = KICKER[f.level] || KICKER.none;
    $("#h-live").textContent = f.headline;
    $("#summary").textContent = f.summary;
    $("#hero-tech").textContent = `activity ${f.tech.activity} · air ${f.tech.air} · comfort ${f.tech.comfort} · mode ${f.tech.mode}`;
    if (lastHeadline !== null && lastHeadline !== f.headline) {
      announcer.textContent = `${f.headline}. ${f.summary}`;
      replay(hero, "rise");
    }
    lastHeadline = f.headline;

    renderPlan($("#zone-map"), mapMetric);
    renderKey();
    renderZoneDetail();
    renderLoudness(f);
    renderAirComfort(f);
    renderTimeline($("#latest"), f.timeline.slice(0, 12));  // Wide screens show what fits beside the map; CSS trims to 4 when stacked
    renderLesson(f);
  }

  /* Loudness = how close the loudest student area is to its own noise limit:
   * the node's audio RMS (ADC counts) x 16 against the captured level_x16.
   * Never shown as dB: the microphone isn't calibrated. */
  const loudHistory = [];
  function loudPct(zoneId) {
    const cz = state.classroom && (state.classroom.zones || []).find((z) => z.zone === zoneId);
    if (!cz || !cz.loud || !cz.loud.level_x16) return null;
    const n = state.nodes.find((x) => x.id === cz.node_id);
    const a = n && n.status !== "offline" && n.telemetry && n.telemetry.audio;
    return a && a.rms != null ? (a.rms * 16 * 100) / cz.loud.level_x16 : null;
  }
  function loudest() {
    const f = fb();
    if (!f) return null;
    let best = null;
    for (const z of f.zones) {
      if (z.lecturer_area) continue;
      const p = loudPct(z.zone);
      if (p != null && (!best || p > best.pct)) best = { pct: p, name: z.name };
    }
    return best;
  }
  function sampleLoud() {  // Every poll, on every page, so the sparkline has history
    const best = loudest();
    if (best) loudHistory.push([state.time_ms, best.pct]);
    while (loudHistory.length && loudHistory[0][0] < state.time_ms - LOUD_SPAN_MS) loudHistory.shift();
  }
  function renderLoudness() {
    const card = $("#m-loud");
    const best = loudest();
    const anyLevel = !!(state.classroom && (state.classroom.zones || []).some((z) => z.loud && z.loud.level_x16));
    $("#loud-hint").hidden = anyLevel;
    if (!best) {
      card.dataset.tone = "none";
      countTo($("#loud-num"), null);
      $("#loud-where").textContent = anyLevel ? "No sound readings" : "";
      $("#loud-fill").style.width = "0%";
      spark($("#loud-spark"), [], 0, 1);
      return;
    }
    card.dataset.tone = best.pct >= 100 ? "act_now" : best.pct >= 70 ? "heads_up" : "fine";
    countTo($("#loud-num"), Math.round(best.pct), (v) => `${Math.round(v)}%`);
    $("#loud-where").textContent = best.name;
    $("#loud-fill").style.width = `${clamp(best.pct / 140, 0, 1) * 100}%`;
    spark($("#loud-spark"), loudHistory, 0, 140);
  }

  const CO2_TONE = { good: "fine", fair: "heads_up", poor: "act_now", warmup: "none", none: "none" };
  function renderAirComfort(f) {
    const live = state.nodes.filter((n) => n.status !== "offline" && n.telemetry);
    const withCo2 = live.filter((n) => n.telemetry.co2_ppm != null);
    const top = withCo2.reduce((a, b) => (!a || b.telemetry.co2_ppm > a.telemetry.co2_ppm ? b : a), null);
    const airCard = $("#m-air");
    const airTile = f.tiles.find((t) => t.id === "air");  // The verdict is the server's, like the headline
    if (top) {
      const level = co2Level(top.telemetry.co2_ppm, false);
      airCard.dataset.tone = airTile ? airTile.level : CO2_TONE[level];
      countTo($("#air-num"), top.telemetry.co2_ppm, (v) => Math.round(v).toLocaleString());
      $("#air-word").textContent = airTile ? airTile.label : CO2_LEVEL[level];
      $("#air-where").textContent = withCo2.length > 1 ? `Highest: ${sensorName(top.id).toLowerCase()}` : "";
      const since = state.time_ms - 300000;
      spark($("#air-spark"), top.history.filter((p) => p[0] >= since && p[3] != null).map((p) => [p[0], p[3]]),
            400, Math.max(state.co2_bands.poor + 200, top.telemetry.co2_ppm));
    } else {
      airCard.dataset.tone = "none";
      countTo($("#air-num"), null);
      $("#air-where").textContent = "";
      $("#air-word").textContent = live.some((n) => n.telemetry.co2_warmup) ? "Warming up" : "";
      spark($("#air-spark"), [], 0, 1);
    }
    const temps = live.map((n) => n.telemetry.temperature_c).filter((v) => v != null);
    const hums = live.map((n) => n.telemetry.humidity_pct).filter((v) => v != null);
    const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
    const tile = f.tiles.find((t) => t.id === "comfort");
    $("#m-comfort").dataset.tone = tile ? tile.level : "none";
    countTo($("#temp-num"), mean(temps), (v) => v.toFixed(1));
    $("#hum-num").textContent = hums.length ? `${Math.round(mean(hums))}% humidity` : "";
    $("#comfort-word").textContent = tile ? tile.label : "";
  }

  /* The last 10 minutes as one bar. Each stretch takes the worst level of the
   * room's sound, air and comfort at that time, from feedback.timeline. */
  const RANK = { none: 0, fine: 1, heads_up: 2, act_now: 3 };
  function renderLesson(f) {
    const end = state.time_ms, spanMs = state.history_s * 1000, start = end - spanMs;
    // Alerts (excessive noise, stuffy air...) count too, from start to end.
    const alerts = state.alerts || {};
    const alertItems = [...(alerts.active || []), ...(alerts.ended || [])].flatMap((a) => [
      { wall_ms: a.started_ms, level: a.level, text: a.message, tech: `alert${a.id}:` },
      ...(a.ended_ms ? [{ wall_ms: a.ended_ms, level: "fine", text: `Cleared: ${a.message}`, tech: `alert${a.id}:` }] : []),
    ]);
    const items = [...f.timeline, ...alertItems].sort((a, b) => a.wall_ms - b.wall_ms);
    const now = {};
    const worst = () => Object.values(now).reduce((w, l) => (RANK[l] > RANK[w] ? l : w), "fine");
    let from = start, level = "none", text = "Before the first change";
    const segs = [];
    for (const it of items) {
      const dim = (it.tech || "").split(":")[0] || it.text;
      if (it.wall_ms > start && it.wall_ms > from) segs.push({ from, to: it.wall_ms, level, text });
      now[dim] = it.level;
      level = worst();
      text = it.text;
      if (it.wall_ms > start) from = it.wall_ms;
    }
    segs.push({ from, to: end, level, text });
    const merged = [];
    for (const s of segs) {  // Neighbours at the same level become one stretch
      const last = merged[merged.length - 1];
      if (last && last.level === s.level) { last.to = s.to; if (!last.texts.includes(s.text)) last.texts.push(s.text); }
      else merged.push({ ...s, texts: [s.text] });
    }
    const bar = $("#lesson-bar");
    const key = merged.map((s) => `${s.from}:${s.level}`).join("|");
    if (bar.dataset.key !== key) {
      bar.dataset.key = key;
      bar.replaceChildren(...merged.map((s) => {
        const b = make("button", "seg");
        b.type = "button";
        b.dataset.level = s.level;
        const what = s.texts.slice(-2).map((t) => t.replace(/\.$/, "")).join(", ");
        const label = `${clockTime(s.from)} to ${s.to >= end - 1500 ? "now" : clockTime(s.to)}: ${what}`;
        b.title = label;
        b.setAttribute("aria-label", `${label}. ${LEVEL_WORD[s.level]}.`);
        return b;
      }), make("span", "lesson-now"));
    }
    [...bar.querySelectorAll(".seg")].forEach((b, i) => b.style.setProperty("--w", String(Math.max(1, merged[i].to - merged[i].from))));
    const mins = Math.round(state.history_s / 60);
    $("#lesson-span").textContent = mins === 1 ? "minute" : `${mins} minutes`;
    const axis = $("#lesson-axis");
    const labels = [clockTime(start), clockTime(start + spanMs / 2), "now"];
    if (axis.textContent !== labels.join("")) axis.replaceChildren(...labels.map((t) => make("span", "", t)));
  }

  /* ---- Room map ---- */
  $$('input[name="map-metric"]').forEach((r) => r.addEventListener("change", () => { mapMetric = r.value; if (state) renderLive(); }));
  function renderKey() {
    const key = $("#map-key");
    const which = mapMetric === "activity" ? "activity" : "other";
    if (key.dataset.which === which) return;
    key.dataset.which = which;
    key.replaceChildren(...KEYS[which].map(([look, word]) => {
      const li = make("li");
      const sw = make("span", "sw-look");
      sw.dataset.look = look;
      li.append(sw, word);
      return li;
    }));
  }

  /* Ambient effects, shared by the area card and the room map: haze for stuffy
   * air, rising heat lines, footsteps for movement, sound-meter bars for voices.
   * Built once; renders only change their strength through CSS variables
   * (--haze, --heat, --steps) and data attributes, so the 1 s refresh never
   * restarts an animation. The words beside them always carry the meaning. */
  const seeded = (i, k) => ((i * 73 + k * 37) % 97) / 97;  // Stable "random" positions
  function fillHaze(el, n) {
    for (let i = 0; i < n; i++) {
      const m = make("i", "mote");
      const size = 18 + seeded(i, 1) * 26;
      Object.assign(m.style, { left: `${seeded(i, 2) * 88}%`, top: `${45 + seeded(i, 3) * 50}%`,
                               width: `${size}px`, height: `${size}px`, animationDelay: `${-seeded(i, 4) * 9}s` });
      m.style.setProperty("--i", i / n);  // Motes appear one by one as the haze thickens
      el.append(m);
    }
  }
  function fillHeat(el) {
    const s = svg("svg", { viewBox: "0 0 60 40", preserveAspectRatio: "none" });
    [12, 30, 48].forEach((x, i) => {
      const p = svg("path", { d: `M${x} 40c-5-6 5-10 0-16s5-10 0-16`, class: "heat-line" }, s);
      p.style.animationDelay = `${-i * 0.8}s`;
    });
    el.append(s);
  }
  function fillSteps(el, n, from, to, aspect = 1, gait = 6) {  // Alternate left and right prints along a walk
    // Points are in % of the box; aspect (width / height) turns them into a real angle.
    const ang = (Math.atan2((to[0] - from[0]) * aspect, -(to[1] - from[1])) * 180) / Math.PI;
    for (let i = 0; i < n; i++) {
      const t = (i + 0.5) / n, side = i % 2 ? 1 : -1;
      const x = from[0] + (to[0] - from[0]) * t + (side * gait * Math.cos((ang * Math.PI) / 180)) / aspect;
      const y = from[1] + (to[1] - from[1]) * t + side * gait * Math.sin((ang * Math.PI) / 180);
      const foot = icon("i-foot", "foot");
      foot.style.left = `${x}%`;
      foot.style.top = `${y}%`;
      foot.style.setProperty("--r", `${ang}deg`);
      foot.style.setProperty("--flip", side > 0 ? "-1" : "1");
      foot.style.animationDelay = `calc(var(--pace, 3s) * ${i / n})`;
      el.append(foot);
    }
  }
  function co2Trend(nodeId) {  // Last 3 minutes of this sensor: up, down or steady
    const node = state.nodes.find((n) => n.id === nodeId);
    const pts = node ? node.history.filter((p) => p[3] != null && p[0] >= state.time_ms - 180000) : [];
    if (pts.length < 2 || pts[pts.length - 1][0] - pts[0][0] < 60000) return "steady";
    const d = pts[pts.length - 1][3] - pts[0][3];
    return d > 40 ? "rising" : d < -40 ? "falling" : "steady";
  }
  const heatOf = (t) => (t == null ? 0 : clamp((t - 25) / 3, 0, 1));
  const stepsOf = (pct) => (pct == null || pct < 3 ? 0 : clamp(pct / 30, 0.3, 1));  // Matches MOVE_WORD: under 3 % is "None"
  const MOVE_WORD = (pct) => (pct == null ? "No reading" : pct < 3 ? "None" : pct < 15 ? "A little" : pct < 40 ? "Some" : "Lots");

  /* Floor plan (docs/ui_design.md): drawn from the zone layout. u runs from
   * the front of the room (whiteboard) to the back, v from the door side to
   * the window side. Wide: front on the left; narrow: front at the top. */
  let selectedZone = null;
  const SVG_W = 1000, SVG_H = 600;

  function planGeometry(zones) {
    const lecturer = zones.find((z) => z.lecturer_area);
    const rows = [...new Set(zones.map((z) => z.layout[0]))].sort((a, b) => a - b);
    const lecturerAlone = lecturer && zones.filter((z) => z.layout[0] === lecturer.layout[0]).length === 1 && lecturer.layout[0] === rows[0];
    const first = lecturerAlone ? 0.24 : 0;
    const rest = rows.length - (lecturerAlone ? 1 : 0);
    const bands = {};
    rows.forEach((row, i) => {
      if (lecturerAlone && i === 0) bands[row] = [0, first];
      else { const k = i - (lecturerAlone ? 1 : 0); bands[row] = [first + (k * (1 - first)) / rest, first + ((k + 1) * (1 - first)) / rest]; }
    });
    const rects = {};
    for (const row of rows) {
      const inRow = zones.filter((z) => z.layout[0] === row).sort((a, b) => a.layout[1] - b.layout[1]);
      inRow.forEach((z, j) => { rects[z.zone] = { u0: bands[row][0], u1: bands[row][1], v0: j / inRow.length, v1: (j + 1) / inRow.length }; });
    }
    return { rects, seatsFrom: lecturerAlone ? first : 0, seatBands: rest || rows.length };
  }

  function drawRoom(root, portrait, geo) {
    const vbW = portrait ? SVG_H : SVG_W, vbH = portrait ? SVG_W : SVG_H, m = 14;
    const P = (u, v) => (portrait ? [m + v * (vbW - 2 * m), m + u * (vbH - 2 * m)] : [m + u * (vbW - 2 * m), m + v * (vbH - 2 * m)]);
    const box = (u0, v0, u1, v1, attrs) => {
      const [x0, y0] = P(u0, v0), [x1, y1] = P(u1, v1);
      return svg("rect", { x: Math.min(x0, x1), y: Math.min(y0, y1), width: Math.abs(x1 - x0), height: Math.abs(y1 - y0), ...attrs }, root);
    };
    const line = (u0, v0, u1, v1, cls) => { const [x0, y0] = P(u0, v0), [x1, y1] = P(u1, v1); svg("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: cls }, root); };
    box(0, 0, 1, 1, { class: "room-floor" });
    box(0, 0, 1, 1, { class: "room-wall" });                       // Wall first: board, door, windows sit on it
    line(0, 0.18, 0, 0.72, "room-board");                       // Whiteboard on the front wall
    const [hx, hy] = P(0.035, 0), [ex, ey] = P(0.115, 0);         // Door: gap, open leaf, swing
    const r = Math.hypot(ex - hx, ey - hy);
    const [lx, ly] = portrait ? [hx + r, hy] : [hx, hy + r];      // Leaf opens into the room
    svg("line", { x1: hx, y1: hy, x2: ex, y2: ey, class: "room-door-gap" }, root);
    svg("line", { x1: hx, y1: hy, x2: lx, y2: ly, class: "room-door" }, root);
    svg("path", { d: `M${ex} ${ey} A${r} ${r} 0 0 ${portrait ? 0 : 1} ${lx} ${ly}`, class: "room-door room-swing" }, root);
    for (let i = 0; i < 3; i++) {                                 // Windows on the far wall
      const a = geo.seatsFrom + ((i + 0.2) * (1 - geo.seatsFrom)) / 3, b = a + (0.6 * (1 - geo.seatsFrom)) / 3;
      line(a, 1, b, 1, "room-window");
    }
    if (geo.seatsFrom > 0) {                                      // Lecturer's desk and chair
      box(geo.seatsFrom * 0.5, 0.6, geo.seatsFrom * 0.68, 0.86, { class: "room-desk", rx: 4 });
      const [cx, cy] = P(geo.seatsFrom * 0.3, 0.73);
      svg("circle", { cx, cy, r: 13, class: "room-chair" }, root);
    }
    const cols = geo.seatBands * 2;                               // Student desks: two blocks, aisle between
    for (let c = 0; c < cols; c++) {
      const u = geo.seatsFrom + ((c + 0.5) * (1 - geo.seatsFrom)) / cols;
      for (const v of [0.16, 0.28, 0.4, 0.6, 0.72, 0.84]) {
        box(u - 0.022, v - 0.04, u + 0.006, v + 0.04, { class: "room-desk", rx: 3 });
        const [cx, cy] = P(u + 0.024, v);
        svg("circle", { cx, cy, r: 9, class: "room-chair" }, root);
      }
    }
    return { P, vbW, vbH };
  }

  function renderPlan(container, metric, compact = false) {
    const f = fb();
    if (!f) return;
    const portrait = container.clientWidth > 0 && container.clientWidth < 560;
    // Rebuild only when the room changes shape; otherwise update in place, so
    // keyboard focus and screen-reader position survive the 1 s refresh.
    const key = `${portrait}|${f.zones.map((z) => `${z.zone}:${z.layout}:${z.lecturer_area}`).join(",")}`;
    const rebuilt = container.dataset.key !== key;
    if (rebuilt) buildPlan(container, portrait, compact, f.zones, key);
    container.dataset.metric = metric;  // Footsteps only in the Movement view
    const view = portrait ? "flat" : mapView;
    if (container.dataset.view !== view) { container.dataset.view = view; labelBurst(); }
    $("#map-view").hidden = portrait;
    if (view === "3d") fit3D(container);
    $("#map-front").textContent = portrait ? "Front of the room at the top"
      : view === "3d" ? "Whiteboard on the far left wall" : "Front of the room on the left";
    const czones = (state.classroom && state.classroom.zones) || [];
    for (const z of f.zones) {
      const el = container.querySelector(`[data-zone="${CSS.escape(z.zone)}"]`);
      const offline = z.status === "Not connected";
      const m = z[metric];
      const level = offline ? "none" : m.level;
      const label = offline ? "Not connected" : m.label;
      const tech = z.activity.tech;
      let look = LEVEL_LOOK[level] || "none";
      if (metric === "activity" && !offline) {
        look = ACT_LOOK[tech] || look;
        if (tech === "TALKING" && level === "fine") look = "settled";  // Group work: talking is expected
      }
      const rings = metric === "activity" && !offline ? { LECTURER: "speak", TALKING: "talk", LOUD: "loud" }[tech] : null;
      const cz = czones.find((c) => c.zone === z.zone);
      const node = state.nodes.find((n) => n.id === z.node_id);
      let detail = "";
      if (offline) detail = node && node.age_s != null ? `Last reading ${Math.round(node.age_s)} s ago` : "No readings yet";
      else if (metric === "activity") {
        const p = loudPct(z.zone);
        detail = p != null ? `${Math.round(p)}% of noise limit` : "";
      } else detail = m.detail || "";

      el.dataset.level = level;
      el.dataset.look = look;
      if (rings) el.dataset.rings = rings; else delete el.dataset.rings;
      el.dataset.offline = String(offline);
      const ppm = cz && !offline ? cz.co2_ppm : null;
      el.style.setProperty("--haze", ppm == null ? "0" : String(clamp((ppm - 800) / 500, 0, 0.9)));
      el.style.setProperty("--heat", String(offline || !cz ? 0 : heatOf(cz.temperature_c)));
      el.style.setProperty("--steps", String(offline || !cz ? 0 : stepsOf(cz.motion_pct)));
      if (!compact) el.setAttribute("aria-pressed", String(z.zone === selectedZone));
      el.setAttribute("aria-label", `${z.name}: ${label}${detail ? ", " + detail : ""}.${m.why ? " " + m.why : ""}`);
      const st = $(".plan-state", el);
      st.dataset.level = level;
      $("span", st).textContent = label;
      $(".plan-detail", el).textContent = detail;
      const techLine = $(".tech", el);
      if (techLine) techLine.textContent = `zone ${z.zone} · sensor ${z.node_id}${m.tech ? " · " + m.tech : ""}`;
      const lab = $(`.plan-label[data-zone="${CSS.escape(z.zone)}"]`, container);
      if (lab) {
        lab.dataset.look = look;
        $(".plan-word", lab).textContent = label;
        $(".plan-detail", lab).textContent = detail;
      }
    }
    placeLabels();
    if (rebuilt) labelBurst();
  }

  function buildPlan(container, portrait, compact, zones, key) {
    container.dataset.key = key;
    container.dataset.portrait = String(portrait);
    container.setAttribute("aria-label", `Classroom floor plan. The front of the room, with the whiteboard and the lecturer's desk, is ${portrait ? "at the top" : "on the left"}.`);
    const geo = planGeometry(zones);
    const root = svg("svg", { class: "plan-room", "aria-hidden": "true", preserveAspectRatio: "none" });
    const { P, vbW, vbH } = drawRoom(root, portrait, geo);
    root.setAttribute("viewBox", `0 0 ${vbW} ${vbH}`);
    container.style.setProperty("--ratio", `${vbW} / ${vbH}`);
    const pct = (x, total) => `${(100 * x) / total}%`;
    const nodes = [root];
    for (const z of zones) {
      const g = geo.rects[z.zone];
      const [x0, y0] = P(g.u0, g.v0), [x1, y1] = P(g.u1, g.v1);
      const [sx, sy] = P((g.u0 + g.u1) / 2, g.v1 - 0.08);
      svg("circle", { cx: sx, cy: sy, r: 8, class: "room-sensor" }, root);
      const el = make("button", "plan-zone");
      el.dataset.zone = z.zone;
      el.type = "button";
      el.setAttribute("aria-controls", "zone-detail");
      el.addEventListener("click", () => openZone(z.zone));
      Object.assign(el.style, { left: pct(Math.min(x0, x1), vbW), top: pct(Math.min(y0, y1), vbH),
                                width: pct(Math.abs(x1 - x0), vbW), height: pct(Math.abs(y1 - y0), vbH) });
      const chip = make("span", "plan-chip");
      chip.append(make("span", "plan-name", z.name), levelLine("none", "", "plan-state"), make("span", "plan-detail"), make("span", "tech"));
      const haze = make("span", "haze"), heat = make("span", "fx-heat"), steps = make("span", "fx-steps");
      fillHaze(haze, 10);
      fillHeat(heat);
      // Someone walking along the area's long side, like down an aisle
      const aspect = Math.abs(x1 - x0) / Math.abs(y1 - y0);
      if (aspect < 1) fillSteps(steps, 6, [44, 94], [56, 8], aspect, 7);
      else fillSteps(steps, 6, [6, 60], [94, 44], aspect, 7);
      el.append(haze, heat, steps, make("span", "ring"), make("span", "ring"), make("span", "ring"), chip, make("span", "plan-anchor"));
      nodes.push(el);
    }
    // 3D view: the same floor plan tilted into an isometric diorama. Walls, the
    // whiteboard and desks are extruded boxes; labels float upright above it.
    const plane = make("div", "plan-plane");
    const solid = make("div", "plan-solid");
    buildSolid(solid, P, vbW, vbH, geo, portrait);
    plane.append(...nodes, solid);
    const labels = make("div", "plan-labels");
    labels.setAttribute("aria-hidden", "true");  // The zone buttons carry the same words
    for (const z of zones) {
      const lab = make("div", "plan-label");
      lab.dataset.zone = z.zone;
      lab.append(make("span", "plan-name", z.name), make("span", "plan-word"), make("span", "plan-detail"));
      labels.append(lab);
    }
    container.replaceChildren(plane, labels);
  }

  /* Extruded parts of the room for the 3D view. Box footprints are in % of the
   * plan, heights in px; only the two far walls are drawn so nothing hides the floor. */
  function buildSolid(root, P, vbW, vbH, geo, portrait) {
    const at = (u0, v0, u1, v1) => {
      const [x0, y0] = P(u0, v0), [x1, y1] = P(u1, v1);
      return { left: `${(100 * Math.min(x0, x1)) / vbW}%`, top: `${(100 * Math.min(y0, y1)) / vbH}%`,
               width: `${(100 * Math.abs(x1 - x0)) / vbW}%`, height: `${(100 * Math.abs(y1 - y0)) / vbH}%` };
    };
    const box = (cls, u0, v0, u1, v1, h) => {
      const b = make("div", `solid ${cls}`);
      Object.assign(b.style, at(u0, v0, u1, v1));
      b.style.setProperty("--h", `${h}px`);
      b.append(make("i", "s-top"), make("i", "s-front"), make("i", "s-side"));
      root.append(b);
      return b;
    };
    if (portrait) return;  // Phones stay flat
    const wallFront = make("div", "wall wall-front");   // u = 0: whiteboard wall
    Object.assign(wallFront.style, at(0, 0, 0.0001, 1));
    wallFront.append(make("i", "board"));
    const wallDoor = make("div", "wall wall-door");     // v = 0: door side, with the doorway left open
    Object.assign(wallDoor.style, at(0.115, 0, 1, 0.0001));
    root.append(wallFront, wallDoor);
    if (geo.seatsFrom > 0) box("desk lectern", geo.seatsFrom * 0.5, 0.6, geo.seatsFrom * 0.68, 0.86, 18);
    const cols = geo.seatBands * 2;
    for (let c = 0; c < cols; c++) {
      const u = geo.seatsFrom + ((c + 0.5) * (1 - geo.seatsFrom)) / cols;
      for (const v of [0.16, 0.28, 0.4, 0.6, 0.72, 0.84]) box("desk", u - 0.022, v - 0.04, u + 0.006, v + 0.04, 12);
    }
  }

  /* Map view: flat (as drawn) or 3D (tilted). Phones are always flat. */
  let mapView = "3d";
  try { if (localStorage.getItem("mosaic-view") === "flat") mapView = "flat"; } catch (e) { /* Blocked */ }
  $$('input[name="map-view"]').forEach((r) => {
    r.checked = r.value === mapView;
    r.addEventListener("change", () => {
      mapView = r.value;
      store("mosaic-view", mapView === "flat" ? "flat" : null);
      if (state) renderLive();
      labelBurst();
    });
  });
  function fit3D(container) {  // Scale the tilted room so it fits the panel
    const cw = container.clientWidth, ch = container.clientHeight;
    const a = (40 * Math.PI) / 180, t = (58 * Math.PI) / 180;
    const pw = cw * Math.cos(a) + ch * Math.sin(a);
    const ph = (cw * Math.sin(a) + ch * Math.cos(a)) * Math.cos(t) + 40 * Math.sin(t);
    $(".plan-plane", container).style.setProperty("--s", (Math.min(cw / pw, ch / ph) * 1.04).toFixed(3));
  }
  function placeLabels() {
    const container = $("#zone-map");
    if (!container || container.dataset.view !== "3d") return;
    const box = container.getBoundingClientRect();
    $$(".plan-label", container).forEach((lab) => {
      const anchor = $(`.plan-zone[data-zone="${CSS.escape(lab.dataset.zone)}"] .plan-anchor`, container);
      if (!anchor) return;
      const a = anchor.getBoundingClientRect();
      lab.style.left = `${a.left - box.left}px`;
      lab.style.top = `${a.top - box.top}px`;
    });
  }
  let burstEnd = 0;
  function labelBurst(ms = 1400) {  // Follow the areas while the room tilts
    const running = performance.now() < burstEnd;
    burstEnd = performance.now() + ms;
    if (running) return;
    const step = () => { placeLabels(); if (performance.now() < burstEnd) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  /* Simulation strip: which scripted phase the simulator is playing (dashboard.py "simulation") */
  const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  function renderSim() {
    const sim = state.simulation;
    const strip = $("#sim-strip");
    strip.hidden = !sim;
    if (!sim) return;
    const bar = $("#sim-bar");
    if (!sim.scenario) {
      $("#sim-name").textContent = "Simulated";
      $("#sim-phase").textContent = `${sim.nodes} sensors with random readings, no script`;
      $("#sim-left").textContent = "";
      $("#sim-toggle").hidden = true;  // No script to control
      $("#sim-controls").hidden = true;
      bar.hidden = true;
      $("#sim-tech").textContent = "";
      return;
    }
    $("#sim-name").textContent = `Simulated · ${sim.scenario[0].toUpperCase()}${sim.scenario.slice(1)}`;
    const n = sim.phases.length;
    $("#sim-phase").textContent = sim.finished ? `Script finished, holding: ${sim.label}`
      : `Phase ${sim.phase + 1} of ${n}: ${sim.label}`;
    const left = $("#sim-left");
    const speed = sim.paused ? "Paused" : sim.rate > 1 ? `${sim.rate}×` : "";
    left.replaceChildren(...(speed ? [make("b", "", speed), document.createTextNode(sim.finished ? "" : " · ")] : []),
                         document.createTextNode(sim.finished ? "" : `${mmss(sim.left_s)} left`));
    renderSimControls(sim);
    bar.hidden = false;
    if (bar.dataset.scenario !== sim.scenario) {
      bar.dataset.scenario = sim.scenario;
      bar.replaceChildren(...sim.phases.map((ph) => {
        const seg = make("i", "");
        seg.style.setProperty("--s", ph.seconds);
        seg.title = ph.label;
        return seg;
      }));
    }
    [...bar.children].forEach((seg, i) => {
      seg.toggleAttribute("data-done", i < sim.phase || sim.finished);
      seg.toggleAttribute("data-now", i === sim.phase && !sim.finished);
    });
    const cur = sim.phases[sim.phase];
    bar.children[sim.phase].style.setProperty("--p", `${clamp((cur.seconds - sim.left_s) / cur.seconds, 0, 1) * 100}%`);
    const c = state.classroom;
    $("#sim-tech").textContent = `expected ${sim.expect} · now activity ${c ? c.activity : "—"}, air ${c ? c.air : "—"}, comfort ${c ? c.comfort : "—"}`;
  }

  /* Demo controls for a scripted simulation: a toggle opens a clickable row
   * (closed by default and in presenter mode), and the same actions have keys:
   * Space pause/play, right arrow next phase, 1/2/4 speed. */
  let simOpen = false, simOpenPresent = false;  // Presenter mode starts closed and isn't remembered
  const presenting = () => "present" in document.documentElement.dataset;
  try { simOpen = localStorage.getItem("mosaic-sim-controls") === "open"; } catch (e) { /* Blocked */ }
  function renderSimControls(sim) {
    const toggle = $("#sim-toggle");
    toggle.hidden = false;
    const open = presenting() ? simOpenPresent : simOpen;
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Hide demo controls" : "Show demo controls");
    toggle.title = toggle.getAttribute("aria-label");
    $("#sim-controls").hidden = !open;
    const play = $("#sim-play");
    play.setAttribute("aria-label", sim.paused ? "Play the script" : "Pause the script");
    play.title = play.getAttribute("aria-label");
    $("use", play).setAttribute("href", sim.paused ? "#i-play" : "#i-pause");
    const last = sim.finished || sim.phase >= sim.phases.length - 1;
    $("#sim-next").disabled = last;
    $("#sim-next").title = last ? "Already on the last phase" : "Next phase";
    document.querySelectorAll('input[name="sim-rate"]').forEach((r) => { r.checked = Number(r.value) === sim.rate; });
  }
  async function simControl(body) {
    try {
      state.simulation = await post("/api/simulation", body);
      renderSim();
      const s = state.simulation;
      announcer.textContent = body.pause !== undefined ? (s.paused ? "Script paused" : "Script playing")
        : body.rate ? `Script speed ${s.rate}×` : `Phase ${s.phase + 1}: ${s.label}`;
    } catch (err) {
      announcer.textContent = err.message;
    }
  }
  $("#sim-toggle").addEventListener("click", () => {
    const open = $("#sim-toggle").getAttribute("aria-expanded") !== "true";
    if (presenting()) simOpenPresent = open;
    else { simOpen = open; store("mosaic-sim-controls", open ? "open" : null); }
    if (state && state.simulation) renderSim();
  });
  $("#sim-play").addEventListener("click", () => state.simulation && simControl({ pause: !state.simulation.paused }));
  $("#sim-next").addEventListener("click", () => simControl({ next: true }));
  document.querySelectorAll('input[name="sim-rate"]').forEach((r) =>
    r.addEventListener("change", () => simControl({ rate: Number(r.value) })));
  document.addEventListener("keydown", (e) => {
    const sim = state && state.simulation;
    const strip = $("#sim-strip");
    if (!sim || !sim.scenario || strip.hidden || !strip.offsetParent) return;  // Live room with a script only
    if (e.metaKey || e.ctrlKey || e.altKey || e.repeat || document.querySelector("dialog[open]")) return;
    if (document.documentElement.dataset.intro === "play") return;  // That key skips the intro
    const t = e.target;
    if (t.closest && t.closest("input, textarea, select, [contenteditable]")) return;
    let body;
    if (e.key === " " && !(t.closest && t.closest("button, a, summary, [role=button]"))) body = { pause: !sim.paused };
    else if (e.key === "ArrowRight") body = { next: true };
    else if (["1", "2", "4"].includes(e.key)) body = { rate: Number(e.key) };
    else return;
    e.preventDefault();
    simControl(body);
  });

  /* Area details: a card in the side column; Escape or the close button hides it */
  function openZone(zone) {
    selectedZone = zone;
    renderLive();
    $("#zone-close").focus();
  }
  function closeZone() {
    const zone = selectedZone;
    selectedZone = null;
    $("#zone-detail").hidden = true;
    if (state) renderLive();
    const btn = zone && $(`#zone-map [data-zone="${CSS.escape(zone)}"]`);
    if (btn) btn.focus();
  }
  $("#zone-close").addEventListener("click", closeZone);
  let cardFx = false;
  function renderZoneDetail() {
    const f = fb();
    const card = $("#zone-detail");
    const z = f && selectedZone && f.zones.find((x) => x.zone === selectedZone);
    card.hidden = !z;
    if (!z) { selectedZone = null; return; }
    if (!cardFx) {  // Effects are built once and only re-tuned afterwards
      cardFx = true;
      fillHaze($("#zd-air .fx-haze"), 12);
      fillHeat($("#zd-warm .fx-heat"));
      fillSteps($("#zd-move .fx-steps"), 4, [66, 96], [84, 6], 2.2, 9);
    }
    const c = state.classroom || {};
    const cz = (c.zones || []).find((x) => x.zone === z.zone) || {};
    const offline = z.status === "Not connected";
    $("#zone-detail-h").textContent = z.name;

    // Sound: one big word with a live sound meter
    const tech = z.activity.tech;
    const voice = offline ? "none" : { LECTURER: "speak", TALKING: "talk", LOUD: "loud", NO_DATA: "none" }[tech] || "quiet";
    $("#zd-voice").dataset.voice = voice;
    $("#zd-hero").dataset.look = offline ? "none" : (tech === "TALKING" && z.activity.level === "fine") ? "settled"
      : ACT_LOOK[tech] || LEVEL_LOOK[z.activity.level] || "none";
    $("#zd-word").textContent = offline ? "Not connected" : z.activity.label;
    const mins = cz.since_ms != null && c.now_ms != null ? Math.floor((c.now_ms - cz.since_ms) / 60000) : null;
    $("#zd-sub").textContent = offline ? "Check this sensor's power" : tech === "NO_DATA" ? "No sound reading"
      : mins == null ? "" : mins < 1 ? "just now" : `for ${mins} min`;

    // Air: stuffiness as haze, trend as an arrow
    const air = $("#zd-air");
    const trend = co2Trend(z.node_id);
    air.dataset.tone = offline ? "none" : z.air.level;
    air.style.setProperty("--haze", cz.co2_ppm == null || offline ? "0" : String(clamp((cz.co2_ppm - 650) / 650, 0.08, 1)));
    $(".zd-big", air).textContent = offline ? "—" : z.air.label;
    $(".zd-small", air).textContent = offline || cz.co2_ppm == null ? "no reading"
      : { rising: z.air.level === "fine" ? "↑ rising" : "↑ getting worse", falling: "↓ improving",
          steady: z.air.level === "fine" ? "✓ steady" : "→ steady" }[trend];
    air.setAttribute("aria-label", `Air: ${z.air.label}${cz.co2_ppm != null ? `, ${cz.co2_ppm} ppm CO₂` : ""}, ${trend}`);

    // Warmth: degrees, with heat lines when it's warm
    const warm = $("#zd-warm");
    const t = offline ? null : cz.temperature_c;
    warm.dataset.tone = offline ? "none" : z.comfort.level;
    warm.style.setProperty("--heat", String(heatOf(t)));
    $(".zd-big", warm).textContent = t == null ? "—" : `${Math.round(t)}°`;
    $(".zd-small", warm).textContent = t == null ? "no reading" : z.comfort.level === "fine" ? "✓ fine" : "▲ not comfy";
    warm.setAttribute("aria-label", `Warmth: ${z.comfort.label}${z.comfort.detail ? `, ${z.comfort.detail}` : ""}`);

    // Movement: information only, so it stays neutral; footsteps show how much
    const move = $("#zd-move");
    const pct = offline ? null : cz.motion_pct;
    move.style.setProperty("--steps", String(stepsOf(pct)));
    move.style.setProperty("--pace", `${pct == null ? 3 : clamp(4.2 - pct / 25, 1.8, 4.2)}s`);
    $(".zd-big", move).textContent = MOVE_WORD(pct);
    $(".zd-small", move).textContent = "movement";
    move.setAttribute("aria-label", `Movement: ${MOVE_WORD(pct).toLowerCase()}${pct != null ? `, ${pct} % of the time` : ""}`);

    $("#zone-detail-sensor").textContent = `Sensor ${z.node_id} · ${z.status.toLowerCase()}`;
    $("#zone-detail-tech").textContent = `zone ${z.zone} · ${tech} · ${z.air.tech} ${cz.co2_ppm ?? "—"} ppm · ${z.comfort.tech} ${z.comfort.detail} · motion ${pct ?? "—"} %`;
  }

  /* ---- History ---- */
  function renderTimeline(list, items) {
    if (!items.length) {
      list.replaceChildren(make("li", "timeline-empty", "Nothing yet. Changes in the room appear here."));
      return;
    }
    const seen = Number(list.dataset.newest || 0);  // New rows slide in; the first fill doesn't
    list.dataset.newest = String(Math.max(seen, ...items.map((i) => i.wall_ms)));
    list.replaceChildren(...items.map((item) => {
      const li = make("li", seen && item.wall_ms > seen ? "timeline-item enter" : "timeline-item");
      li.dataset.level = item.level;
      const time = make("time", "timeline-time", clockTime(item.wall_ms));
      time.dateTime = new Date(item.wall_ms).toISOString();
      time.title = new Date(item.wall_ms).toLocaleString();
      li.append(time, icon(LEVEL_ICON[item.level], `icon icon-sm lvl-${item.level}`), make("span", "", item.text),
                make("span", "timeline-ago", ago(item.wall_ms)), make("span", "tech", item.tech));
      return li;
    }));
  }

  $$('input[name="range"]').forEach((r) => r.addEventListener("change", () => { rangeS = Number(r.value); if (state) renderCharts(); }));

  function renderLegend(nodes) {
    const legend = $("#legend");
    const ids = nodes.map((n) => n.id).join(",");
    if (legend.dataset.ids === ids) return;
    legend.dataset.ids = ids;
    legend.replaceChildren(...nodes.map((n) => {
      const b = make("button", "chip-btn");
      b.type = "button";
      b.style.setProperty("--series", series(n.id));
      b.setAttribute("aria-pressed", String(!hidden.has(n.id)));
      b.innerHTML = `<svg width="18" height="6" aria-hidden="true"><line x1="1" y1="3" x2="17" y2="3"
        stroke="var(--series)" stroke-width="3" stroke-linecap="round" stroke-dasharray="${dash(n.id)}"/></svg>`;
      b.append(sensorName(n.id));
      b.addEventListener("click", () => {
        if (hidden.has(n.id)) hidden.delete(n.id); else hidden.add(n.id);
        b.setAttribute("aria-pressed", String(!hidden.has(n.id)));
        renderCharts();
      });
      return b;
    }));
  }

  function sensorName(id) {
    const z = fb() && fb().zones.find((x) => x.node_id === id);
    return z ? z.name : `Sensor ${id}`;
  }

  function niceTicks(lo, hi, count = 4) {
    const raw = (hi - lo) / count;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(6));
    return ticks;
  }

  function drawChart(container, summary, field, opts) {
    const w = Math.max(container.clientWidth, 200);
    const h = container.clientHeight || 220;
    const pad = { l: 42, r: 10, t: 8, b: 22 };
    const end = state.time_ms;
    const start = end - rangeS * 1000;
    const lines = state.nodes.filter((n) => !hidden.has(n.id)).map((n) => ({
      id: n.id, pts: n.history.filter((p) => p[0] >= start && p[field] != null).map((p) => [p[0], p[field]]),
    })).filter((s) => s.pts.length);

    const root = svg("svg", { viewBox: `0 0 ${w} ${h}`, "aria-hidden": "true" });
    const values = lines.flatMap((s) => s.pts.map((p) => p[1]));
    const span = rangeS >= 60 ? `${rangeS / 60} minute${rangeS > 60 ? "s" : ""}` : `${rangeS} seconds`;
    if (!values.length) {
      svg("text", { x: w / 2, y: h / 2, "text-anchor": "middle", class: "no-data" }, root).textContent = "No readings yet";
      container.replaceChildren(root);
      container.setAttribute("aria-label", `${opts.name}: no readings yet`);
      summary.textContent = "No readings yet.";
      return;
    }
    let lo = Math.min(...values), hi = Math.max(...values);
    [lo, hi] = opts.domain(lo, hi);
    const x = (t) => pad.l + ((t - start) / (end - start)) * (w - pad.l - pad.r);
    const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (h - pad.t - pad.b);
    for (const band of opts.bands || []) {
      const top = y(Math.min(band.to, hi)), bottom = y(Math.max(band.from, lo));
      if (bottom > top) svg("rect", { x: pad.l, y: top, width: w - pad.l - pad.r, height: bottom - top, class: band.cls }, root);
    }
    for (const v of niceTicks(lo, hi)) {
      svg("line", { x1: pad.l, x2: w - pad.r, y1: y(v), y2: y(v), class: "grid-line" }, root);
      svg("text", { x: pad.l - 8, y: y(v) + 4, "text-anchor": "end", class: "axis-text" }, root).textContent = opts.tick(v);
    }
    const label = (s) => (s === 0 ? "now" : s >= 60 ? `−${s / 60} min` : `−${s} s`);
    [rangeS, rangeS / 2, 0].forEach((s, i) => {
      svg("text", { x: x(end - s * 1000), y: h - 4, "text-anchor": ["start", "middle", "end"][i], class: "axis-text" }, root).textContent = label(s);
    });
    for (const s of lines) {
      let d = "", prev = null;
      for (const [t, v] of s.pts) {
        d += `${prev === null || t - prev > 5000 ? "M" : "L"}${x(t).toFixed(1)},${y(v).toFixed(1)}`;
        prev = t;
      }
      const g = svg("g", { style: `--series:${series(s.id)}` }, root);
      svg("path", { d, class: "series-line", "stroke-dasharray": dash(s.id) }, g);
      const [lt, lv] = s.pts[s.pts.length - 1];
      svg("circle", { cx: x(lt), cy: y(lv), r: 4, class: "series-dot" }, g);
    }
    container.replaceChildren(root);
    // Text alternative: the highest line now, and how it moved over the range.
    const top = lines.reduce((a, b) => (b.pts[b.pts.length - 1][1] > a.pts[a.pts.length - 1][1] ? b : a));
    const first = top.pts[0][1], last = top.pts[top.pts.length - 1][1];
    const trend = Math.abs(last - first) < opts.flat ? "stayed about the same" : last > first ? `rose from ${opts.tick(first)}` : `fell from ${opts.tick(first)}`;
    const text = `Highest now: ${opts.tick(last)} ${opts.unit} (${sensorName(top.id).toLowerCase()}). Over the last ${span} it ${trend}${Math.abs(last - first) < opts.flat ? "" : ` to ${opts.tick(last)}`}.`;
    summary.textContent = text;
    container.setAttribute("aria-label", `${opts.name}. ${text}`);
  }

  function renderCharts() {
    if (page !== "history" || !state.nodes.length) return;  // Hidden charts have no width
    renderLegend(state.nodes);
    const b = state.co2_bands;
    drawChart($("#chart-co2"), $("#sum-co2"), 3, {
      name: "Air, CO₂ in ppm", unit: "ppm", flat: 50,
      domain: (lo, hi) => [Math.min(400, Math.floor(lo / 100) * 100), Math.max(b.poor + 200, Math.ceil(hi / 100) * 100 + 100)],
      bands: [{ from: -1e9, to: b.fair, cls: "band-good" }, { from: b.fair, to: b.poor, cls: "band-fair" }, { from: b.poor, to: 1e9, cls: "band-poor" }],
      tick: (v) => String(Math.round(v)),
    });
    drawChart($("#chart-temp"), $("#sum-temp"), 1, {
      name: "Temperature in °C", unit: "°C", flat: 0.5,
      domain: (lo, hi) => [Math.floor(lo - 0.5), Math.ceil(hi + 0.5)],
      tick: (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1)),
    });
  }

  function renderHistory() {
    const f = fb();
    const ended = ((state.alerts && state.alerts.ended) || []).map((a) => ({
      wall_ms: a.ended_ms, level: "fine", text: `Cleared: ${a.message}`, tech: `alert ${a.key} ended`,
    }));
    const items = [...(f ? f.timeline : []), ...ended].sort((a, b) => b.wall_ms - a.wall_ms);
    renderTimeline($("#timeline"), items);
    renderCharts();
  }

  /* ---- Sensors: one table row per sensor ---- */
  function makeRow(id) {
    const row = $("#node-tpl").content.firstElementChild.cloneNode(true);
    const next = [...cards.keys()].filter((k) => k > id).sort((a, b) => a - b)[0];
    $("#nodes").insertBefore(row, next === undefined ? null : cards.get(next));
    cards.set(id, row);
    return row;
  }
  function setValue(row, key, value, digits) {
    const cell = $(`[data-k="${key}"]`, row);
    $(".v", cell).textContent = fmt(value, digits);
    cell.toggleAttribute("data-invalid", value == null);
    return cell;
  }
  function co2Level(ppm, warmup) {
    if (ppm == null) return warmup ? "warmup" : "none";
    if (ppm < state.co2_bands.fair) return "good";
    return ppm < state.co2_bands.poor ? "fair" : "poor";
  }
  const SIGNAL = ["very weak", "weak", "fair", "good", "strong"];
  function updateCard(n) {
    const row = cards.get(n.id) || makeRow(n.id);
    const t = n.telemetry || {};
    row.dataset.status = n.status;
    $(".nr-area", row).textContent = sensorName(n.id);
    const status = $(".status", row);
    status.dataset.status = n.status;
    $(".status-text", status).textContent = STATUS[n.status][0];
    setIcon($("svg", status), STATUS[n.status][1]);

    const rssi = t.rssi_dbm;
    const bars = !rssi ? 0 : rssi >= -55 ? 4 : rssi >= -65 ? 3 : rssi >= -75 ? 2 : rssi >= -85 ? 1 : 0;
    const meta = [`Sensor ${n.id}`];
    if (n.simulated) meta.push("Simulated");
    if (rssi && n.status !== "offline") meta.push(`${SIGNAL[bars]} signal`);
    if (n.status !== "online" && n.age_s != null) meta.push(`last reading ${Math.round(n.age_s)} s ago`);
    $(".nr-meta", row).textContent = meta.join(" · ");
    const linkLine = $(".nr-link", row);
    linkLine.textContent = [rssi ? `${rssi} dBm` : null, `${fmt(n.loss_pct, 1)}% lost`,
      n.rtt_ms == null ? null : `${fmt(n.rtt_ms, 0)} ms`, n.age_s < 1.5 ? "now" : `${Math.round(n.age_s)} s ago`].filter(Boolean).join(" · ");
    // Loss counts recovery by retries (gateway retry tracking), not raw Wi-Fi loss.
    linkLine.title = `Unrecovered message loss: ${n.lost}; recovered late: ${n.recovered || 0}; ` +
      `sequence gaps first detected: ${n.gaps_detected || 0}; duplicates: ${n.duplicates || 0}. ` +
      "Retries can recover data; this is not raw Wi-Fi transmission loss.";

    setValue(row, "temp", t.temperature_c, 1);
    setValue(row, "hum", t.humidity_pct, 0);
    setValue(row, "pir", t.pir_pct, 0);
    const co2 = setValue(row, "co2", t.co2_ppm, 0);
    const level = co2Level(t.co2_ppm, t.co2_warmup);
    const chip = $(".chip", co2);
    chip.dataset.level = level;
    chip.textContent = CO2_LEVEL[level];

    const a = t.audio;
    const sound = $('[data-k="audio"]', row);
    sound.toggleAttribute("data-invalid", !a);
    $(".nr-sound", sound).textContent = a ? (AUDIO[a.class] || AUDIO.unknown)[0] : "No reading";
    $(".nr-conf", sound).textContent = a && a.class !== "unknown" ? `${a.confidence}% sure` : "";
    $(".nr-probs", sound).textContent = a ? `background ${a.probs[0]}% · speech ${a.probs[1]}% · sudden ${a.probs[3]}%` : "";
  }
  function renderSensors() {
    const nodes = state.nodes;
    $("#empty").hidden = nodes.length > 0;
    $("#nodes-table").hidden = nodes.length === 0;
    const f = fb();
    $("#sensors-lead").textContent = f ? f.sensors.text + "." : "";
    nodes.forEach(updateCard);
    $("#footnote").textContent = state.dropped ? `${state.dropped} unreadable messages ignored.` : "";
  }

  /* ---- Setup: voice setup, report interval ---- */
  const dialog = $("#voice-dialog");
  let dialogOpener = null;
  let listening = false;

  function progressItems(list, zones) {
    list.replaceChildren(...zones.map((z) => {
      const li = make("li", "progress-item");
      const label = make("span", "", z.name);
      const bar = make("span", "bar");
      bar.setAttribute("role", "progressbar");
      bar.setAttribute("aria-label", `${z.name} voice setup`);
      bar.setAttribute("aria-valuemin", "0");
      bar.setAttribute("aria-valuemax", "100");
      bar.setAttribute("aria-valuenow", String(z.progress_pct));
      bar.style.setProperty("--p", `${z.progress_pct}%`);
      const word = make("span", "progress-word", z.done ? "Done ✓" : z.in_progress ? `${z.progress_pct}%` : "Not set up");
      li.append(label, bar, word);
      return li;
    }));
  }

  function renderSetup() {
    const f = fb();
    if (!f) return;
    const v = f.voice;
    $("#voice-text").textContent = v.text;
    progressItems($("#voice-zones"), v.zones);
    $("#voice-open").disabled = $("#voice-reset").disabled = !v.enabled;
    $("#voice-open").textContent = v.state === "done" ? "Set up again" : "Set up voice detection";

    const intervals = f.zones.map((z) => (state.classroom.zones.find((c) => c.zone === z.zone) || {}).report_interval_ms);
    const current = intervals.find((x) => x);
    if (!intervalBusy) $$('input[name="interval"]').forEach((r) => { r.checked = Number(r.value) === current; });

    if (dialog.open) {
      progressItems($("#dialog-zones"), v.zones);
      if (listening && v.state === "done") showStep("done");
    }
    renderLoud(f);
  }

  function showStep(step) {
    $$("[data-step]", dialog).forEach((s) => { s.hidden = s.dataset.step !== step; });
    $("#dialog-start").hidden = step !== "intro";
    $("#dialog-close").hidden = step !== "done";
    $("#dialog-cancel").textContent = step === "listening" ? "Stop and discard" : "Cancel";
    $("#dialog-cancel").hidden = step === "done";
    if (step === "done") { listening = false; $("#dialog-close").focus(); announcer.textContent = "Voice setup done."; }
  }
  $("#voice-open").addEventListener("click", (e) => {
    dialogOpener = e.currentTarget;
    $("#dialog-error").hidden = true;
    showStep("intro");
    dialog.showModal();
    $("#dialog-start").focus();
  });
  $("#dialog-start").addEventListener("click", async () => {
    try {
      await post("/api/calibrate");
      listening = true;
      showStep("listening");
      announcer.textContent = "Listening. Keep only the lecturer speaking.";
      poll(true);
    } catch (e) {
      $("#dialog-error").textContent = e.message;
      $("#dialog-error").hidden = false;
    }
  });
  $("#dialog-cancel").addEventListener("click", async () => {
    if (listening) {
      try { await post("/api/calibrate/reset"); announcer.textContent = "Voice setup stopped and discarded."; } catch (e) { /* Shown on next poll */ }
      listening = false;
    }
    dialog.close();
  });
  $("#dialog-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => { if (dialogOpener) dialogOpener.focus(); poll(true); });

  $("#voice-reset").addEventListener("click", async () => {
    if (!window.confirm("Start voice setup over? The current setup is deleted, and the system uses loudness only until you set it up again.")) return;
    const error = $("#voice-error");
    error.hidden = true;
    try {
      await post("/api/calibrate/reset");
      announcer.textContent = "Voice setup deleted.";
      poll(true);
    } catch (e) { error.textContent = e.message; error.hidden = false; }
  });

  /* ---- Setup: noise limit (excessive noise), one area at a time ---- */
  // Placeholder target: find a cited classroom noise limit before the report.
  const TARGET_DB = 70;
  // AC RMS of a 12-bit ADC can't pass about 2048 counts; a sine at full
  // scale is about 1448. Above MIC_NEAR_TOP the reading may be clipping.
  const MIC_TOP = 2048, MIC_NEAR_TOP = 1400, TOO_QUIET = 4;
  const loudDialog = $("#loud-dialog");
  $$("[data-target-db]").forEach((el) => { el.textContent = TARGET_DB; });
  let loudOpener = null;
  let loud = null;  // {areas: [zone, ...], i, phase: intro|ready|capturing|saved|done, started, seen}

  const loudArea = (zone) => {
    const f = fb();
    return f && f.loudness.areas.find((a) => a.zone === zone);
  };
  const meterPct = (rms) => Math.round(100 * Math.min(1, Math.log1p(rms) / Math.log1p(MIC_TOP)));

  function renderLoud(f) {
    const l = f.loudness;
    $("#loud-text").textContent = l.text;
    $("#loud-zones").replaceChildren(...l.areas.map((a) => {
      const li = make("li", "loud-item");
      const tag = make("span", "loud-word", a.capturing ? "Listening…" : a.set ? "Set" : "Not set");
      tag.dataset.set = a.set ? "yes" : "no";
      const raw = make("span", "tech", a.level != null ? `limit ${a.level.toFixed(1)} RMS` : "");
      li.append(make("span", "", a.name), raw, tag);
      return li;
    }));
    $("#loud-open").textContent = l.state === "done" ? "Set again" : "Set noise limit";
    $("#loud-clear").hidden = !l.areas.some((a) => a.set);
    if (loudDialog.open && loud && loud.phase !== "intro" && loud.phase !== "done") renderLoudStep();
  }

  function loudButtons(step) {
    const p = loud ? loud.phase : "";
    $("#loud-start").hidden = step !== "intro";
    $("#loud-capture").hidden = step !== "area" || p === "saved";
    $("#loud-next").hidden = step !== "area" || p !== "saved";
    $("#loud-again").hidden = step !== "area" || p !== "saved";
    $("#loud-skip").hidden = step !== "area" || p === "saved";
    $("#loud-close").hidden = step !== "done";
    $("#loud-cancel").hidden = step === "done";
    $("#loud-cancel").textContent = step === "area" ? "Close" : "Cancel";
  }
  function showLoudStep(step) {
    $$("[data-lstep]", loudDialog).forEach((s) => { s.hidden = s.dataset.lstep !== step; });
    loudButtons(step);
  }

  function renderLoudStep() {
    const a = loudArea(loud.areas[loud.i]);
    if (!a) return;
    const node = (state.nodes || []).find((n) => n.id === a.node_id);
    const audio = node && node.status !== "offline" && node.telemetry && node.telemetry.audio;
    const rms = audio && typeof audio.rms === "number" ? audio.rms : null;
    const err = $("#loud-dialog-error");

    if (loud.phase === "capturing") {
      if (a.capturing) loud.seen = true;
      if (!a.capturing && (loud.seen || Date.now() - loud.started > 7000)) {
        if (a.error) {
          loud.phase = "ready";
          err.textContent = `Couldn't set it: ${a.error} Try again.`;
          err.hidden = false;
        } else {
          loud.phase = "saved";
          announcer.textContent = `Noise limit saved for the ${a.name.toLowerCase()}.`;
        }
      }
    }

    const place = a.name.charAt(0).toLowerCase() + a.name.slice(1);
    $("#loud-step").textContent = `Area ${loud.i + 1} of ${loud.areas.length} · ${a.name}`;
    $("#loud-area-title").textContent = loud.phase === "saved" ? "Saved" : "Make the sound now";
    $("#loud-how").textContent = loud.phase === "saved"
      ? `Above this level, the ${place} show Excessive noise. You can stop the sound.`
      : `Stand by the ${place} sensor (sensor ${a.node_id}). Hold the phone next to it, keep the meter at ${TARGET_DB} dB, then press Capture.`;

    const meter = $("#loud-meter");
    const pct = rms == null ? 0 : meterPct(rms);
    meter.style.setProperty("--p", `${pct}%`);
    meter.setAttribute("aria-valuenow", String(pct));
    meter.dataset.top = rms != null && rms >= MIC_NEAR_TOP ? "yes" : "no";
    const limit = $("#loud-limit");
    limit.hidden = a.level == null;
    if (a.level != null) limit.style.left = `${meterPct(a.level)}%`;
    const word = $("#loud-word");
    const missing = !a.online || rms == null;
    word.textContent = missing ? "This sensor isn't sending sound readings."
      : rms >= MIC_NEAR_TOP ? "Close to the most this microphone can read. Move the phone back a little."
      : rms < TOO_QUIET ? "Too quiet. Turn the sound up."
      : loud.phase === "saved" ? "The line marks the saved limit."
      : "Hearing it.";
    word.dataset.level = missing || rms >= MIC_NEAR_TOP || rms < TOO_QUIET ? "warn" : "ok";
    $("#loud-raw").textContent = `now ${rms == null ? "—" : rms.toFixed(1)} RMS (ADC counts)` +
      (a.level != null ? ` · limit ${a.level.toFixed(1)}` : "");

    const cap = $("#loud-capture");
    cap.textContent = loud.phase === "capturing" ? `Listening… ${a.capture_left_s ?? 5} s` : "Capture";
    cap.setAttribute("aria-disabled", loud.phase === "capturing" ? "true" : "false");
    loudButtons("area");
  }

  function loudGo(i) {
    $("#loud-dialog-error").hidden = true;
    if (i >= loud.areas.length) {
      loud.phase = "done";
      const f = fb();
      $("#loud-done-text").textContent = f && f.loudness.areas.every((a) => a.set)
        ? "Every area has a noise limit." : "Areas you skipped keep showing Talking.";
      showLoudStep("done");
      $("#loud-close").focus();
      return;
    }
    loud.i = i;
    loud.phase = "ready";
    showLoudStep("area");
    renderLoudStep();
    $("#loud-capture").focus();
  }

  $("#loud-open").addEventListener("click", (e) => {
    const f = fb();
    if (!f) return;
    loudOpener = e.currentTarget;
    loud = { areas: f.loudness.areas.map((a) => a.zone), i: 0, phase: "intro" };
    $("#loud-dialog-error").hidden = true;
    showLoudStep("intro");
    loudDialog.showModal();
    $("#loud-start").focus();
  });
  $("#loud-start").addEventListener("click", () => loudGo(0));
  $("#loud-skip").addEventListener("click", () => loudGo(loud.i + 1));
  $("#loud-next").addEventListener("click", () => loudGo(loud.i + 1));
  $("#loud-again").addEventListener("click", () => { loud.phase = "ready"; renderLoudStep(); $("#loud-capture").focus(); });
  $("#loud-capture").addEventListener("click", async () => {
    if (loud.phase === "capturing") return;
    const err = $("#loud-dialog-error");
    err.hidden = true;
    try {
      await post("/api/loudness/capture", { zone: loud.areas[loud.i] });
      Object.assign(loud, { phase: "capturing", started: Date.now(), seen: false });
      announcer.textContent = "Listening for 5 seconds. Keep the sound steady.";
      renderLoudStep();
      poll(true);
    } catch (e) { err.textContent = e.message; err.hidden = false; }
  });
  $("#loud-cancel").addEventListener("click", () => loudDialog.close());
  $("#loud-close").addEventListener("click", () => loudDialog.close());
  loudDialog.addEventListener("close", () => { loud = null; if (loudOpener) loudOpener.focus(); poll(true); });

  $("#loud-clear").addEventListener("click", async () => {
    if (!window.confirm("Remove the noise limit from every area? Noisy areas will show Talking until you set it again.")) return;
    const error = $("#loud-error");
    error.hidden = true;
    const f = fb();
    const set = f ? f.loudness.areas.filter((a) => a.set) : [];
    const results = await Promise.allSettled(set.map((a) => post("/api/loudness/clear", { zone: a.zone })));
    if (results.some((r) => r.status === "rejected")) {
      error.textContent = "Some areas couldn't be cleared. Try again.";
      error.hidden = false;
    } else announcer.textContent = "Noise limits removed.";
    poll(true);
  });

  let intervalBusy = false;
  $$('input[name="interval"]').forEach((r) => r.addEventListener("change", async () => {
    const ms = Number(r.value);
    const status = $("#interval-status");
    const nodes = state ? state.nodes : [];
    if (!nodes.length) { status.textContent = "No sensors to update yet."; return; }
    intervalBusy = true;
    status.textContent = "Updating sensors…";
    const results = await Promise.allSettled(nodes.map((n) => post(`/api/nodes/${n.id}/config`, { report_interval_ms: ms })));
    const failed = results.filter((x) => x.status === "rejected").length;
    status.textContent = failed ? `${failed} sensor${failed > 1 ? "s" : ""} couldn't be updated. Try again.` :
      `Sent to all ${nodes.length} sensors. They confirm within a few seconds.`;
    setTimeout(() => { intervalBusy = false; }, 4000);
  }));

  /* ---- Main render ---- */
  function render() {
    renderHeader();
    renderBanners();
    renderMode();
    if (page === "live") renderLive();
    else if (page === "history") renderHistory();
    else if (page === "sensors") renderSensors();
    else if (page === "setup") renderSetup();
    if (page !== "live" && fb()) {  // Keep the headline announcement current on every page
      if (lastHeadline !== null && lastHeadline !== fb().headline) announcer.textContent = `${fb().headline}. ${fb().summary}`;
      lastHeadline = fb().headline;
    }
  }

  let timer = null;
  async function poll(once = false) {
    if (once !== true) timer = null;
    try {
      const res = await fetch("/api/state", { cache: "no-store" });
      if (!res.ok) throw new Error(res.status);
      state = await res.json();
      failures = 0;
      sampleLoud();
      setLive("live");
      render();
      document.dispatchEvent(new CustomEvent("mosaic:state", { detail: state }));  // intro.js listens
    } catch (e) {
      failures += 1;
      if (failures >= 2) { setLive("lost"); document.dispatchEvent(new Event("mosaic:lost")); }
    } finally {
      if (once !== true && !timer) timer = setTimeout(poll, POLL_MS);
    }
  }

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => state && render(), 150);  // Charts and plan orientation
  });
  route(false);
  poll();
})();
