/* Memora — put a secretary on your own site (plan/41 §8, M6).
 *
 * <script src="https://memo-ora.com/embed.js" data-code="YOUR-CODE" defer></script>
 *
 * One button in the corner and one iframe, created only when somebody opens it. No
 * dependencies, no globals beyond a single guard, and nothing is read from the host page:
 * this script runs on somebody else's site, so it must take nothing and leave nothing.
 */
(function () {
  "use strict";
  if (window.__memoraEmbed) return;
  window.__memoraEmbed = true;

  var me = document.currentScript;
  if (!me) return;
  var code = (me.getAttribute("data-code") || "").trim();
  if (!code) return;
  var origin = new URL(me.src, window.location.href).origin;
  var accent = me.getAttribute("data-accent") || "#1a5fe0";
  var side = me.getAttribute("data-side") === "left" ? "left" : "right";
  var label = me.getAttribute("data-label") || "";
  var z = 2147483000;

  var btn = document.createElement("button");
  btn.type = "button";
  btn.setAttribute("aria-label", label || "Chat");
  btn.style.cssText = [
    "position:fixed", "bottom:20px", side + ":20px", "z-index:" + z,
    "width:56px", "height:56px", "border-radius:28px", "border:0", "cursor:pointer",
    "background:" + accent, "color:#fff", "box-shadow:0 8px 24px rgba(0,0,0,.24)",
    "display:flex", "align-items:center", "justify-content:center", "padding:0",
  ].join(";");
  btn.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
    + ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>';

  var frame = null;
  var open = false;

  function panel() {
    if (frame) return frame;
    frame = document.createElement("iframe");
    frame.src = origin + "/secretary/" + encodeURIComponent(code) + "?embed=1";
    frame.title = label || "Memora";
    frame.setAttribute("allow", "microphone; clipboard-write");
    frame.style.cssText = [
      "position:fixed", "bottom:88px", side + ":20px", "z-index:" + z,
      "width:min(400px, calc(100vw - 32px))", "height:min(640px, calc(100vh - 120px))",
      "border:0", "border-radius:18px", "box-shadow:0 18px 48px rgba(0,0,0,.28)",
      "background:#fff", "display:none",
    ].join(";");
    document.body.appendChild(frame);
    return frame;
  }

  function toggle() {
    open = !open;
    panel().style.display = open ? "block" : "none";
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  btn.addEventListener("click", toggle);
  // Escape closes it, the way every panel on the web does.
  document.addEventListener("keydown", function (e) { if (open && e.key === "Escape") toggle(); });

  function mount() { document.body.appendChild(btn); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
