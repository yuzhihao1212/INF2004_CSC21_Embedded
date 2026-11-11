/* MOSAIC dashboard: five pages over one /api/state poll. No libraries.
 * Wording comes from the server (feedback.py); this file only lays it out. */
(() => {
  "use strict";

  const POLL_MS = 1000;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PAGES = { overview: "Overview", map: "Room map", history: "History", sensors: "Sensors", setup: "Setup" };
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
  const LINK_LABELS = { rssi: "Wi-Fi signal", loss: "Readings lost", rtt: "Response time", age: "Last reading" };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const announcer = $("#announcer");
  const alerter = $("#alerter");

  let state = null;
  let page = "overview";
  let rangeS = 300;
  let mapMetric = "activity";
  let failures = 0;
  let lastHeadline = null;
  const seenAlerts = new Set();
  const hidden = new Set();
  const cards = new Map();

  const series = (id) => `var(--series-${((id - 1) % 8) + 1})`;
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

  /* ---- Pages: #/overview ... #/setup; Back/Forward and links work ---- */
  function route(fromUser) {
    const [id, arg] = location.hash.replace(/^#\/?/, "").split("/");
    page = PAGES[id] ? id : "overview";
    if (page === "map" && arg) selectedZone = decodeURIComponent(arg);
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
    const box = $("#banners");
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
      card.append(icon("i-stop", "icon banner-icon"), text, hide);
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

  /* ---- Overview ---- */
  function renderOverview() {
    const f = fb();
    if (!f) return;
    const hero = $("#hero");
    hero.dataset.level = f.tiles[0].level;
    $("#headline").textContent = f.headline;
    $("#summary").textContent = f.summary;
    $("#hero-tech").textContent = `activity ${f.tech.activity} · air ${f.tech.air} · comfort ${f.tech.comfort} · mode ${f.tech.mode}`;
    if (lastHeadline !== null && lastHeadline !== f.headline) announcer.textContent = `${f.headline}. ${f.summary}`;
    lastHeadline = f.headline;

    for (const tile of f.tiles) {
      const node = $(`#tile-${tile.id}`);
      node.dataset.level = tile.level;
      setIcon($(".level-icon", node), LEVEL_ICON[tile.level]);
      $(".level-icon", node).setAttribute("class", `icon level-icon lvl-${tile.level}`);
      $(".lt", node).textContent = tile.label;
      $(".tile-why", node).textContent = tile.why;
      $(".tech", node).textContent = [tile.tech, tile.detail].filter(Boolean).join(" · ");
      node.setAttribute("aria-label", `${tile.title}: ${tile.label}, ${LEVEL_WORD[tile.level]}. ${tile.why}`);
    }
    renderPlan($("#mini-map"), "activity", true);
    renderTimeline($("#latest"), f.timeline.slice(0, 4));
  }

  /* ---- Room map ---- */
  $$('input[name="map-metric"]').forEach((r) => r.addEventListener("change", () => { mapMetric = r.value; if (state) renderMapPage(); }));

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
    if (container.dataset.key !== key) buildPlan(container, portrait, compact, f.zones, key);
    for (const z of f.zones) {
      const el = container.querySelector(`[data-zone="${CSS.escape(z.zone)}"]`);
      const offline = z.status === "Not connected";
      const m = z[metric];
      const level = offline ? "none" : m.level;
      const label = offline ? "Not connected" : m.label;
      el.dataset.level = level;
      el.dataset.offline = String(offline);
      if (!compact) el.setAttribute("aria-pressed", String(z.zone === selectedZone));
      el.setAttribute("aria-label", `${z.name}: ${label}, ${LEVEL_WORD[level]}.${m.why ? " " + m.why : ""}`);
      const state = $(".plan-state", el);
      state.dataset.level = level;
      setIcon($(".level-icon", state), LEVEL_ICON[level] || LEVEL_ICON.none);
      $(".level-icon", state).setAttribute("class", `icon level-icon lvl-${level}`);
      $("span", state).textContent = label;
      const tech = $(".tech", el);
      if (tech) tech.textContent = `zone ${z.zone} · sensor ${z.node_id}${m.tech ? " · " + m.tech : ""}`;
    }
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
      const el = make(compact ? "a" : "button", "plan-zone");
      el.dataset.zone = z.zone;
      if (compact) el.href = `#/map/${encodeURIComponent(z.zone)}`;
      else {
        el.type = "button";
        el.setAttribute("aria-controls", "zone-detail");
        el.addEventListener("click", () => { selectedZone = z.zone; renderMapPage(); });
      }
      Object.assign(el.style, { left: pct(Math.min(x0, x1), vbW), top: pct(Math.min(y0, y1), vbH),
                                width: pct(Math.abs(x1 - x0), vbW), height: pct(Math.abs(y1 - y0), vbH) });
      const chip = make("span", "plan-chip");
      chip.append(make("span", "plan-name", z.name), levelLine("none", "", "plan-state"));
      if (!compact) chip.append(make("span", "tech"));
      el.append(chip);
      nodes.push(el);
    }
    container.replaceChildren(...nodes);
  }

  function renderMapPage() {
    const f = fb();
    if (!f) return;
    const rank = { act_now: 3, heads_up: 2, fine: 1, none: 0 };
    if (!f.zones.some((z) => z.zone === selectedZone)) {  // Default: the area that needs most attention
      selectedZone = [...f.zones].sort((a, b) => rank[b.activity.level] - rank[a.activity.level])[0].zone;
    }
    renderPlan($("#zone-map"), mapMetric);
    const z = f.zones.find((x) => x.zone === selectedZone);
    $("#zone-detail-h").textContent = z.name;
    $("#zone-detail-sensor").textContent = `Sensor ${z.node_id}: ${z.status.toLowerCase()}`;
    const rows = [["Sound", "i-sound", z.activity, z.activity.why], ["Air", "i-air", z.air, z.air.detail],
                  ["Temperature", "i-thermo", z.comfort, z.comfort.detail], ["Movement", "i-motion", z.motion, z.motion.detail]];
    $("#zone-detail-list").replaceChildren(...rows.flatMap(([title, ic, m, extra]) => {
      const dt = make("dt");
      dt.append(icon(ic, "icon icon-sm"), make("span", "", title));
      const dd = make("dd");
      dd.append(levelLine(m.level, m.label, "level-line"));
      if (extra) dd.append(make("span", "detail-extra", extra));
      return [dt, dd];
    }));
    $("#zone-detail-tech").textContent = `zone ${z.zone} · layout [${z.layout}] · ${z.activity.tech} · ${z.air.tech} · ${z.comfort.tech}`;
  }

  /* ---- History ---- */
  function renderTimeline(list, items) {
    if (!items.length) {
      list.replaceChildren(make("li", "timeline-empty", "Nothing yet. Changes in the room appear here."));
      return;
    }
    list.replaceChildren(...items.map((item) => {
      const li = make("li", "timeline-item");
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

  /* ---- Sensors ---- */
  function makeCard(id) {
    const card = $("#node-tpl").content.firstElementChild.cloneNode(true);
    card.style.setProperty("--series", series(id));
    $(".series-key", card).style.borderTopStyle = dash(id) ? "dashed" : "solid";
    card.querySelectorAll(".link-item").forEach((item) => {
      const label = LINK_LABELS[item.dataset.k];
      item.title = label;
      item.insertAdjacentHTML("afterbegin", `<span class="sr-only">${label}: </span>`);
    });
    const next = [...cards.keys()].filter((k) => k > id).sort((a, b) => a - b)[0];
    $("#nodes").insertBefore(card, next === undefined ? null : cards.get(next));
    cards.set(id, card);
    return card;
  }
  function setMetric(card, key, value, digits) {
    const m = $(`[data-k="${key}"]`, card);
    $(".v", m).textContent = fmt(value, digits);
    m.toggleAttribute("data-invalid", value == null);
    return m;
  }
  function co2Level(ppm, warmup) {
    if (ppm == null) return warmup ? "warmup" : "none";
    if (ppm < state.co2_bands.fair) return "good";
    return ppm < state.co2_bands.poor ? "fair" : "poor";
  }
  function updateCard(n) {
    const card = cards.get(n.id) || makeCard(n.id);
    const t = n.telemetry || {};
    card.dataset.status = n.status;
    $(".node-name", card).textContent = `Sensor ${n.id} · ${sensorName(n.id)}`;
    $(".sim-chip", card).hidden = !n.simulated;
    const status = $(".status", card);
    status.dataset.status = n.status;
    $(".status-text", status).textContent = STATUS[n.status][0];
    setIcon($("svg", status), STATUS[n.status][1]);
    setMetric(card, "temp", t.temperature_c, 1);
    setMetric(card, "hum", t.humidity_pct, 0);
    const co2 = setMetric(card, "co2", t.co2_ppm, 0);
    const level = co2Level(t.co2_ppm, t.co2_warmup);
    const chip = $(".chip", co2);
    chip.dataset.level = level;
    chip.textContent = CO2_LEVEL[level];
    if (t.co2_ppm != null) $(".marker", co2).style.left = `${clamp((t.co2_ppm - 400) / 1200, 0, 1) * 100}%`;
    const pir = setMetric(card, "pir", t.pir_pct, 0);
    $(".meter span", pir).style.width = `${t.pir_pct || 0}%`;

    const audio = $(".audio", card);
    const a = t.audio;
    audio.toggleAttribute("data-invalid", !a);
    const [name, ic] = a ? (AUDIO[a.class] || AUDIO.unknown) : ["No sound reading", "i-mute"];
    $(".audio-class", audio).textContent = name;
    setIcon($(".audio-icon", audio), ic);
    $(".audio-conf", audio).textContent = a && a.class !== "unknown" ? `${a.confidence}%` : "";
    const probs = a ? [a.probs[0], a.probs[1], a.probs[3]] : [0, 0, 0];
    const top = probs.indexOf(Math.max(...probs));
    audio.querySelectorAll(".probs span").forEach((s, i) => {
      s.querySelector("i").style.setProperty("--p", `${probs[i]}%`);
      s.toggleAttribute("data-top", !!a && i === top && a.class !== "unknown");
    });

    const link = (k, text, bad) => {
      const item = $(`[data-k="${k}"]`, card);
      $(".lv", item).textContent = text;
      item.toggleAttribute("data-bad", !!bad);
      return item;
    };
    const rssi = t.rssi_dbm;
    const bars = !rssi ? 0 : rssi >= -55 ? 4 : rssi >= -65 ? 3 : rssi >= -75 ? 2 : rssi >= -85 ? 1 : 0;
    link("rssi", rssi ? `${["Very weak", "Weak", "Fair", "Good", "Strong"][bars]} (${rssi} dBm)` : "—", rssi && bars < 2)
      .querySelectorAll(".bars i").forEach((b, i) => b.toggleAttribute("data-on", i < bars));
    link("loss", `${fmt(n.loss_pct, 1)}% lost`, n.loss_pct > 5);
    link("rtt", n.rtt_ms == null ? "—" : `${fmt(n.rtt_ms, 0)} ms`, n.rtt_ms > 100);
    link("age", n.age_s < 1.5 ? "now" : `${Math.round(n.age_s)} s ago`, n.status !== "online");
  }
  function renderSensors() {
    const nodes = state.nodes;
    $("#empty").hidden = nodes.length > 0;
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
    if (page === "overview") renderOverview();
    else if (page === "map") renderMapPage();
    else if (page === "history") renderHistory();
    else if (page === "sensors") renderSensors();
    else if (page === "setup") renderSetup();
    if (page !== "overview" && fb()) {  // Keep the headline announcement current on every page
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
      setLive("live");
      render();
    } catch (e) {
      failures += 1;
      if (failures >= 2) setLive("lost");
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
