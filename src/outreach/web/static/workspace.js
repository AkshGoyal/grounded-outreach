// Protect exact copy in the same campaign instruction editor; saving still uses the form.
document.querySelectorAll('[data-keep-selection]').forEach(button => {
  button.addEventListener('click', () => {
    const form = button.closest('form');
    const editor = form.querySelector('[data-message-editor]');
    const start = editor.selectionStart, end = editor.selectionEnd;
    const selected = editor.value.slice(start, end);
    const prefix = start > 0 && editor.value[start - 1] !== '\n' ? '\n' : '';
    const suffix = end < editor.value.length && editor.value[end] !== '\n' ? '\n' : '';
    const wrapped = prefix + '[KEEP]\n' + selected + '\n[/KEEP]' + suffix;
    const status = form.querySelector('[data-keep-status]');
    if (editor.value.length - selected.length + wrapped.length > editor.maxLength) {
      status.textContent = 'Shorten the instructions before adding a protected block.';
      return;
    }
    editor.setRangeText(wrapped, start, end, 'end');
    editor.focus();
    if (!selected) editor.setSelectionRange(start + prefix.length + 7, start + prefix.length + 7);
    editor.dispatchEvent(new Event('input', {bubbles: true}));
    status.textContent = selected ? 'Selected wording is protected. Save your instructions.' : 'Write the exact wording between the markers, then save.';
  });
});

document.querySelectorAll('[data-select-all]').forEach(control => {
  control.addEventListener('change', () => control.closest('form').querySelectorAll('[name="lead_ids"]:not(:disabled)').forEach(box => {box.checked = control.checked;}));
});
document.querySelectorAll('[data-dictate]').forEach(button => {
  button.addEventListener('click', () => {
    const status = document.getElementById('voice-status');
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {status.textContent = 'Voice input is unavailable in this browser. You can type your brief.'; return;}
    if (button.dataset.listening === '1') return;
    const target = document.getElementById(button.dataset.dictate);
    const recognition = new Recognition();
    recognition.lang = navigator.language || 'en-IN';
    recognition.interimResults = false;
    recognition.onresult = event => {target.value += (target.value ? ' ' : '') + event.results[0][0].transcript; target.dispatchEvent(new Event('input', {bubbles:true}));};
    recognition.onerror = () => {status.textContent = 'Voice input stopped. Check microphone permission or type your brief.';};
    recognition.onend = () => {button.dataset.listening = '0'; button.textContent = 'Use voice';};
    try {recognition.start(); button.dataset.listening = '1'; button.textContent = 'Listening…'; status.textContent = 'Your browser handles voice transcription. Speak your audience brief.';} catch {status.textContent = 'Voice input could not start.';}
  });
});
// Keep table position and filters when opening evidence and coming back.
const scrollKey = 'outreach-position:' + location.pathname + location.search;
if (performance.getEntriesByType('navigation')[0]?.type === 'back_forward') {
  try {window.scrollTo(0, Number(sessionStorage.getItem(scrollKey) || 0));} catch { /* Optional browser storage. */ }
}
window.addEventListener('pagehide', () => {try {sessionStorage.setItem(scrollKey, String(window.scrollY));} catch { /* Optional browser storage. */ }});

// Unsubmitted text stays in this browser tab. Paid authorisations are never restored.
document.querySelectorAll('[data-save-draft]').forEach(form => {
  const key = 'outreach-intake:' + location.pathname;
  const fields = [...form.elements].filter(e => e.name && !['submit', 'password', 'hidden'].includes(e.type) && !['planning_confirm', 'acknowledge_prior', 'confirm_selection', 'confirmed'].includes(e.name));
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
    const version = form.dataset.draftVersion || '';
    if (saved && form.dataset.serverError !== 'true' && (form.dataset.serverValues !== 'true' || (version && saved._version === version))) fields.forEach(field => {
      if (!Object.hasOwn(saved, field.name)) return;
      if (field.type === 'checkbox') field.checked = saved[field.name].includes(field.value);
      else field.value = saved[field.name];
    });
  } catch { /* Server-saved drafts remain available if browser storage is blocked. */ }
  form.addEventListener('input', () => {
    const values = {_version: form.dataset.draftVersion || ''};
    fields.forEach(field => {
      if (field.type === 'checkbox') {
        values[field.name] ||= [];
        if (field.checked) values[field.name].push(field.value);
      } else values[field.name] = field.value;
    });
    try {sessionStorage.setItem(key, JSON.stringify(values));
      const status = form.querySelector('[data-draft-status]');
      if (status) status.textContent = 'Unsubmitted changes kept in this tab';
    } catch { /* Saving to the server is still supported. */ }
  });
  form.addEventListener('submit', event => {
    queueMicrotask(() => { if (!event.defaultPrevented) { try {sessionStorage.removeItem(key);} catch { /* Optional browser storage. */ } } });
  });
});
document.querySelectorAll('.lead-selection').forEach(form => {
  const update = () => {
    const count = form.querySelectorAll('[name="lead_ids"]:checked:not(:disabled)').length;
    const status = form.querySelector('[data-selection-status]');
    if (status) status.textContent = count ? (form.hasAttribute('data-reviewed-selection') ? `${count} contacts selected` : `${count} selected — choose a campaign to add them`) : 'Select contacts to continue.';
    form.querySelectorAll('button').forEach(button => {button.disabled = count === 0;});
  };
  form.addEventListener('change', update);
  update();
});

