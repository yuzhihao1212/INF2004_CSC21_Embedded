/* MOSAIC intro: the four-shard logo forms full screen ("orbit and lock"), waits
   for the first reading from the gateway (4 s at most), then flies into the
   header logo while the top bar slides down and the page content rises.

   Plays once per browser tab: the inline script in index.html sets
   html[data-intro="play"] when sessionStorage has no "mosaic-intro" key.
   Click or any key skips it. With reduced motion it is a short fade. */
(() => {
  "use strict";

  const replay = document.getElementById("intro-replay");
  if (replay) replay.addEventListener("click", () => {
    try { sessionStorage.removeItem("mosaic-intro"); } catch (e) {}
    location.hash = "#/live";
    location.reload();
  });

  const root = document.documentElement;
  const intro = document.getElementById("intro");
  if (root.dataset.intro !== "play" || !intro) return;
  try { sessionStorage.setItem("mosaic-intro", "1"); } catch (e) {}
  // Opened in a background tab: animations don't run there, so skip the intro.
  if (document.hidden) { root.dataset.intro = "done"; intro.remove(); return; }

  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (sel, el = intro) => el.querySelector(sel);
  const brand = document.querySelector(".brand");
  const brandMark = $(".brand-mark", brand);
  const brandWord = $(".wordmark", brand);
  const big = $(".intro-brand");
  const mark = $(".intro-mark");
  const extras = [$(".intro-tag"), $(".intro-status"), $(".intro-skip")];
  const DIRS = [[0, -1], [1, 0], [0, 1], [-1, 0]];
  const anims = [];
  const run = (el, frames, opts) => { const a = el.animate(frames, opts); anims.push(a); return a; };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const start = performance.now();

  // The big logo is the header logo scaled up by 1/k, so it lands on it exactly.
  function sizeBig() {
    const k = Math.max(0.3125, brand.getBoundingClientRect().width / (innerWidth * 0.8));
    intro.style.setProperty("--intro-mark", `${brandMark.getBoundingClientRect().width / k}px`);
    intro.style.setProperty("--intro-word", `${parseFloat(getComputedStyle(brandWord).fontSize) / k}px`);
    intro.style.setProperty("--intro-gap", `${(parseFloat(getComputedStyle(brand).columnGap) || 8) / k}px`);
  }
  sizeBig();
  if (document.fonts) document.fonts.ready.then(() => { if (!flying) sizeBig(); });

  // Live status line: first reading from app.js, or a lost connection.
  const statusBox = $(".intro-status");
  const statusText = $("#intro-status-text");
  let gotData;
  const ready = new Promise((r) => { gotData = r; });
  document.addEventListener("mosaic:state", (e) => {
    const nodes = (e.detail && e.detail.nodes) || [];
    const online = nodes.filter((n) => n.status === "online").length;
    statusBox.dataset.state = online ? "ok" : "wait";
    statusText.textContent = online ? `Connected to ${online} sensor${online === 1 ? "" : "s"}` : "Waiting for the sensors";
    gotData();
  }, { once: true });
  document.addEventListener("mosaic:lost", () => {
    statusBox.dataset.state = "lost";
    statusText.textContent = "Can't reach the gateway yet";
    gotData();
  }, { once: true });

  // 1. Form the logo (same choreography as the header logo).
  const FORM_MS = reduce ? 0 : 1900;
  if (!reduce) {
    const t0 = 150;
    $(".intro-spin").querySelectorAll(".intro-shard").forEach((p, i) => {
      const [dx, dy] = DIRS[i];
      run(p, [{ transform: `translate(${dx * 34}px, ${dy * 34}px) scale(.5)`, opacity: 0 }, { opacity: 1, offset: 0.25 }, { transform: "none", opacity: 1 }],
        { duration: 1100, delay: t0, easing: "cubic-bezier(.6, 0, .9, .6)", fill: "backwards" });
    });
    run($(".intro-spin"), [{ transform: "rotate(-540deg) scale(.6)" }, { transform: "none" }],
      { duration: 1100, delay: t0, easing: "cubic-bezier(.3, 0, .2, 1)", fill: "backwards" });
    run($(".intro-thud"), [{ transform: "scale(1)" }, { transform: "scale(.9)" }, { transform: "scale(1.06)" }, { transform: "scale(1)" }],
      { duration: 380, delay: t0 + 1100, easing: "ease-out" });
    run($(".intro-ring"), [{ transform: "scale(.7)", opacity: 0.8 }, { transform: "scale(1.6)", opacity: 0 }],
      { duration: 600, delay: t0 + 1110, easing: "ease-out" });
    $(".intro-word").querySelectorAll("span").forEach((s, i) => {
      run(s, [{ opacity: 0, transform: "translateY(14px)" }, { opacity: 1, transform: "none" }],
        { duration: 380, delay: t0 + 1200 + i * 55, easing: "cubic-bezier(.3, 1.4, .5, 1)", fill: "backwards" });
    });
    extras.forEach((el, i) => run(el, [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }],
      { duration: 400, delay: t0 + 1550 + i * 120, fill: "backwards" }));
  }

  // 2. Fly into the header logo while the page arrives behind it.
  let flying = false;
  function end() {
    root.dataset.intro = "done";
    intro.remove();
    removeEventListener("keydown", skip);
  }
  function fly() {
    if (flying) return;
    flying = true;
    if (reduce) { run(intro, [{ opacity: 1 }, { opacity: 0 }], { duration: 300, fill: "forwards" }).finished.then(end); return; }

    const W = big.getBoundingClientRect();
    const B = mark.getBoundingClientRect();
    const T = brandMark.getBoundingClientRect();
    const k = T.width / B.width;
    const tx = T.left + T.width / 2 - W.left - (B.left + B.width / 2 - W.left) * k;
    const ty = T.top + T.height / 2 - W.top - (B.top + B.height / 2 - W.top) * k;
    const settle = "cubic-bezier(.2, .8, .2, 1)";

    extras.forEach((el) => run(el, [{ opacity: 1 }, { opacity: 0 }], { duration: 250, fill: "forwards" }));
    run($(".intro-bg"), [{ opacity: 1 }, { opacity: 0 }], { duration: 450, delay: 250, fill: "forwards" });
    run(document.querySelector(".topbar"), [{ transform: "translateY(-100%)" }, { transform: "none" }],
      { duration: 500, delay: 250, easing: settle, fill: "backwards" });
    const page = document.querySelector("#main > .page:not([hidden])");
    const items = [document.querySelector(".banner-wrap"), ...(page ? page.children : [])];
    items.forEach((el, i) => el && run(el, [{ opacity: 0, transform: "translateY(16px)" }, { opacity: 1, transform: "none" }],
      { duration: 500, delay: 400 + i * 70, easing: settle, fill: "backwards" }));
    run(big, [{ transform: "none" }, { transform: `translate(${tx}px, ${ty}px) scale(${k})` }],
      { duration: 650, delay: 250, easing: "cubic-bezier(.6, 0, .2, 1)", fill: "forwards" }).finished.then(end);
  }

  // Skip: jump to the end of whatever is running, then fly at once.
  function skip(e) {
    if (e && e.type === "keydown" && ["Shift", "Control", "Alt", "Meta"].includes(e.key)) return;
    anims.forEach((a) => { try { a.finish(); } catch (err) {} });
    fly();
  }
  intro.addEventListener("click", skip);
  addEventListener("keydown", skip);

  // Safety net: never leave the dashboard covered. Animations stall in a
  // background tab, so this ends the intro without waiting for them.
  const hardEnd = () => {
    if (!intro.isConnected) return;
    skip();
    anims.forEach((a) => { try { a.finish(); } catch (err) {} });
    end();
  };
  setTimeout(hardEnd, 8000);
  document.addEventListener("visibilitychange", () => { if (document.hidden) hardEnd(); });

  const maxWait = reduce ? 1500 : 4000;
  Promise.all([wait(FORM_MS), Promise.race([ready, wait(maxWait - (performance.now() - start))])])
    .then(() => wait(reduce ? 0 : 450))
    .then(fly);
})();
