(function () {
  "use strict";

  var LOG_CAP = 500;
  var ARM_MS = 4000;

  function glyph(node) {
    var name = node.dataset.glyph;
    if (!name || node.firstChild) return;
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", (window.ICONS || {})[name] || "");
    node.append(path);
  }

  function railIcon(node) {
    if (node.dataset.iconDone) return;
    node.dataset.iconDone = "1";
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 -960 960 960");
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "shrink-0 size-5");
    svg.dataset.glyph = node.dataset.icon;
    glyph(svg);
    node.prepend(svg);
  }

  function measureMore(box) {
    var body = box.querySelector("[data-more-body]");
    var toggle = box.querySelector("[data-more-toggle]");
    if (!body || !toggle || toggle.dataset.ready) return;
    toggle.dataset.ready = "1";
    if (body.scrollHeight - body.clientHeight > 2) toggle.hidden = false;
    toggle.addEventListener("click", function () {
      var open = body.classList.toggle("is-open");
      toggle.textContent = open ? toggle.dataset.lessLabel : toggle.dataset.moreLabel;
    });
  }

  function hexNote(input) {
    var note = document.getElementById(input.dataset.hex);
    if (!note) return;
    var stripped = input.value.replace(/\s|^0x/gi, "");
    note.textContent = !stripped
      ? "0 " + input.dataset.bytesLabel
      : /^[0-9a-f]+$/i.test(stripped)
        ? Math.ceil(stripped.length / 2) + " " + input.dataset.bytesLabel
        : input.dataset.invalidLabel;
  }

  function bitsNote(box) {
    var label = document.getElementById(box.dataset.bits);
    if (!label) return;
    var held = 0;
    box.querySelectorAll("input[type=checkbox]").forEach(function (one) {
      if (one.checked) held |= Number(one.value);
    });
    label.textContent = "0x" + (held >>> 0).toString(16).toUpperCase().padStart(8, "0");
  }

  function remember(box) {
    if (box.dataset.foldReady) return;
    box.dataset.foldReady = "1";
    var stored = null;
    try { stored = localStorage.getItem("stef.fold." + box.id); } catch (e) {}
    if (stored === "open" || stored === "shut") box.open = stored === "open";
    box.addEventListener("toggle", function () {
      try { localStorage.setItem("stef.fold." + box.id, box.open ? "open" : "shut"); } catch (e) {}
    });
  }

  function hydrate(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("[data-glyph]").forEach(glyph);
    scope.querySelectorAll("[data-icon]").forEach(railIcon);
    scope.querySelectorAll("[data-more]").forEach(measureMore);
    scope.querySelectorAll("[data-hex]").forEach(hexNote);
    scope.querySelectorAll("[data-bits]").forEach(bitsNote);
    scope.querySelectorAll("details[id]").forEach(remember);
  }

  // ── Toasts ─────────────────────────────────────────────────────────────────

  function toast(kind, title, detail) {
    var tone =
      kind === "error" ? "border-red-500 text-red-600"
      : kind === "warn" ? "border-yellow-500 text-yellow-600"
      : "border-green-500 text-green-600";
    var box = document.createElement("div");
    box.className =
      "flex items-start gap-3 w-80 p-3 bg-surface border-l-4 rounded-md shadow-lg " + tone;
    box.setAttribute("role", "status");
    box.innerHTML =
      '<div class="min-w-0 flex-1"><div class="text-sm font-semibold"></div>' +
      '<div class="mt-0.5 font-mono text-xs text-gray-500 break-all"></div></div>';
    box.firstChild.firstChild.textContent = title;
    box.firstChild.lastChild.textContent = detail || "";
    document.getElementById("toasts").append(box);
    window.setTimeout(function () { box.remove(); }, 7000);
  }

  // ── Arming a hazardous run ─────────────────────────────────────────────────

  function rest(button) {
    window.clearTimeout(Number(button.dataset.timer));
    button.dataset.armed = "";
    button.className = button.dataset.resting;
    button.querySelector("span").textContent = button.dataset.restingLabel;
  }

  function arm(button, question, issue) {
    if (button.dataset.armed === "1") {
      rest(button);
      issue(true);
      return;
    }
    button.dataset.resting = button.dataset.resting || button.className;
    var label = button.querySelector("span");
    button.dataset.restingLabel = button.dataset.restingLabel || label.textContent;
    button.dataset.armed = "1";
    button.className =
      "inline-flex items-center gap-2 whitespace-nowrap text-gray-50 dark:text-gray-900 bg-red-600 border border-red-600 hover:bg-red-700 font-medium text-sm rounded-md pl-3 pr-1 py-1";
    label.textContent = question;
    button.dataset.timer = String(window.setTimeout(function () { rest(button); }, ARM_MS));
  }

  // ── The log ────────────────────────────────────────────────────────────────

  var paused = false;
  var withheld = [];

  function logBody() { return document.getElementById("logbody"); }

  function trim() {
    var body = logBody();
    while (body.childElementCount > LOG_CAP) body.firstElementChild.remove();
    body.scrollTop = body.scrollHeight;
  }

  function filterTo(source) {
    document.getElementById("logfilter").textContent =
      source === "all" ? "" : '.log-record:not([data-source="' + source + '"]){display:none}';
    document.querySelectorAll(".log-chip").forEach(function (chip) {
      chip.classList.toggle("bg-surface", chip.dataset.filter === source);
      chip.classList.toggle("text-gray-900", chip.dataset.filter === source);
      chip.classList.toggle("dark:text-white", chip.dataset.filter === source);
    });
  }

  function exportLog() {
    var text = Array.prototype.map
      .call(logBody().children, function (row) {
        return Array.prototype.map
          .call(row.children, function (cell) { return cell.textContent; })
          .join("\t");
      })
      .join("\n");
    var url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    var anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "stef-log.txt";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  // ── Theme ──────────────────────────────────────────────────────────────────

  var SEG_ON = "bg-surface text-gray-900 dark:text-white ring-1 ring-gray-400 dark:ring-gray-600";
  var SEG_OFF = "text-gray-500 hover:text-gray-900 dark:hover:text-white";

  function applyTheme(choice) {
    document.documentElement.classList.toggle("dark", choice === "dark");
    try { localStorage.setItem("stef.theme", choice); } catch (e) {}
    document.querySelectorAll("#theme button").forEach(function (button) {
      button.className =
        "px-3 py-1 text-xs rounded-md cursor-pointer " +
        (button.dataset.theme === choice ? SEG_ON : SEG_OFF);
    });
  }

  // ── Wiring ─────────────────────────────────────────────────────────────────

  document.addEventListener("DOMContentLoaded", function () {
    hydrate(document);
    applyTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
    filterTo("all");

    document.querySelectorAll("#theme button").forEach(function (button) {
      button.addEventListener("click", function () { applyTheme(button.dataset.theme); });
    });

    var pause = document.querySelector(".log-pause");
    pause.addEventListener("click", function () {
      paused = !paused;
      pause.textContent = paused ? pause.dataset.resumeLabel : pause.dataset.pauseLabel;
      if (!paused && withheld.length) {
        logBody().insertAdjacentHTML("beforeend", withheld.join(""));
        withheld = [];
        hydrate(logBody());
        trim();
      }
    });
    document.querySelector(".log-clear").addEventListener("click", function () {
      logBody().replaceChildren();
      withheld = [];
    });
    document.querySelector(".log-export").addEventListener("click", exportLog);
    document.querySelectorAll(".log-chip").forEach(function (chip) {
      chip.addEventListener("click", function () { filterTo(chip.dataset.filter); });
    });
  });

  document.body.addEventListener("click", function (event) {
    if (event.target.closest("[data-nofold]")) event.preventDefault();
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var label = button.querySelector("span");
    var was = label.textContent;
    navigator.clipboard.writeText(button.dataset.copyPayload).then(
      function () {
        label.textContent = button.dataset.copied;
        window.setTimeout(function () { label.textContent = was; }, 1500);
      },
      function () { toast("error", button.dataset.failed); }
    );
  });

  document.addEventListener("input", function (event) {
    if (event.target.dataset.hex) hexNote(event.target);
  });

  document.addEventListener("change", function (event) {
    var bits = event.target.closest("[data-bits]");
    if (bits) bitsNote(bits);
  });

  document.body.addEventListener("htmx:load", function (event) { hydrate(event.detail.elt); });

  document.body.addEventListener("htmx:beforeSwap", function (event) {
    if (event.detail.target !== logBody() || !paused) return;
    withheld.push(event.detail.serverResponse);
    if (withheld.length > LOG_CAP) withheld.shift();
    event.detail.shouldSwap = false;
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target === logBody()) trim();
  });

  document.body.addEventListener("htmx:confirm", function (event) {
    if (!event.detail.question) return;
    event.preventDefault();
    arm(event.detail.elt, event.detail.question, event.detail.issueRequest);
  });

  document.body.addEventListener("htmx:responseError", function (event) {
    var body = event.detail.xhr.responseText || "";
    var said = body;
    try { said = JSON.parse(body).detail || body; } catch (e) {}
    toast("error", String(event.detail.xhr.status), said);
  });

  document.body.addEventListener("htmx:sendError", function () {
    toast("error", "Lost the event stream, retrying");
  });
})();