document.querySelectorAll('.draft-selection').forEach(form => {
  const selectAll = form.querySelector('[data-select-drafts]');
  selectAll.addEventListener('change', () => {
    form.querySelectorAll('[name="draft_ids"]').forEach(box => {box.checked = selectAll.checked;});
  });
  const update = () => {
    const count = form.querySelectorAll('[name="draft_ids"]:checked').length;
    form.querySelector('[data-draft-selection-status]').textContent = count ? `${count} drafts selected for approval` : 'Select drafts to approve.';
    form.querySelector('button').disabled = count === 0;
  };
  form.addEventListener('change', update);
  update();
});


// A usable full form remains available when JavaScript is disabled.
document.querySelectorAll('[data-wizard]').forEach(form => {
  const steps = [...form.querySelectorAll('[data-step]')];
  const markers = [...form.querySelectorAll('[data-step-label]')];
  let current = Number(form.dataset.startStep || 0);
  form.noValidate = true;
  form.querySelectorAll('.wizard-controls').forEach(control => { control.hidden = false; });
  const summary = () => {
    const target = form.querySelector('[data-audience-summary]');
    target.replaceChildren();
    const rows = [
      ['Goal', form.elements.brief.value],
      ['Companies', form.elements.company_type.value || 'Add this before research'],
      ['Location', form.elements.geography.value || 'Add this before research'],
      ['Contacts', [...form.querySelectorAll('[name="contact_roles"]:checked')].map(e => e.closest('label').textContent.trim()).join(', ') || 'Add this before research']
    ];
    rows.forEach(([label, value]) => {
      const row = document.createElement('p');
      const strong = document.createElement('strong');
      strong.textContent = label + ': ';
      row.append(strong, document.createTextNode(value));
      target.append(row);
    });
    target.hidden = false;
  };
  const show = (index, focus = true) => {
    current = Math.max(0, Math.min(index, steps.length - 1));
    steps.forEach((step, i) => { step.hidden = i !== current; });
    markers.forEach((marker, i) => {
      if (i === current) marker.setAttribute('aria-current', 'step');
      else marker.removeAttribute('aria-current');
      marker.classList.toggle('complete', i < current);
    });
    if (current === steps.length - 1) summary();
    if (focus) {
      const heading = steps[current].querySelector('h2');
      heading.tabIndex = -1;
      heading.focus();
    }
  };
  const invalidIn = step => [...step.querySelectorAll('input,textarea,select')].find(e => !e.checkValidity());
  const revealError = field => {
    const index = steps.findIndex(step => step.contains(field));
    if (index >= 0) show(index, false);
    let ancestor = field.parentElement;
    while (ancestor && ancestor !== form) {
      if (ancestor.tagName === 'DETAILS') ancestor.open = true;
      ancestor = ancestor.parentElement;
    }
    field.reportValidity();
    field.focus();
  };
  const next = () => {
    const invalid = invalidIn(steps[current]);
    if (invalid) revealError(invalid);
    else show(current + 1);
  };
  form.querySelectorAll('[data-next]').forEach(button => button.addEventListener('click', next));
  form.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => show(current - 1)));
  form.addEventListener('submit', event => {
    if (current < steps.length - 1) { event.preventDefault(); next(); return; }
    const invalid = steps.map(invalidIn).find(Boolean);
    if (invalid) { event.preventDefault(); revealError(invalid); }
  });
  form.addEventListener('keydown', event => {
    if (event.key === 'Enter' && event.target.tagName === 'INPUT' && current < steps.length - 1) {
      event.preventDefault(); next();
    }
  });
  show(current, false);
  const error = form.querySelector('[data-form-error]');
  if (error) {
    const invalid = steps.map(invalidIn).find(Boolean);
    if (invalid) revealError(invalid);
    else error.focus();
  }
});
document.querySelectorAll('[data-provider-form]').forEach(form => {
  const choice = form.querySelector('[name="provider"]');
  const update = () => {
    form.querySelectorAll('[data-provider-help]').forEach(section => { section.hidden = section.dataset.providerHelp !== choice.value; });
  };
  choice.addEventListener('change', update);
  update();
});


