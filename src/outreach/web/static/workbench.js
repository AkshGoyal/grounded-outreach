"use strict";

(() => {
  const errors = document.querySelector("[data-form-errors]");
  if (errors) errors.focus();

  const form = document.querySelector("[data-prospect-form]");
  if (form) {
    const initiallyDisabled = form.querySelector("button[type=submit]").disabled;
    form.addEventListener("submit", event => {
      const button = form.querySelector("button[type=submit]");
      if (button.disabled) {
        event.preventDefault();
        return;
      }
      button.disabled = true;
      button.textContent = "Starting research…";
      form.setAttribute("aria-busy", "true");
    });
    window.addEventListener("pageshow", () => {
      const button = form.querySelector("button[type=submit]");
      button.disabled = initiallyDisabled;
      button.textContent = "Start research";
      form.removeAttribute("aria-busy");
    });
  }

  const configElement = document.getElementById("run-poll-config");
  if (!configElement) return;
  const config = JSON.parse(configElement.textContent);
  if (!["queued", "running"].includes(config.execution_status)) return;
  const message = document.querySelector("[data-poll-status]");
  let stopped = false;

  async function poll() {
    if (stopped) return;
    try {
      const response = await fetch(config.url, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok || response.redirected) throw new Error("Status unavailable");
      const saved = await response.json();
      if (
        saved.execution_status !== config.execution_status ||
        saved.updated_at !== config.updated_at ||
        (saved.stages || []).length !== config.stage_count
      ) {
        stopped = true;
        window.location.reload();
        return;
      }
      message.textContent = "This page updates by itself. Refreshing is safe.";
      delete message.dataset.disconnected;
    } catch (_) {
      message.textContent = "Lost contact with the server. Saved results stay here; trying again.";
      message.dataset.disconnected = "true";
    }
    window.setTimeout(poll, document.hidden ? 4000 : 1200);
  }

  window.setTimeout(poll, 500);
})();

// Draft review: unchecked edits cannot be approved, and copy uses the server's approved text.
(() => {
  const form = document.querySelector("[data-draft-form]");
  if (form) {
    const fields = [form.elements.subject, form.elements.body];
    const saved = fields.map(field => field.defaultValue);
    const approve = document.querySelector("[data-approve-form] button[type=submit]");
    const initiallyDisabled = approve ? approve.disabled : true;
    const status = form.querySelector("[data-edit-status]");
    const update = () => {
      const changed = fields.some((field, index) => field.value !== saved[index]);
      if (approve) approve.disabled = changed || initiallyDisabled;
      status.textContent = changed ? "Edits not checked yet. Check edits before approving." : "";
    };
    fields.forEach(field => field.addEventListener("input", update));
    form.addEventListener("submit", () => {
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      button.textContent = "Checking edits…";
    });
  }

  const copy = document.querySelector("[data-copy-approved]");
  if (!copy) return;
  const message = document.querySelector("[data-copy-status]");
  copy.addEventListener("click", async () => {
    try {
      const response = await fetch(copy.dataset.exportUrl, { cache: "no-store" });
      const text = await response.text();
      if (!response.ok) throw new Error(text);
      await navigator.clipboard.writeText(text);
      message.textContent = "Approved draft copied. Nothing was sent.";
    } catch (error) {
      const block = document.querySelector("[data-export-copy]");
      const range = document.createRange();
      range.selectNodeContents(block);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      message.textContent = error && error.message && !/clipboard|permission|denied/i.test(error.message)
        ? error.message
        : "Copy was blocked by the browser. The approved text is selected; press Ctrl+C or ⌘C.";
    }
  });
})();

// Source-to-draft comparison: pointing at a sentence's citation marks the source it relies on.
(() => {
  const links = document.querySelectorAll("a.support-id[href^='#source-']");
  links.forEach(link => {
    const source = document.getElementById(link.getAttribute("href").slice(1));
    if (!source) return;
    const on = () => source.classList.add("is-cited");
    const off = () => source.classList.remove("is-cited");
    link.addEventListener("mouseenter", on);
    link.addEventListener("mouseleave", off);
    link.addEventListener("focus", on);
    link.addEventListener("blur", off);
    link.addEventListener("click", () => window.setTimeout(() => source.focus({ preventScroll: true }), 0));
  });
})();

