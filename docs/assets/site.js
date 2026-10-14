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
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    links.addEventListener("click", function (e) {
      if (e.target.closest("a")) {
        links.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
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
  document.querySelectorAll("[data-copy], [data-copy-target]").forEach(function (btn) {
    var label = btn.querySelector("[data-label]");
    var original = label ? label.textContent : "";
    var status = document.getElementById("copy-status");
    btn.addEventListener("click", function () {
      var target = btn.getAttribute("data-copy-target");
      var text = target ? (document.getElementById(target) || {}).textContent : btn.getAttribute("data-copy");
      if (!text) return;
      copyText(text.trim()).then(function () {
        btn.classList.add("is-done");
        if (label) label.textContent = "Copied";
        if (status) status.textContent = "Copied to clipboard: " + text.trim();
        setTimeout(function () {
          btn.classList.remove("is-done");
          if (label) label.textContent = original;
        }, 1800);
      }, function () {
        if (label) label.textContent = "Press Ctrl+C";
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