// Paid planning uses saved preferences; unsaved edits must be saved first.
document.querySelectorAll('[data-paid-planning], [data-local-planning]').forEach(planning => {
  const editor = document.querySelector('[data-wizard], .audience-form');
  if (!editor) return;
  const fields = [...editor.elements].filter(e => e.name && !['hidden','submit','button'].includes(e.type));
  const initial = field => field.type === 'checkbox' ? field.defaultChecked :
    field.tagName === 'SELECT' ? ([...field.options].find(o => o.defaultSelected) || field.options[0]).value : field.defaultValue;
  const update = () => {
    const dirty = fields.some(field => (field.type === 'checkbox' ? field.checked : field.value) !== initial(field));
    planning.querySelector('[value="plan"], [value="plan_local"]').disabled = dirty;
    planning.querySelector('[data-planning-status]').textContent = dirty ?
      'Save your audience edits before creating the plan.' : 'Uses the saved audience. Save any edits before planning.';
    if (dirty && planning.querySelector('[name="planning_confirm"]')) planning.querySelector('[name="planning_confirm"]').checked = false;
  };
  editor.addEventListener('input', update);
  editor.addEventListener('change', update);
  update();
});

// Keep the user informed during normal HTML form submission without changing payloads.
const actionFeedback = document.querySelector('[data-action-feedback]');
const busyForms = new Map();
const actionMessage = (form, button) => {
  if (form.dataset.busy) return form.dataset.busy;
  const path = new URL(form.action, location.href).pathname;
  if (/^\/campaigns\/[^/]+\/research$/.test(path)) return 'Saving the next research batch for free. No provider request or email is being made.';
  if (path.endsWith('/revise')) return 'Saving a revised audience for free. The original research and spending stay unchanged.';
  if (path.endsWith('/recover-discovery')) return 'Recovering saved company suggestions. No provider request is being made.';
  if (path.endsWith('/remove')) return button?.value === 'delete' ? 'Deleting the confirmed unused draft…' : button?.value === 'restore' ? 'Restoring saved work…' : 'Archiving work and keeping its history…';
  if (path === '/research/intake' || /^\/research\/[^/]+\/intake$/.test(path)) return button?.value === 'plan' ? 'Starting your approved paid planning request. You will review the plan before company research.' : 'Saving your audience. No paid research or email is starting.';
  if (path.includes('/check-openrouter')) return 'Checking OpenRouter key access. No model request is being made.';
  if (path.endsWith('/verify') || path === '/accounts') return 'Checking sending and inbox login. No email is being sent.';
  if (path === '/setup/model') return 'Running the paid AI model diagnostic…';
  if (path === '/setup/mail') return 'Checking sending and inbox login. No email is being sent.';
  if (path === '/setup/providers') return 'Encrypting and saving your provider keys privately…';
  if (path.endsWith('/approve') && path.startsWith('/research/')) return 'Saving your approved plan and starting research within its cap…';
  if (path.endsWith('/refine')) return 'Starting an AI request to update the research plan…';
  if (path.endsWith('/resume')) return 'Resuming approved research. Completed requests stay saved.';
  if (path.endsWith('/pause') || path.endsWith('/stop')) return 'Requesting a stop after the current operation. Saved work is kept.';
  if (path.endsWith('/draft-all')) return 'Starting paid AI drafting. Progress will show on the next page; no email is sent.';
  if (path.endsWith('/draft')) return 'Writing this smaller batch with paid AI requests. Drafts save as they finish; no email is sent.';
  if (path.endsWith('/attachments')) return 'Uploading campaign files. No email is sent.';
  if (path.includes('/attachments/') && path.endsWith('/remove')) return 'Removing the file from future emails. Saved history is kept.';
  if (path.startsWith('/research/') && path.endsWith('/use')) return 'Saving your approved contact selection. No research or email is started.';
  if (path === '/inbox/check') return 'Checking your inbox and matching campaign replies…';
  if (path.includes('/send') || path.endsWith('/test') || path.endsWith('/test-send')) return 'Processing your approved sending request. Check the saved result before repeating it.';
  if (path.includes('approve')) return 'Saving your approval. This step does not launch email sending.';
  return 'Saving your changes. Waiting for the app to confirm…';
};
const resetFeedback = () => {
  busyForms.forEach((state, form) => {
    clearTimeout(state.timer);
    form.removeAttribute('aria-busy');
    form.classList.remove('is-submitting');
    if (state.button) {
      state.button.textContent = state.original;
      state.button.removeAttribute('aria-disabled');
    }
  });
  busyForms.clear();
  if (actionFeedback) actionFeedback.hidden = true;
};
document.querySelectorAll('form').forEach(form => {
  if (form.method.toLowerCase() !== 'post' || new URL(form.action, location.href).pathname === '/backup') return;
  form.addEventListener('submit', event => {
    if (event.defaultPrevented) return;
    if (busyForms.has(form)) { event.preventDefault(); return; }
    // Wizard and selection validation run before this listener. Keep submitter values intact.
    if (!form.noValidate && !form.checkValidity()) return;
    const button = event.submitter || form.querySelector('button[type=submit],button:not([type])');
    const state = {button, original: button?.textContent, timer: null};
    busyForms.set(form, state);
    form.setAttribute('aria-busy', 'true');
    form.classList.add('is-submitting');
    if (button) { button.setAttribute('aria-disabled', 'true'); button.textContent = form.dataset.busyLabel || 'Working…'; }
    if (actionFeedback) {
      actionFeedback.querySelector('[data-action-message]').textContent = actionMessage(form, button);
      actionFeedback.hidden = false;
    }
    state.timer = setTimeout(() => {
      if (actionFeedback && busyForms.has(form)) actionFeedback.querySelector('[data-action-message]').textContent =
        'Still waiting for the app to confirm this request. Do not submit it again; check saved progress and history if the connection is interrupted.';
    }, 15000);
  });
  form.addEventListener('click', event => {
    if (busyForms.has(form) && event.target.closest('button,input[type=submit]')) event.preventDefault();
  });
});
window.addEventListener('pageshow', resetFeedback);

