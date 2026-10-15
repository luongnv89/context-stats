// context-stats site behaviour: mobile nav, copy buttons, scroll reveal.
// Everything degrades to a fully readable static page without JS.
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  // Sticky nav gains a hairline once the page scrolls.
  var nav = document.querySelector(".nav");
  if (nav) {
    var onScroll = function () { nav.classList.toggle("is-scrolled", window.scrollY > 8); };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // Mobile menu.
  var toggle = document.querySelector(".nav-toggle");
  var links = document.getElementById("nav-links");
  if (toggle && links) {
    var setMenu = function (open) {
      links.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    };
    toggle.addEventListener("click", function () {
      setMenu(!links.classList.contains("is-open"));
    });
    links.addEventListener("click", function (e) {
      if (e.target.closest("a")) setMenu(false);
    });
    // Escape closes the open menu and hands focus back to the toggle.
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && links.classList.contains("is-open")) {
        setMenu(false);
        toggle.focus();
      }
    });
  }

  // Copy-to-clipboard: [data-copy] holds the text, or [data-copy-target] points at an element.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy") ? resolve() : reject(new Error("copy failed")); }
      catch (err) { reject(err); }
      finally { document.body.removeChild(ta); }
    });
  }
  // On copy failure, select the text so the user can copy it by hand.
  function selectText(el) {
    if (!el || !window.getSelection) return;
    try {
      var range = document.createRange();
      range.selectNodeContents(el);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (err) { /* selection unsupported; the status message still explains */ }
  }
  document.querySelectorAll("[data-copy], [data-copy-target]").forEach(function (btn) {
    var label = btn.querySelector("[data-label]");
    var original = label ? label.textContent : "";
    var status = document.getElementById("copy-status");
    var resetTimer = null;
    btn.addEventListener("click", function () {
      var target = btn.getAttribute("data-copy-target");
      var targetEl = target ? document.getElementById(target) : null;
      var text = target ? (targetEl || {}).textContent : btn.getAttribute("data-copy");
      if (!text) return;
      var reset = function () {
        clearTimeout(resetTimer);
        resetTimer = setTimeout(function () {
          btn.classList.remove("is-done", "is-error");
          if (label) label.textContent = original;
        }, 1800);
      };
      copyText(text.trim()).then(function () {
        btn.classList.remove("is-error");
        btn.classList.add("is-done");
        if (label) label.textContent = "Copied";
        if (status) status.textContent = "Copied to clipboard: " + text.trim();
        reset();
      }, function () {
        btn.classList.remove("is-done");
        btn.classList.add("is-error");
        selectText(targetEl);
        if (label) label.textContent = "Press Ctrl+C";
        if (status) {
          status.textContent = targetEl
            ? "Copy failed. The text is selected; press Ctrl+C (Cmd+C on Mac) to copy it."
            : "Copy failed. Copy it manually: " + text.trim();
        }
        reset();
      });
    });
  });

  // Scroll reveal.
  var items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-in");
          io.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    items.forEach(function (el) { el.classList.add("is-in"); });
  }
})();
