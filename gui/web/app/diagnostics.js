/* The diagnostics screen: it renders declarations and knows no subsystem. */
(function () {
  "use strict";

  var T = window.STEF_TEXT || {};

  // ── Making nodes ───────────────────────────────────────────────────────────

  function el(tag, props) {
    var node = document.createElement(tag);
    var extras = Array.prototype.slice.call(arguments, 2);
    for (var key in props || {}) {
      var value = props[key];
      if (value == null || value === false) continue;
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else if (key.slice(0, 2) === "on") node.addEventListener(key.slice(2), value);
      else if (key in node && key !== "list") node[key] = value;
      else node.setAttribute(key, value);
    }
    extras.forEach(function (child) {
      if (child == null) return;
      if (Array.isArray(child)) child.forEach(function (one) { if (one) node.append(one); });
      else node.append(child);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  function icon(name, extra) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 -960 960 960");
    svg.setAttribute("fill", "currentColor");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "shrink-0 " + (extra || "size-[18px]"));
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", (window.ICONS || {})[name] || "");
    svg.append(path);
    return svg;
  }

  function clock(seconds) {
    var when = new Date((seconds || 0) * 1000);
    return (
      String(when.getHours()).padStart(2, "0") + ":" +
      String(when.getMinutes()).padStart(2, "0") + ":" +
      String(when.getSeconds()).padStart(2, "0") + "." +
      String(when.getMilliseconds()).padStart(3, "0")
    );
  }

  function hex32(value) {
    return "0x" + (Number(value) >>> 0).toString(16).toUpperCase().padStart(8, "0");
  }

  // ── The visual language ────────────────────────────────────────────────────

  var CLS = {
    card: "bg-surface border border-gray-300 dark:border-gray-700 rounded-lg shadow-sm",
    cardHead: "flex items-center gap-3 px-4 py-2.5 border-b border-gray-300 dark:border-gray-700",
    cardBody: "flex flex-col gap-4 p-4",
    sub: "text-xs text-gray-500 dark:text-gray-400",
    lede: "text-sm font-medium text-gray-900 dark:text-white",
    spacer: "flex-1",
    hint: "text-xs text-gray-500 dark:text-gray-400",
    mono: "font-mono text-sm tabular-nums",

    btn: "inline-flex items-center gap-1.5 text-gray-900 bg-surface border border-gray-400 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-gray-400 font-medium rounded-md text-sm px-3 py-1.5 dark:text-gray-200 dark:border-gray-600 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed",
    btnPrimary: "inline-flex items-center gap-1.5 text-gray-50 dark:text-gray-900 bg-blue-700 border border-blue-700 hover:bg-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-300 font-medium rounded-md text-sm px-3 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed",
    btnDanger: "inline-flex items-center gap-1.5 text-red-600 bg-surface border border-red-500 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-300 font-medium rounded-md text-sm px-3 py-1.5 dark:hover:bg-red-900 disabled:opacity-40 disabled:cursor-not-allowed",
    btnArmed: "inline-flex items-center gap-1.5 text-gray-50 dark:text-gray-900 bg-red-600 border border-red-600 hover:bg-red-700 font-medium rounded-md text-sm px-3 py-1.5",
    btnQuiet: "inline-flex items-center gap-1.5 text-gray-500 bg-transparent border border-transparent hover:bg-gray-200 hover:text-gray-900 rounded-md text-xs px-2 py-1 dark:hover:bg-gray-700 dark:hover:text-white",

    tabbar: "flex gap-1 border-b border-gray-300 dark:border-gray-700",
    tabBase: "inline-flex items-center gap-2 px-4 py-2 -mb-px border-b-2 text-sm cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed ",
    tabOff: "border-transparent text-gray-500 hover:text-gray-900 dark:hover:text-white",
    tabOn: "border-gray-900 text-gray-900 font-semibold dark:border-white dark:text-white",

    segmented: "inline-flex gap-0.5 p-0.5 bg-inset border border-gray-300 dark:border-gray-700 rounded-md",
    segBase: "px-3 py-1 text-xs rounded cursor-pointer transition-colors ",
    segOff: "text-gray-500 hover:text-gray-900 dark:hover:text-white",
    segOn: "bg-surface text-gray-900 dark:text-white ring-1 ring-gray-400 dark:ring-gray-600",

    label: "block mb-1 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400",
    input: "bg-surface border border-gray-400 text-gray-900 text-sm rounded-md focus:ring-2 focus:ring-blue-300 block w-full px-2.5 py-1.5 dark:border-gray-600 dark:text-white",
    inputMono: "bg-surface border border-gray-400 text-gray-900 text-sm font-mono rounded-md focus:ring-2 focus:ring-blue-300 block w-full px-2.5 py-1.5 dark:border-gray-600 dark:text-white",
    inputSm: "bg-surface border border-gray-300 text-gray-900 text-xs font-mono rounded block w-full px-2 py-1 dark:border-gray-600 dark:text-white",
    checkbox: "w-3.5 h-3.5 text-blue-600 bg-surface border-gray-400 rounded-sm focus:ring-blue-300 dark:border-gray-600",

    divider: "-mx-4 border-t border-gray-300 dark:border-gray-700",
    well: "p-4 bg-inset border border-gray-300 dark:border-gray-700 rounded-lg",
    note: "px-3 py-2 text-sm text-gray-600 bg-inset border-l-4 border-gray-400 rounded-r-md dark:text-gray-300 dark:border-gray-600",
    noteError: "px-3 py-2 text-sm text-red-600 bg-inset border-l-4 border-red-500 rounded-r-md",

    table: "w-max min-w-full text-xs text-left border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden",
    th: "px-2.5 py-1.5 text-xs font-medium uppercase tracking-wide text-gray-500 bg-inset dark:text-gray-400",
    td: "px-2.5 py-1.5 border-t border-gray-300 dark:border-gray-700",

    logRow: "log-row-gui px-4 py-px hover:bg-gray-200/40 dark:hover:bg-gray-800",
  };

  function seg(on) { return CLS.segBase + (on ? CLS.segOn : CLS.segOff); }
  function tabClass(on) { return CLS.tabBase + (on ? CLS.tabOn : CLS.tabOff); }

  var OUTCOME = {
    idle: { key: "idle", icon: "radio_button_unchecked", tone: "text-gray-400" },
    running: { key: "running", icon: "progress_activity", tone: "text-gray-500" },
    passed: { key: "passed", icon: "check_circle", tone: "text-green-500" },
    warned: { key: "warned", icon: "warning", tone: "text-yellow-500" },
    failed: { key: "failed", icon: "error", tone: "text-red-500" },
    skipped: { key: "skipped", icon: "block", tone: "text-gray-400" },
  };

  var LINK = {
    down: { icon: "link_off", dot: "bg-gray-400", tone: "text-gray-400" },
    linking: { icon: "sync", dot: "bg-yellow-500", tone: "text-yellow-500" },
    up: { icon: "link", dot: "bg-green-500", tone: "text-green-500" },
    error: { icon: "error", dot: "bg-red-500", tone: "text-red-500" },
  };

  var SEVERITY = ["idle", "skipped", "passed", "warned", "failed"];

  function worst(list) {
    return list.reduce(function (acc, one) {
      return SEVERITY.indexOf(one) > SEVERITY.indexOf(acc) ? one : acc;
    }, "idle");
  }

  function hazardMark() {
    return el("span", {
      class: "inline-flex items-center gap-1 text-xs font-medium text-red-500",
    }, icon("warning", "size-4"), el("span", { text: (T.run || {}).hazardous }));
  }

  function outcomeMark(status, withLabel) {
    var spec = OUTCOME[status] || OUTCOME.idle;
    var label = (T.status || {})[spec.key] || spec.key;
    var node = el(
      "span",
      { class: "inline-flex items-center gap-1.5 text-xs " + spec.tone, title: label },
      icon(spec.icon, "size-[18px] " + (status === "running" ? "animate-spin" : ""))
    );
    if (withLabel) node.append(el("span", { text: label }));
    return node;
  }

  // ── Talking to the backend ─────────────────────────────────────────────────

  function api(path, body) {
    return fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(function (response) {
      if (!response.ok) {
        return response.json().then(
          function (payload) { throw new Error(payload.detail || response.statusText); },
          function () { throw new Error(response.statusText); }
        );
      }
      return response.json();
    });
  }

  // What a live list last answered, by the address it was asked at. A redraw
  // must not blank a list the screen has already been told, so the control
  // paints what is remembered and replaces it when the fresh answer lands.
  var known = {};

  function ask(at) {
    return api(at).then(function (list) {
      known[at] = list;
      return list;
    });
  }

  // ── What the screen is showing ─────────────────────────────────────────────

  var state = {
    subsystems: [],
    current: null,
    tool: "link",
    linkValues: {},
    linkBusy: false,
    linkError: null,
    linkReason: null,
    linkKnown: false,
    runs: {},
    call: null,
    callValues: {},
    callAnswer: null,
    callBusy: false,
    records: [],
    seen: 0,
    cleared: 0,
    logPaused: false,
    logFilter: "all",
    machine: { state: "idle", busy: null },
  };

  var dom = {};

  function current() { return state.current; }

  // What every route addresses a routine by, and what the payload calls it are
  // not the same: the address is scoped to its subsystem, the id is not.
  function keyOf(item) { return item.group + "." + item.name; }

  function routinesOf(category) {
    var sub = current();
    if (!sub || !sub.routines) return [];
    return sub.routines.filter(function (one) { return one.category === category; });
  }

  function linkRoutines() {
    return routinesOf("prelink").slice().sort(function (a, b) {
      if (a.name === "verify_port") return -1;
      if (b.name === "verify_port") return 1;
      return a.hazardous - b.hazardous;
    });
  }

  // The categories that already have a panel of their own. The Routines tab is
  // what is left over, so a category declared later appears there without this
  // file learning its name.
  var HOUSED = ["link", "prelink", "call"];

  function benchRoutines() {
    var sub = current();
    if (!sub || !sub.routines) return [];
    return sub.routines.filter(function (one) {
      return HOUSED.indexOf(one.category) === -1;
    });
  }

  function categoryGroups(list) {
    var order = [];
    var held = {};
    list.forEach(function (one) {
      if (!held[one.category]) { held[one.category] = []; order.push(one.category); }
      held[one.category].push(one);
    });
    return order.map(function (name) { return { name: name, routines: held[name] }; });
  }

  // A category with no legend is rendered under its own name rather than hidden,
  // since the alternative is a routine an operator cannot reach.
  function categoryLabel(name) {
    return (T.category || {})[name] || name;
  }

  function forgetLink() {
    state.linkValues = {};
    state.linkBusy = false;
    state.linkError = null;
    state.linkReason = null;
    state.linkKnown = false;
  }

  function connectRoutine() {
    return routinesOf("link").filter(function (one) {
      return one.name === "connect";
    })[0] || null;
  }

  function runFor(test) {
    var key = current().id + "." + keyOf(test);
    if (!state.runs[key]) {
      state.runs[key] = {
        status: "idle",
        when: null,
        open: false,
        values: JSON.parse(JSON.stringify(test.blank || {})),
        outcomes: [],
      };
    }
    return state.runs[key];
  }

  // ── The log ────────────────────────────────────────────────────────────────

  function lvlClass(level) {
    var tone =
      level === "ok" ? "text-green-500"
      : level === "warn" ? "text-yellow-500"
      : level === "error" ? "text-red-500"
      : "text-gray-500";
    return "text-xs font-semibold uppercase tracking-wide " + tone;
  }

  function appendRecord(record) {
    if (state.logFilter !== "all" && state.logFilter !== record.source) return;
    var empty = dom.logBody.querySelector(".log-empty");
    if (empty) empty.remove();
    dom.logBody.append(
      el(
        "div",
        { class: CLS.logRow },
        el("span", { class: "text-gray-500", text: clock(record.time) }),
        el("span", {
          class: "truncate text-gray-600 dark:text-gray-400",
          title: record.source,
          text: record.source,
        }),
        el("span", { class: lvlClass(record.level) + " truncate", title: record.kind, text: record.kind }),
        el("span", {
          class: "clamp-2 whitespace-pre-wrap break-words " + (
            record.level === "error" ? "text-red-500" : "text-gray-900 dark:text-white"),
          title: record.text,
          text: record.text,
        })
      )
    );
    dom.logBody.scrollTop = dom.logBody.scrollHeight;
  }

  /* EventSource reconnects on its own and is handed the backlog again, so a
   * record already seen has to be dropped rather than shown a second time.
   */
  function take(record) {
    if (record.seq <= state.seen) return false;
    state.seen = record.seq;
    if (record.seq <= state.cleared) return false;
    state.records.push(record);
    if (state.records.length > 500) state.records.shift();
    return true;
  }

  function shown() {
    return state.records.filter(function (record) {
      return state.logFilter === "all" || state.logFilter === record.source;
    });
  }

  function redrawLog() {
    clear(dom.logBody);
    if (!shown().length) {
      dom.logBody.append(
        el("div", { class: "log-empty px-4 py-2 text-xs text-gray-500", text: (T.log || {}).empty })
      );
    }
    state.records.forEach(appendRecord);
  }

  function renderLogChips() {
    clear(dom.logChips);
    var options = [{ id: "all", label: (T.log || {}).all }];
    state.subsystems.forEach(function (sub) {
      if (sub.available) options.push({ id: sub.id, label: sub.id });
    });
    options.forEach(function (option) {
      dom.logChips.append(
        el("button", {
          class: seg(state.logFilter === option.id),
          text: option.label,
          onclick: function () {
            state.logFilter = option.id;
            renderLogChips();
            redrawLog();
          },
        })
      );
    });
  }

  function toast(kind, title, detail) {
    var tone =
      kind === "error" ? "border-red-500 text-red-600"
      : kind === "warn" ? "border-yellow-500 text-yellow-600"
      : "border-green-500 text-green-600";
    var box = el(
      "div",
      { class: "flex items-start gap-3 w-80 p-3 bg-surface border-l-4 rounded-md shadow-lg " + tone, role: "status" },
      icon(kind === "error" ? "error" : kind === "warn" ? "warning" : "check_circle"),
      el(
        "div",
        { class: "min-w-0 flex-1" },
        el("div", { class: "text-sm font-semibold", text: title }),
        detail ? el("div", { class: "mt-0.5 font-mono text-xs text-gray-500 break-all", text: detail }) : null
      )
    );
    box.append(el("button", { class: CLS.btnQuiet, onclick: function () { box.remove(); } }, icon("close", "size-4")));
    dom.toasts.append(box);
    window.setTimeout(function () { box.remove(); }, 7000);
  }

  function arm(button, label, iconName, run) {
    var resting = button.dataset.resting || button.className;
    button.dataset.resting = resting;
    if (button.dataset.armed === "1") {
      window.clearTimeout(Number(button.dataset.timer));
      button.dataset.armed = "0";
      button.className = resting;
      clear(button).append(icon(iconName), el("span", { text: label }));
      run();
      return;
    }
    button.dataset.armed = "1";
    button.className = CLS.btnArmed;
    clear(button).append(icon("warning"), el("span", { text: (T.run || {}).confirm }));
    button.dataset.timer = String(
      window.setTimeout(function () {
        button.dataset.armed = "0";
        button.className = resting;
        clear(button).append(icon(iconName), el("span", { text: label }));
      }, 4000)
    );
  }

  function showMore(text, cls) {
    var box = el("div", {});
    var body = el("div", {
      class: (cls || "text-sm") + " clamp-3",
      title: text,
      text: text,
    });
    var toggle = el("button", {
      class: "mt-1 text-xs underline text-gray-500 hover:text-gray-900 dark:hover:text-white",
      text: (T.misc || {}).more,
      hidden: true,
      onclick: function () {
        var open = body.classList.toggle("is-open");
        toggle.textContent = open ? (T.misc || {}).less : (T.misc || {}).more;
      },
    });
    box.append(body, toggle);
    window.requestAnimationFrame(function () {
      if (body.scrollHeight - body.clientHeight > 2) toggle.hidden = false;
    });
    return box;
  }

  function kvTable(rows, heads) {
    // A reply is as wide as whatever it found. The table is free to outgrow the
    // column it sits in, and the box around it is what scrolls when it does.
    var table = el("table", { class: CLS.table });
    table.append(
      el("thead", {}, el("tr", {}, (heads || ["field", "value"]).map(function (h) {
        return el("th", { class: CLS.th, text: h });
      })))
    );
    var body = el("tbody");
    rows.forEach(function (row) {
      body.append(
        el("tr", {}, row.map(function (cell, index) {
          return el("td", {
            class: CLS.td + (index
              ? " font-mono tabular-nums text-gray-900 dark:text-white"
              : " text-gray-500 dark:text-gray-400"),
            text: String(cell),
          });
        }))
      );
    });
    table.append(body);
    return el("div", { class: "overflow-x-auto" }, table);
  }

  function resultRecord(answer) {
    var out = {};
    if (answer.summary) out.summary = answer.summary;
    if (answer.note) out.note = answer.note;
    if (answer.raw) out.raw = answer.raw;
    if (answer.fields && answer.fields.length) {
      out.fields = {};
      answer.fields.forEach(function (pair) { out.fields[pair[0]] = pair[1]; });
    }
    if (answer.table) {
      var head = answer.table.head || [];
      out.table = (answer.table.rows || []).map(function (row) {
        var record = {};
        row.forEach(function (cell, index) { record[head[index] || String(index)] = cell; });
        return record;
      });
    }
    return out;
  }

  function copyButton(payload) {
    var label = (T.misc || {}).copy;
    var button = el("button", { class: CLS.btnQuiet + " shrink-0", type: "button", title: label });
    function rest() {
      clear(button).append(icon("content_copy", "size-4"), el("span", { text: label }));
    }
    button.addEventListener("click", function () {
      var written = navigator.clipboard && navigator.clipboard.writeText
        ? navigator.clipboard.writeText(payload())
        : Promise.reject(new Error(""));
      written.then(
        function () {
          clear(button).append(icon("check_circle", "size-4"), el("span", { text: (T.misc || {}).copied }));
          window.setTimeout(rest, 1500);
        },
        function () { toast("error", (T.misc || {}).copy_failed); }
      );
    });
    rest();
    return button;
  }

  function renderResult(answer, copyable) {
    if (!answer) return null;
    var card = el("div", { class: CLS.card + " overflow-hidden" });
    card.append(
      el(
        "div",
        { class: "flex items-start gap-2 px-3 py-2 border-b border-gray-300 dark:border-gray-700" },
        el("div", { class: "min-w-0 flex-1" },
          el("div", { class: CLS.mono + " text-gray-900 dark:text-white", text: answer.summary }),
          answer.note ? el("div", { class: CLS.hint, text: answer.note }) : null),
        copyable ? copyButton(function () { return JSON.stringify(resultRecord(answer), null, 2); }) : null
      )
    );
    if (answer.raw) {
      card.append(
        el(
          "div",
          { class: "px-3 py-2 border-b border-gray-300 dark:border-gray-700" },
          el("div", {
            class: "max-h-24 overflow-auto font-mono text-xs tracking-widest text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-all",
            text: answer.raw,
          })
        )
      );
    }
    if (answer.fields && answer.fields.length) {
      card.append(el("div", { class: "p-3" }, kvTable(answer.fields)));
    }
    if (answer.table) {
      card.append(el("div", { class: "p-3" }, kvTable(answer.table.rows, answer.table.head)));
    }
    return card;
  }

  // ── Forms, one control per declared kind ───────────────────────────────────

  function fieldBox(spec, control) {
    return el(
      "div",
      { class: "flex flex-col" },
      el("label", {
        class: CLS.label,
        text: spec.name + (spec.unit ? " (" + spec.unit + ")" : ""),
      }),
      control,
      spec.hint ? el("div", { class: CLS.hint + " mt-1", text: spec.hint }) : null
    );
  }

  function choiceControl(spec, values, onChange) {
    var select = el("select", {
      class: CLS.input,
      onchange: function () {
        var picked = select.selectedOptions[0];
        values[spec.name] = picked && picked.dataset.numeric === "1"
          ? Number(select.value)
          : select.value;
        onChange();
      },
    });

    function fill(list) {
      clear(select);
      (list || []).forEach(function (option) {
        select.append(
          el("option", {
            value: option.value,
            "data-numeric": typeof option.value === "number" ? "1" : "0",
            selected: String(option.value) === String(values[spec.name]),
            text: option.label,
          })
        );
      });
      if (values[spec.name] == null && list && list.length) {
        values[spec.name] = list[0].value;
        select.value = String(list[0].value);
      }
    }

    // A fixed list crossed with the payload. One that can move crossed as an
    // address instead, and is asked for whenever this control is drawn.
    var box = fieldBox(spec, select);
    fill(spec.options || known[spec.reload]);
    if (spec.reload) {
      var row = el("div", { class: "flex items-center gap-2" });
      select.classList.add("flex-1");
      var refresh = el("button", {
        class: CLS.btnQuiet,
        title: (T.link || {}).refresh,
        onclick: function () {
          ask(spec.reload).then(fill);
        },
      }, icon("sync", "size-4"));
      box = fieldBox(spec, row);
      row.append(select, refresh);
      ask(spec.reload).then(fill);
    }
    return box;
  }

  function control(spec, values, onChange) {
    if (spec.kind === "choice") return choiceControl(spec, values, onChange);

    if (spec.kind === "boolean") {
      // Two buttons rather than one input, so which side is on is drawn here and
      // not by the browser. A form whose onChange redraws nothing still has to
      // show the side it now holds.
      var group = el("div", { class: CLS.segmented });
      var sides = [];
      [false, true].forEach(function (side) {
        var button = el("button", {
          type: "button",
          class: seg(Boolean(values[spec.name]) === side),
          text: side ? "True" : "False",
          onclick: function () {
            values[spec.name] = side;
            sides.forEach(function (one) { one.node.className = seg(one.side === side); });
            onChange();
          },
        });
        sides.push({ side: side, node: button });
        group.append(button);
      });
      return fieldBox(spec, group);
    }

    if (spec.kind === "integer") {
      var input = el("input", {
        class: CLS.input,
        type: "number",
        min: spec.min == null ? undefined : spec.min,
        max: spec.max == null ? undefined : spec.max,
        value: values[spec.name] == null ? 0 : values[spec.name],
        oninput: function () {
          var next = Number(input.value);
          if (spec.min != null && next < spec.min) next = spec.min;
          if (spec.max != null && next > spec.max) next = spec.max;
          values[spec.name] = next;
        },
      });
      var box = fieldBox(spec, input);
      if (spec.min != null || spec.max != null) {
        box.append(el("div", {
          class: CLS.hint + " mt-1",
          text: (T.call || {}).range + " " + (spec.min == null ? "" : spec.min) +" to "+ (spec.max == null ? "" : spec.max),
        }));
      }
      return box;
    }

    if (spec.kind === "bitmask") {
      var bits = el("div", {
        class: "flex flex-wrap items-center gap-x-3 gap-y-1 px-2.5 py-1.5 bg-surface border border-gray-400 rounded-md dark:border-gray-600",
      });
      var hexLabel = el("span", {
        class: "ml-auto font-mono text-xs text-gray-500",
        text: hex32(values[spec.name] || 0),
      });
      (spec.options || []).forEach(function (option) {
        var checkbox = el("input", {
          class: CLS.checkbox,
          type: "checkbox",
          checked: (Number(values[spec.name] || 0) & Number(option.value)) !== 0,
          onchange: function () {
            var next = Number(values[spec.name] || 0);
            values[spec.name] = checkbox.checked
              ? next | Number(option.value)
              : next & ~Number(option.value);
            hexLabel.textContent = hex32(values[spec.name]);
            onChange();
          },
        });
        bits.append(
          el("label", {
            class: "inline-flex items-center gap-1 text-xs text-gray-600 dark:text-gray-300 cursor-pointer",
          }, checkbox, option.label)
        );
      });
      bits.append(hexLabel);
      return fieldBox(spec, bits);
    }

    if (spec.kind === "raw_bytes") {
      var hexInput = el("input", {
        class: CLS.inputMono,
        value: values[spec.name] || "",
        spellcheck: "false",
        oninput: function () {
          values[spec.name] = hexInput.value;
          note.textContent = describeHex(hexInput.value);
        },
      });
      var note = el("div", { class: CLS.hint + " mt-1", text: describeHex(values[spec.name] || "") });
      var wrap = fieldBox(spec, hexInput);
      wrap.append(note);
      return wrap;
    }

    if (spec.kind === "group") return groupControl(spec, values, onChange);

    return fieldBox(spec, el("div", { class: CLS.hint, text: (T.misc || {}).unavailable }));
  }

  function describeHex(text) {
    var stripped = String(text || "").replace(/\s|^0x/gi, "");
    if (!stripped) return "0 " + (T.call || {}).bytes;
    if (!/^[0-9a-f]+$/i.test(stripped)) return (T.call || {}).invalid_hex;
    return Math.ceil(stripped.length / 2) + " " + (T.call || {}).bytes;
  }

  function groupControl(spec, values, onChange) {
    var rows = values[spec.name] || (values[spec.name] = []);
    var table = el("table", { class: CLS.table });
    table.append(
      el("thead", {}, el("tr", {},
        spec.columns.map(function (column) { return el("th", { class: CLS.th, text: column.name }); })
          .concat([el("th", { class: CLS.th })])
      ))
    );
    var tbody = el("tbody");
    table.append(tbody);

    // How many rows there are is this control's own business. Adding one redraws
    // the body here rather than waiting for a redraw of the form, which is a
    // redraw a form whose onChange does nothing never gets.
    function draw() {
      clear(tbody);
      rows.forEach(function (row, index) {
        var cells = spec.columns.map(function (column) {
          var cell = control(
            Object.assign({}, column, { hint: null, unit: null }),
            row,
            function () {}
          );
          var label = cell.querySelector("label");
          if (label) label.remove();
          return el("td", { class: CLS.td }, cell);
        });
        var remove = el("button", { class: CLS.btnQuiet, title: (T.call || {}).remove_row }, icon("close", "size-4"));
        remove.addEventListener("click", function () {
          rows.splice(index, 1);
          draw();
          onChange();
        });
        cells.push(el("td", { class: CLS.td }, remove));
        tbody.append(el("tr", {}, cells));
      });
    }
    draw();

    var wrapper = fieldBox(spec, el("div", { class: "overflow-x-auto" }, table));
    var add = el("button", { class: CLS.btn });
    add.append(icon("add"), el("span", { text: (T.call || {}).add_row }));
    add.addEventListener("click", function () {
      rows.push(blankRow(spec.columns));
      draw();
      onChange();
    });
    wrapper.append(el("div", { class: "flex gap-2 items-center mt-2" }, add));
    return wrapper;
  }

  function blankRow(columns) {
    var blank = {};
    columns.forEach(function (column) {
      var options = column.options || [];
      blank[column.name] =
        column.kind === "boolean" ? false
        : column.kind === "raw_bytes" ? ""
        : column.kind === "choice" ? (options.length ? options[0].value : null)
        : 0;
    });
    return blank;
  }

  function formGrid(params, values, onChange) {
    if (!params.length) return null;
    var grid = el("div", { class: "grid grid-cols-1 md:grid-cols-2 gap-3" });
    params.forEach(function (spec) { grid.append(control(spec, values, onChange)); });
    return grid;
  }

  // ── Link ───────────────────────────────────────────────────────────────────

  function renderLink(container) {
    var sub = current();
    var body = el("div", { class: CLS.cardBody });

    var opening = connectRoutine();
    if (opening && opening.inputs.length) {
      body.append(formGrid(opening.inputs, state.linkValues, function () { probe(); }));
    }

    if (state.linkReason) {
      body.append(el("div", { class: CLS.note, text: state.linkReason }));
    }
    if (state.linkError) {
      body.append(el("div", { class: CLS.noteError, text: state.linkError }));
    }

    var buttons = el("div", { class: "flex items-center gap-2" });
    if (sub.state === "up") {
      var off = el("button", { class: CLS.btn, onclick: disconnect });
      off.append(icon("link_off"), el("span", { text: (T.link || {}).disconnect }));
      buttons.append(off);
    } else {
      var waiting = state.linkBusy || !state.linkKnown;
      var on = el("button", {
        class: CLS.btnPrimary,
        disabled: waiting || Boolean(state.linkReason),
        onclick: connect,
      });
      on.append(
        icon(waiting ? "progress_activity" : "link", waiting ? "size-[18px] animate-spin" : "size-[18px]"),
        el("span", {
          text: state.linkBusy
            ? (T.link || {}).connecting
            : (!state.linkKnown ? (T.link || {}).checking : (T.link || {}).connect),
        })
      );
      buttons.append(on);
    }
    body.append(buttons);
    container.append(card((T.card || {}).connection, body));

    var routines = linkRoutines();
    if (routines.length) {
      container.append(sectionLabel((T.card || {}).before));
      var group = el("div", { class: "flex flex-col gap-2" });
      routines.forEach(function (test) { group.append(routineCard(test)); });
      container.append(group);
    }
  }

  function probe() {
    var sub = current();
    if (!connectRoutine() || sub.state === "up") {
      state.linkReason = null;
      state.linkKnown = true;
      return Promise.resolve();
    }
    state.linkKnown = false;
    renderMain();
    return api("/api/link/" + sub.id + "/readiness", state.linkValues).then(function (verdict) {
      if (!current() || current().id !== sub.id) return;
      state.linkReason = verdict.ok ? null : verdict.reason;
      state.linkKnown = true;
      renderMain();
    });
  }

  function connect() {
    var sub = current();
    state.linkBusy = true;
    state.linkError = null;
    renderMain();
    api("/api/link/" + sub.id + "/connect", state.linkValues)
      .then(function (answer) {
        if (current() && current().id === sub.id) {
          state.linkBusy = false;
          if (!answer.ok) state.linkError = answer.reason;
        }
        if (!answer.ok) toast("error", (T.link || {}).blocked, answer.reason);
        return refreshState();
      })
      .catch(function (error) {
        if (current() && current().id !== sub.id) return;
        state.linkBusy = false;
        state.linkError = error.message;
        renderMain();
      });
  }

  function disconnect() {
    var sub = current();
    api("/api/link/" + sub.id + "/disconnect", {}).then(function () {
      if (current() && current().id === sub.id) {
        state.linkReason = null;
        state.linkError = null;
        state.linkKnown = false;
      }
      refreshState();
    });
  }

  // ── Bench tests ────────────────────────────────────────────────────────────

  function renderRoutines(container) {
    var groups = categoryGroups(benchRoutines());

    if (!groups.length) {
      container.append(card(null, el("div", { class: CLS.cardBody },
        el("div", { class: CLS.hint, text: (T.run || {}).none }))));
      return;
    }

    groups.forEach(function (one) {
      container.append(
        sectionLabel(
          categoryLabel(one.name),
          outcomeMark(worst(one.routines.map(function (test) { return runFor(test).status; })), true)
        )
      );
      var stack = el("div", { class: "flex flex-col gap-2" });
      one.routines.forEach(function (test) { stack.append(routineCard(test)); });
      container.append(stack);
    });
  }

  function sectionLabel(title, aside) {
    return el("div", { class: "flex items-center gap-3 px-1" },
      el("span", {
        class: "text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400",
        text: title,
      }),
      el("span", { class: CLS.spacer }),
      aside || null);
  }

  function routineCard(test) {
    var entry = runFor(test);
    // The subsystem answered this when the payload was built, reason and all,
    // so the screen shows its sentence rather than guessing one from the state.
    var gated = !test.ready.ok;
    var why = test.ready.reason || (T.run || {}).needs_link;
    var row = el("div", { class: CLS.card });

    var caret = el("span", {
      class: "shrink-0 text-gray-500 transition-transform" + (entry.open ? " rotate-90" : ""),
      text: "▸",
    });
    var body = el("div", {
      class: "px-4 pb-4 flex flex-col gap-3" + (entry.open ? "" : " hidden"),
    });

    var title = el(
      "button",
      {
        class: "flex items-center gap-2 min-w-0 text-left font-semibold text-gray-900 dark:text-white",
        onclick: function () {
          entry.open = !entry.open;
          body.classList.toggle("hidden");
          caret.classList.toggle("rotate-90");
          head.className = headClass(entry.open);
        },
      },
      caret,
      el("span", { class: "truncate", title: test.title, text: test.title }),
      test.hazardous ? hazardMark() : null
    );

    var runButton = el("button", {
      class: test.hazardous ? CLS.btnDanger : CLS.btn,
      disabled: gated || entry.status === "running",
      title: gated ? why : "",
    });
    var label = entry.status === "running"
      ? (T.run || {}).running
      : entry.outcomes.length ? (T.run || {}).rerun : (T.run || {}).run;
    runButton.append(icon("play_arrow"), el("span", { text: label }));
    runButton.addEventListener("click", function () {
      if (test.hazardous) arm(runButton, label, "play_arrow", function () { runTest(test); });
      else runTest(test);
    });

    var head = el("div", { class: headClass(entry.open) },
      title,
      outcomeMark(entry.status, true),
      el("span", { class: "font-mono text-xs text-gray-500", text: entry.when || "" }),
      runButton
    );
    row.append(head);

    if (test.description) {
      body.append(
        el("div", { class: "pt-3 text-sm text-gray-600 dark:text-gray-300" },
          showMore(test.description, "text-sm text-gray-600 dark:text-gray-300"))
      );
    }

    var form = formGrid(test.inputs, entry.values, function () {});
    if (form) body.append(form);

    body.append(stepList(test, entry));
    row.append(body);
    return row;
  }

  function headClass(open) {
    return "check-grid px-4 py-2.5" + (
      open ? " border-b border-gray-300 dark:border-gray-700" : "");
  }

  function runRecord(test, entry) {
    var titles = test.steps.length ? test.steps : entry.outcomes.map(function (_, index) {
      return "#" + (index + 1);
    });
    return JSON.stringify({
      subsystem: current().id,
      routine: keyOf(test),
      title: test.title,
      status: entry.status,
      when: entry.when || null,
      inputs: entry.values,
      steps: entry.outcomes.map(function (settled, index) {
        var step = { step: titles[index] || "#" + (index + 1), status: settled.status };
        if (settled.detail) step.detail = settled.detail;
        if (settled.value) step.result = resultRecord(settled.value);
        return step;
      }),
    }, null, 2);
  }

  function stepList(test, entry) {
    var card = el("div", { class: CLS.card + " overflow-hidden" });
    card.append(
      el("div", {
        class: "flex items-center gap-2 px-3 py-1.5 bg-inset border-b border-gray-300 dark:border-gray-700",
      },
        el("div", {
          class: "flex-1 text-xs font-semibold uppercase tracking-wider text-gray-500",
          text: (T.run || {}).steps,
        }),
        entry.outcomes.length
          ? copyButton(function () { return runRecord(test, entry); })
          : null
      )
    );

    var declared = test.steps.length
      ? test.steps.map(function (title, index) {
          return { title: title, settled: entry.outcomes[index] || null };
        })
      : entry.outcomes.map(function (settled, index) {
          return { title: "#" + (index + 1), settled: settled };
        });

    if (!declared.length) {
      card.append(el("div", { class: "px-3 py-2 " + CLS.hint, text: "" }));
      return card;
    }

    var reached = declared.filter(function (step) { return step.settled; }).length;
    declared.forEach(function (step, index) {
      var settled = step.settled;
      var status = settled
        ? settled.status
        : entry.status === "running" && index === reached
          ? "running"
          : "idle";
      var detail = settled && settled.detail
        ? el("div", {
            class: "mt-0.5 font-mono text-xs " + (
              settled.status === "failed" ? "text-red-500"
              : settled.status === "warned" ? "text-yellow-600 dark:text-yellow-400"
              : "text-gray-500"),
            text: settled.detail,
          })
        : null;
      var value = settled && settled.value ? renderResult(settled.value, false) : null;
      card.append(
        el("div", { class: "step-grid px-3 py-2 border-t border-gray-300 first:border-t-0 dark:border-gray-700" },
          el("div", { class: "min-w-0" },
            el("div", { class: "truncate text-sm text-gray-900 dark:text-white", text: step.title }),
            detail,
            value ? el("div", { class: "mt-2" }, value) : null),
          outcomeMark(status, false)
        )
      );
    });
    return card;
  }

  function runTest(test) {
    var sub = current();
    var entry = runFor(test);
    entry.status = "running";
    entry.open = true;
    entry.outcomes = [];
    entry.when = clock(Date.now() / 1000);
    renderMain();

    streamPost("/api/run/" + sub.id + "/" + keyOf(test), entry.values, function (event, payload) {
      if (event === "outcome") {
        if (payload.error) {
          entry.outcomes.push({ status: "failed", detail: payload.error, value: null });
        } else {
          entry.outcomes.push(payload);
        }
        entry.status = "running";
        renderMain();
      } else if (event === "refused") {
        entry.status = "idle";
        toast("warn", (T.misc || {}).busy, payload.reason);
        renderMain();
      } else if (event === "done") {
        entry.status = worst(entry.outcomes.map(function (one) { return one.status; }));
        if (entry.status === "idle") entry.status = "passed";
        renderMain();
        refreshState();
      }
    }).catch(function (error) {
      entry.status = "failed";
      entry.outcomes.push({ status: "failed", detail: error.message, value: null });
      renderMain();
    });
  }

  function streamPost(path, body, onEvent) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (response) {
      if (!response.ok) throw new Error(response.statusText);
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";

      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) return;
          buffer += decoder.decode(chunk.value, { stream: true });
          var blocks = buffer.split("\n\n");
          buffer = blocks.pop();
          blocks.forEach(function (block) {
            var event = "message";
            var data = "";
            block.split("\n").forEach(function (line) {
              if (line.indexOf("event:") === 0) event = line.slice(6).trim();
              else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
            });
            if (data) onEvent(event, JSON.parse(data));
          });
          return pump();
        });
      }
      return pump();
    });
  }

  // ── Actions ────────────────────────────────────────────────────────────────

  function namespaceGroups(calls) {
    var order = [];
    var methods = {};
    calls.forEach(function (item) {
      if (!methods[item.group]) { methods[item.group] = []; order.push(item.group); }
      methods[item.group].push(item);
    });
    return order.map(function (ns) { return { name: ns, methods: methods[ns] }; });
  }

  function renderCalls(container) {
    var calls = routinesOf("call");
    if (!calls.length) {
      container.append(card((T.tool || {}).calls, el("div", { class: CLS.cardBody },
        el("div", { class: CLS.hint, text: (T.call || {}).none }))));
      return;
    }

    // A refresh replaces every declaration, so the pick is held by address.
    // Re-reading it rather than re-adopting is what keeps a half-filled form filled.
    var groups = namespaceGroups(calls);
    var live = state.call && calls.filter(function (one) {
      return keyOf(one) === keyOf(state.call);
    })[0];
    if (live) state.call = live;
    else adoptCall(groups[0].methods[0]);

    container.append(card((T.tool || {}).calls, picker(groups)));
    container.append(methodCard(state.call));
  }

  function picker(groups) {
    var chosen = state.call.group;
    var group = groups.filter(function (one) { return one.name === chosen; })[0];

    var namespace = pickerBox(
      (T.call || {}).namespace,
      groups.map(function (one) {
        return { value: one.name, label: one.name + " (" + one.methods.length + ")" };
      }),
      chosen,
      function (picked) {
        var next = groups.filter(function (one) { return one.name === picked; })[0];
        selectCall(next.methods[0]);
      }
    );

    var method = pickerBox(
      (T.call || {}).method,
      group.methods.map(function (one) {
        return { value: keyOf(one), label: one.name };
      }),
      keyOf(state.call),
      function (picked) {
        selectCall(group.methods.filter(function (one) {
          return keyOf(one) === picked;
        })[0]);
      }
    );

    return el("div", { class: "flex flex-wrap items-start gap-4 p-4" }, namespace, method);
  }

  function pickerBox(label, entries, chosen, onPick) {
    var select = el("select", {
      class: CLS.input + " font-mono",
      onchange: function () { onPick(select.value); },
    });
    entries.forEach(function (entry) {
      select.append(el("option", {
        value: entry.value,
        selected: entry.value === chosen,
        text: entry.label,
      }));
    });
    return el("div", { class: "flex flex-col min-w-56 flex-1" },
      el("label", { class: CLS.label, text: label }),
      select);
  }

  function methodCard(item) {
    var body = el("div", { class: "flex flex-col gap-4 p-4" });

    if (item.title) body.append(el("div", { class: CLS.lede, text: item.title }));
    if (item.description) {
      body.append(showMore(item.description, "text-sm text-gray-600 dark:text-gray-300"));
    }

    var form = formGrid(item.inputs, state.callValues, function () {});
    body.append(
      el("hr", { class: CLS.divider }),
      el("div", {},
        el("div", { class: CLS.label, text: (T.call || {}).arguments }),
        form || el("div", { class: CLS.hint, text: (T.call || {}).no_arguments })),
      el("hr", { class: CLS.divider }),
      buttonRow(item)
    );

    if (state.callAnswer) {
      var answer = state.callAnswer;
      body.append(
        el("hr", { class: CLS.divider }),
        el("div", {},
          el("div", { class: CLS.label, text: (T.call || {}).reply }),
          answer.ok
            ? renderResult(answer.value, true) || el("div", { class: CLS.note, text: "" })
            : el("div", { class: CLS.noteError, text: answer.reason }))
      );
    }

    // A namespace is never hazardous, only a method is, so the marker sits in
    // the header of the card that names the method.
    return card(item.id, body, item.hazardous ? hazardMark() : null);
  }

  function buttonRow(item) {
    var gated = !item.ready.ok;
    var why = item.ready.reason || (T.call || {}).blocked;
    var run = el("button", {
      class: item.hazardous ? CLS.btnDanger : CLS.btnPrimary,
      disabled: gated || state.callBusy,
      title: gated ? why : "",
    });
    var label = (T.call || {}).run;
    run.append(
      icon(state.callBusy ? "progress_activity" : "play_arrow",
        state.callBusy ? "size-[18px] animate-spin" : "size-[18px]"),
      el("span", { text: label })
    );
    run.addEventListener("click", function () {
      if (item.hazardous) arm(run, label, "play_arrow", function () { runCall(item); });
      else runCall(item);
    });

    return el("div", { class: "flex items-center gap-2" }, run);
  }

  function adoptCall(item) {
    state.call = item;
    state.callValues = JSON.parse(JSON.stringify(item.blank || {}));
    state.callAnswer = null;
  }

  function selectCall(item) {
    adoptCall(item);
    renderMain();
  }

  function runCall(item) {
    var sub = current();
    state.callBusy = true;
    renderMain();
    api("/api/call/" + sub.id + "/" + keyOf(item), state.callValues)
      .then(function (answer) {
        state.callBusy = false;
        state.callAnswer = answer;
        renderMain();
      })
      .catch(function (error) {
        state.callBusy = false;
        state.callAnswer = { ok: false, reason: error.message, value: null };
        renderMain();
      });
  }

  // ── The screen ─────────────────────────────────────────────────────────────

  function card(title, body, aside) {
    var node = el("div", { class: CLS.card });
    if (title) {
      node.append(
        el("div", { class: CLS.cardHead },
          el("span", {
            class: "text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400",
            text: title,
          }),
          el("span", { class: CLS.spacer }),
          aside || null)
      );
    }
    node.append(body);
    return node;
  }

  function subsystemTabs() {
    var bar = el("div", { class: CLS.tabbar });
    state.subsystems.forEach(function (sub) {
      var label = (T.subsystem || {})[sub.id] || sub.id;
      bar.append(
        el("button", {
          class: tabClass(state.current && state.current.id === sub.id),
          disabled: !sub.available,
          title: sub.available ? "" : (T.card || {}).unavailable,
          onclick: function () {
            if (state.current && state.current.id === sub.id) return;
            state.current = sub;
            state.tool = "link";
            state.call = null;
            state.callAnswer = null;
            forgetLink();
            renderMain();
            probe();
          },
        }, el("span", { text: label }))
      );
    });
    return bar;
  }

  function implementationCard(sub) {
    var spec = LINK[sub.state] || LINK.down;
    var body = el("div", { class: "flex flex-col gap-2 p-4" },
      el("span", { class: CLS.lede, text: sub.summary }),
      sub.description
        ? showMore(sub.description, "text-sm text-gray-600 dark:text-gray-300")
        : null);

    var state_ = el("span", { class: "inline-flex items-center gap-2 text-xs " + spec.tone },
      el("span", { class: "w-1.5 h-1.5 rounded-full " + spec.dot }),
      el("span", { text: (T.link || {}).state[sub.state] || sub.state }));

    return card((T.card || {}).implementation, body, state_);
  }

  function toolTabs(up) {
    var bar = el("div", { class: CLS.tabbar });
    [
      { id: "link", label: (T.tool || {}).link, icon: "link", gated: false },
      { id: "routines", label: (T.tool || {}).routines, icon: "vital_signs", gated: !up },
      { id: "calls", label: (T.tool || {}).calls, icon: "data_object", gated: !up },
    ].forEach(function (tab) {
      bar.append(
        el("button", {
          class: tabClass(state.tool === tab.id),
          disabled: tab.gated,
          title: tab.gated ? (T.run || {}).needs_link : "",
          onclick: function () { state.tool = tab.id; renderMain(); },
        }, icon(tab.icon, "size-4"), el("span", { text: tab.label }))
      );
    });
    return bar;
  }

  function renderMain() {
    var sub = current();
    clear(dom.main);
    dom.main.append(subsystemTabs());

    if (!sub || !sub.available) {
      dom.main.append(card(null, el("div", { class: CLS.cardBody },
        el("div", { class: CLS.hint, text: (T.card || {}).unavailable }))));
      return;
    }

    var up = sub.state === "up";
    if (!up) state.tool = "link";

    dom.main.append(implementationCard(sub), toolTabs(up));

    if (state.tool === "link") {
      renderLink(dom.main);
    } else if (state.tool === "routines") {
      renderRoutines(dom.main);
    } else {
      renderCalls(dom.main);
    }
  }

  function refreshState() {
    return api("/api/state").then(function (machine) {
      state.machine = machine;
      return api("/api/subsystems");
    }).then(function (list) {
      var byId = {};
      list.forEach(function (one) { byId[one.id] = one; });
      var reachable = list.filter(function (one) { return one.available; });
      var was = state.current ? state.current.id : null;
      state.subsystems = list;
      state.current =
        (state.current && byId[state.current.id] && byId[state.current.id].available
          ? byId[state.current.id]
          : reachable[0]) || null;
      if ((state.current ? state.current.id : null) !== was) forgetLink();
      renderMain();
      return state.current ? probe() : null;
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────────────

  function applyTheme(choice) {
    document.documentElement.classList.toggle("dark", choice === "dark");
    try { localStorage.setItem("stef.theme", choice); } catch (e) {}
    document.querySelectorAll("#theme button").forEach(function (button) {
      button.className = seg(button.dataset.theme === choice);
    });
  }

  function currentTheme() {
    return document.documentElement.classList.contains("dark") ? "dark" : "light";
  }

  function listen() {
    var source = new EventSource("/api/events");
    source.addEventListener("record", function (message) {
      if (take(JSON.parse(message.data)) && !state.logPaused) {
        appendRecord(state.records[state.records.length - 1]);
      }
    });
    source.onerror = function () { /* EventSource reconnects on its own. */ };
  }

  document.addEventListener("DOMContentLoaded", function () {
    dom.main = document.querySelector("main");
    dom.logBody = document.querySelector(".log-body");
    dom.logChips = document.querySelector(".log-chips");
    dom.toasts = document.querySelector(".toasts");

    document.querySelectorAll("[data-icon]").forEach(function (node) {
      node.prepend(icon(node.dataset.icon, "size-5"));
    });
    document.querySelectorAll("#theme button").forEach(function (button) {
      button.addEventListener("click", function () { applyTheme(button.dataset.theme); });
    });
    applyTheme(currentTheme());

    var pause = document.querySelector(".log-pause");
    pause.addEventListener("click", function () {
      state.logPaused = !state.logPaused;
      pause.textContent = state.logPaused ? (T.log || {}).resume : (T.log || {}).pause;
      if (!state.logPaused) redrawLog();
    });
    document.querySelector(".log-clear").addEventListener("click", function () {
      state.cleared = state.seen;
      state.records = [];
      redrawLog();
    });
    document.querySelector(".log-export").addEventListener("click", function () {
      var text = state.records.map(function (record) {
        return [clock(record.time), record.source, record.level, record.kind, record.text].join("\t");
      }).join("\n");
      var url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
      var anchor = el("a", { href: url, download: "stef-log.txt" });
      anchor.click();
      URL.revokeObjectURL(url);
    });

    redrawLog();
    listen();
    refreshState().then(renderLogChips).catch(function (error) {
      dom.main.append(el("div", { class: CLS.noteError, text: error.message }));
    });
  });
})();