// Only read local status endpoints. These polls never start research or send email.
const pollStatus = (url, update, failed) => {
  let timer, controller, stopped = false, running = false, failures = 0;
  const tick = async () => {
    if (stopped || running) return;
    if (document.hidden) { timer = setTimeout(tick, 5000); return; }
    running = true;
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(url, {signal:controller.signal, cache:'no-store'});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw Error('Status unavailable');
      const value = await response.json();
      failures = 0;
      if (update(value) === false) stopped = true;
    } catch {
      if (!stopped) { failures++; failed(); }
    } finally {
      clearTimeout(timeout);
      running = false;
      if (!stopped) timer = setTimeout(tick, Math.min(30000, 5000 * Math.pow(2, failures)));
    }
  };
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !stopped && !running) { clearTimeout(timer); tick(); }
  });
  window.addEventListener('pagehide', () => {stopped = true; clearTimeout(timer); controller?.abort();});
  window.addEventListener('pageshow', event => {if (event.persisted) {stopped=false; tick();}});
  tick();
};
const activityLabel = document.querySelector('[data-activity-label]');
if (activityLabel) {
  const panel = document.querySelector('[data-activity-panel]');
  pollStatus('/workspace/activity', value => {
    const jobs = value.jobs;
    activityLabel.textContent = jobs.length ? jobs.length + ' task' + (jobs.length === 1 ? '' : 's') + ' running' : 'No background tasks';
    activityLabel.classList.toggle('is-working', jobs.length > 0);
    panel.hidden = jobs.length === 0;
    const list = panel.querySelector('[data-activity-jobs]');
    list.replaceChildren();
    jobs.forEach(job => {
      const row = document.createElement('li'), link = document.createElement('a'), detail = document.createElement('span');
      link.textContent = job.title; link.href = job.href;
      detail.textContent = job.detail;
      row.append(link, detail); list.append(row);
    });
    panel.querySelector('[data-activity-health]').textContent = 'Live updates · Checked ' + new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
    document.querySelectorAll('[data-job-progress]').forEach(section => {
      const kind = section.dataset.jobProgress, job = jobs.find(j => j.kind === kind), recent = value.recent?.[kind];
      const text = section.querySelector('[data-job-detail]');
      if (recent && kind === 'sending') recent.remaining = Math.max(0, recent.total - recent.processed);
      document.querySelectorAll('[data-job-control],[data-job-static-note]').forEach(control => {control.hidden = !job;});
      text.textContent = job?.detail || recent?.detail || 'This job is no longer running in this app process. Open saved results to check its outcome.';
      section.querySelector('[data-job-open]').hidden = !!job;
      if (recent) {
        document.querySelectorAll('[data-job-count]').forEach(count => { if (Object.hasOwn(recent, count.dataset.jobCount)) count.textContent = recent[count.dataset.jobCount]; });
        const bar = document.querySelector('[data-send-progress]');
        if (bar && recent.total) {
          bar.setAttribute('aria-valuenow', recent.processed);
          bar.querySelector('span').style.width = Math.min(100, 100 * recent.processed / recent.total) + '%';
        }
      }
    });
  }, () => {
    activityLabel.textContent = 'Live updates interrupted';
    panel.querySelector('[data-activity-health]').textContent = 'Reconnecting. Work may still be running; no operation will be retried by this status check.';
    document.querySelectorAll('[data-job-detail]').forEach(node => {node.textContent='Live updates interrupted. Reconnecting; inspect saved results before repeating any operation.';});
  });
}

