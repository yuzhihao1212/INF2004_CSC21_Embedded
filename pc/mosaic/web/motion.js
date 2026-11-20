/* Click feedback ("press and glide", see motion.css and docs/decision-log.md).
 * Each choice group (.segmented) and the page tabs (.pages) get one pill that
 * slides to the chosen option. app.js often sets a radio's `checked` or a tab's
 * aria-current without a change event, so besides listening for clicks and
 * page changes this checks every half second whether the choice moved.
 * Nothing here changes what is selected; it only draws where the selection is. */
(() => {
  "use strict";
  const groups = [];

  function glide(el, pick) {
    const ind = document.createElement("span");
    ind.className = "glide-ind";
    ind.setAttribute("aria-hidden", "true");
    el.append(ind);
    el.classList.add("glide");
    const g = { el, ind, pick, target: null, y: null };
    groups.push(g);
    if ("ResizeObserver" in window) new ResizeObserver(() => sync(g, true)).observe(el);
    sync(g, true);
  }

  // Move g's pill onto its current choice. `force` re-measures even when the
  // choice is unchanged (resize, fonts, a page shown again).
  function sync(g, force) {
    const target = g.pick(g.el);
    if (target === g.target && !force) return;
    if (g.el.matches(".segmented")) {
      for (const l of g.el.children) if (l.tagName === "LABEL") l.classList.toggle("is-on", !!target && l.contains(target));
    }
    g.target = target;
    const box = target && (target.matches("input") ? target.nextElementSibling : target);
    const c = g.el.getBoundingClientRect(), t = box && box.getBoundingClientRect();
    if (!t || !c.width || !t.width) { g.ind.classList.remove("on"); g.y = null; return; }
    const x = t.left - c.left - g.el.clientLeft, y = t.top - c.top - g.el.clientTop;
    // First showing, or the choice is on another line of a wrapped group: appear, don't fly.
    const jump = g.y === null || Math.abs(y - g.y) > 2 || !g.ind.classList.contains("on");
    g.ind.classList.toggle("jump", jump);
    g.ind.style.transform = `translate(${x}px, ${y}px)`;
    g.ind.style.width = `${t.width}px`;
    g.ind.style.height = `${t.height}px`;
    g.ind.classList.toggle("dim", !!(target.matches("input") && target.disabled));
    if (jump) void g.ind.offsetWidth;   // Apply the jump before transitions come back
    g.ind.classList.add("on");
    g.ind.classList.remove("jump");
    g.y = y;
  }

  // A timer, not requestAnimationFrame: the click handlers in app.js have run
  // by then, and it still fires when the browser holds back animation frames.
  const syncAll = (force) => setTimeout(() => groups.forEach((g) => sync(g, force)), 0);

  document.querySelectorAll(".segmented").forEach((el) => glide(el, (f) => f.querySelector("input:checked")));
  const pages = document.querySelector(".pages");
  if (pages) glide(pages, (n) => n.querySelector('a[aria-current="page"]'));

  document.addEventListener("change", () => syncAll(false), true);
  document.addEventListener("click", () => syncAll(false), true);
  window.addEventListener("hashchange", () => syncAll(true));
  if (document.fonts) document.fonts.ready.then(() => syncAll(true));
  setInterval(() => syncAll(false), 500);

  // The theme button's icon turns as it changes.
  const theme = document.getElementById("theme-btn");
  if (theme) {
    theme.addEventListener("click", () => { theme.classList.remove("spin"); void theme.offsetWidth; theme.classList.add("spin"); });
    theme.addEventListener("animationend", () => theme.classList.remove("spin"));
  }
})();