// "Write the draft" runs in the request: show progress and prevent a second paid click.
(() => {
  const form = document.querySelector("[data-write-draft]");
  if (!form) return;
  form.addEventListener("submit", () => {
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = "Writing the draft…";
    const hint = form.querySelector("[data-write-hint]");
    if (hint) hint.textContent = "Writing and checking every sentence. This can take up to 30 seconds.";
  });
})();

// Drafting needs the goal: turning the goal off turns drafting off, and explains why.
(() => {
  const goal = document.querySelector("[data-use-goal]");
  const draft = document.querySelector("[data-write-draft-option]");
  if (!goal || !draft) return;
  const sync = () => {
    draft.disabled = !goal.checked;
    if (!goal.checked) draft.checked = false;
    draft.closest(".option").classList.toggle("is-disabled", !goal.checked);
  };
  goal.addEventListener("change", sync);
  sync();
})();

// Live run view: a running clock between page refreshes.
(() => {
  const clock = document.querySelector("[data-elapsed]");
  if (!clock) return;
  const start = Date.parse(clock.dataset.start);
  if (Number.isNaN(start)) return;
  const tick = () => {
    const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
    clock.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  };
  tick();
  window.setInterval(tick, 1000);
})();

// Edit a sentence where it stands: click it, change or remove it, and it is checked again.
(() => {
  const editor = document.querySelector("[data-sentence-editor]");
  if (!editor) return;
  const box = editor.elements.replacement;
  const why = editor.querySelector("[data-sentence-why]");
  const remove = editor.querySelector("[data-sentence-remove]");
  let current = null;
  const close = () => {
    if (current) current.classList.remove("is-editing");
    current = null;
    editor.hidden = true;
  };
  const open = sentence => {
    if (current === sentence) return close();
    close();
    current = sentence;
    sentence.classList.add("is-editing");
    const text = sentence.textContent.trim();
    editor.elements.replace.value = text;
    box.value = text;
    why.textContent = sentence.dataset.why || "";
    const inSubject = Boolean(sentence.closest(".letter-subject"));
    remove.hidden = inSubject;
    // Sits right under the sentence (after its source numbers), or under the subject line.
    let anchor = inSubject ? sentence.closest(".letter-subject") : sentence;
    while (!inSubject && anchor.nextElementSibling && anchor.nextElementSibling.matches("a.ref")) {
      anchor = anchor.nextElementSibling;
    }
    anchor.after(editor);
    editor.hidden = false;
    box.focus();
    box.setSelectionRange(text.length, text.length);
  };
  document.querySelectorAll("[data-sentence]").forEach(sentence => {
    sentence.addEventListener("click", () => open(sentence));
    sentence.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open(sentence);
      }
    });
  });
  editor.querySelector("[data-sentence-cancel]").addEventListener("click", close);
  editor.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      const back = current;
      close();
      if (back) back.focus();
    }
  });
})();

// Folded sections open when something inside them is linked to (a source number, a tag).
(() => {
  const reveal = hash => {
    if (!hash || hash.length < 2) return;
    const target = document.getElementById(decodeURIComponent(hash.slice(1)));
    if (!target) return;
    const panel = target.closest("[data-tab-panel]");
    if (panel && window.workbenchShowTab) window.workbenchShowTab(panel.dataset.tabPanel);
    let opened = Boolean(panel);
    for (let node = target.parentElement; node; node = node.parentElement) {
      if (node.tagName === "DETAILS" && !node.open) {
        node.open = true;
        opened = true;
      }
    }
    if (opened) target.scrollIntoView({ block: "center" });
  };
  window.addEventListener("hashchange", () => reveal(window.location.hash));
  document.addEventListener("click", event => {
    const link = event.target.closest("a[href^='#']");
    if (link) reveal(link.getAttribute("href"));
  });
  reveal(window.location.hash);
})();