document.querySelectorAll('[data-research-progress]:not([hidden])').forEach(section => {
  pollStatus(section.dataset.researchProgress, value => {
    section.querySelector('[data-progress-label]').textContent = value.label;
    if (value.requests) {
      const r=value.requests;
      const waiting=section.querySelector("[data-provider-wait]");
      if(waiting){
        waiting.hidden=!r.request_started;
        if(r.request_started){
          const seconds=Math.max(0,Math.floor((Date.now()-Date.parse(r.request_started))/1000));
          waiting.textContent="Waiting for the current provider request · "+seconds+"s. Results save when it finishes; do not submit another request.";
        }
      }
      document.querySelectorAll('[data-summary]').forEach(node=>{node.textContent=r[node.dataset.summary];});
      document.querySelectorAll('[data-request-summary]').forEach(node=>{
        node.textContent=r.waiting ? r.completed+' requests finished · '+r.waiting+' waiting for the provider.' :
          r.needs_check ? r.completed+' requests finished · '+r.needs_check+' outcomes need checking. Nothing will be retried automatically.' :
          r.total ? 'All '+r.total+' requests finished. Nothing is waiting.' : 'No provider request has been made.';
      });
    }

    document.querySelectorAll('[data-run-status]').forEach(node => {node.textContent = value.label;});
    document.querySelectorAll('[data-research-count]').forEach(node => {node.textContent = value.companies;});
    document.querySelectorAll('[data-research-spend]').forEach(node => {node.textContent = '$' + Number(value.spent).toFixed(4);});
    document.querySelectorAll('[data-research-pause]').forEach(form => {form.hidden = value.status !== 'running';});
    section.querySelector('[data-progress-detail]').textContent = value.detail;
    section.querySelector('[data-progress-companies]').textContent = value.companies;
    section.querySelector('[data-progress-spent]').textContent = '$' + Number(value.spent).toFixed(4);
    section.querySelector('[data-poll-health]').textContent = value.active ? 'Live · ' + new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : 'Work saved';
    section.querySelector('[data-progress-open]').hidden = value.active;
    section.querySelector('.work-spinner').hidden = !value.active;
    if (!value.active) {
      section.querySelector('[data-progress-explanation]').textContent = 'Open the latest saved result to review it. Your current selections and edits have been kept in place.';
      return false;
    }
  }, () => {section.querySelector('[data-poll-health]').textContent = 'Updates interrupted · reconnecting';});
});

// Reveal invalid inputs inside optional editors before native browser focus.
document.addEventListener('invalid', event => {
  let ancestor=event.target.parentElement;
  while(ancestor){if(ancestor.tagName==='DETAILS') ancestor.open=true; ancestor=ancestor.parentElement;}
}, true);

// Show saved-run times in the laptop's local timezone, keeping a UTC fallback.
document.querySelectorAll('time[data-local-time]').forEach(element => {
  const date = new Date(element.dateTime);
  if (Number.isNaN(date.getTime())) return;
  element.textContent = new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
  }).format(date);
  element.title = date.toLocaleString();
});