// Start page: the goal shows only when the choice uses it, and the cost line always
// matches what is chosen (and, for a list, how many prospects are in it).
(() => {
  const choices = document.querySelector("[data-purpose]");
  if (!choices) return;
  const form = choices.closest("form");
  const pitch = form.querySelector("[data-pitch]");
  const line = form.querySelector("[data-cost-line]");
  const costs = line ? JSON.parse(line.dataset.costs) : null;
  const list = form.querySelector("[data-batch-list]");
  const money = value => "$" + value.toFixed(value < 1 ? 3 : 2);
  const update = () => {
    const picked = form.querySelector("input[name=purpose]:checked");
    const purpose = picked ? picked.value : "email";
    if (pitch) pitch.hidden = purpose === "none";
    if (!line) return;
    const chosenDepth = form.querySelector("input[name=depth]:checked");
    const depth = chosenDepth ? chosenDepth.value : "thorough";
    const each = costs[depth] + (purpose === "email" ? costs.email : 0);
    const what = purpose === "email" ? "research and the email" : "research only";
    const total = line.querySelector("[data-cost-total]");
    const detail = line.querySelector("[data-cost-detail]");
    if (line.dataset.many === "1") {
      const count = list ? list.value.split("\n").filter(row => row.trim()).length : 0;
      total.textContent = "About " + money(each) + " each";
      detail.textContent = count
        ? "for " + what + "; about " + money(each * count) + " for " + count + " prospect" + (count === 1 ? "" : "s") + "."
        : "for " + what + ".";
    } else {
      total.textContent = "About " + money(each);
      detail.textContent = "for " + what + ".";
    }
  };
  form.addEventListener("change", update);
  if (list) list.addEventListener("input", update);
  update();
})();

// Feedback for every wait: a thin bar at the top whenever a page is loading, and a
// spinner on the button that was pressed, so a click never looks ignored.
(() => {
  const bar = document.querySelector("[data-nav-progress]");
  const start = () => {
    if (bar) bar.classList.add("is-loading");
  };
  const stop = () => {
    if (bar) bar.classList.remove("is-loading");
    document.querySelectorAll(".is-busy").forEach(button => {
      button.classList.remove("is-busy");
      button.removeAttribute("aria-busy");
      if (button.dataset.idleLabel) button.textContent = button.dataset.idleLabel;
    });
  };
  document.addEventListener("click", event => {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target === "_blank" || link.hasAttribute("download")) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    if (url.pathname === window.location.pathname && url.search === window.location.search) return;
    if (/\/export\b/.test(url.pathname)) return;
    start();
  });
  document.addEventListener("submit", event => {
    if (event.defaultPrevented) return;
    const button = event.submitter || event.target.querySelector("button[type=submit]");
    start();
    if (!button || button.classList.contains("link-button")) return;
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    if (button.dataset.busyLabel) {
      button.dataset.idleLabel = button.textContent;
      button.textContent = button.dataset.busyLabel;
    }
  });
  window.addEventListener("pageshow", stop);
})();

// Sign-in: show or hide the password, and explain a slow first load.
(() => {
  const form = document.querySelector("[data-login-form]");
  if (!form) return;
  const input = form.querySelector("input[name=password]");
  const toggle = form.querySelector("[data-show-password]");
  toggle.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    toggle.textContent = show ? "Hide" : "Show";
    toggle.setAttribute("aria-pressed", String(show));
    input.focus();
  });
  const wait = form.querySelector("[data-login-wait]");
  form.addEventListener("submit", () => {
    input.type = "password";
    window.setTimeout(() => {
      if (wait) wait.hidden = false;
    }, 2500);
  });
})();

// Evidence beside the email, one tab at a time: why this hook, what we found, sources.
// A source number in the email opens the Sources tab at that source.
(() => {
  const rail = document.querySelector("[data-rail]");
  if (!rail) return;
  const tabs = [...rail.querySelectorAll("[data-tab]")];
  const panels = [...rail.querySelectorAll("[data-tab-panel]")];
  const show = name => {
    if (!tabs.some(tab => tab.dataset.tab === name)) return;
    tabs.forEach(tab => {
      const active = tab.dataset.tab === name;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    panels.forEach(panel => {
      panel.hidden = panel.dataset.tabPanel !== name;
    });
  };
  window.workbenchShowTab = show;
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => show(tab.dataset.tab));
    tab.addEventListener("keydown", event => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!step) return;
      const next = tabs[(index + step + tabs.length) % tabs.length];
      next.focus();
      show(next.dataset.tab);
    });
  });
  rail.classList.add("is-tabbed");
  show("hook");
})();
