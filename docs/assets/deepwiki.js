(function () {
  if (window.__agentdescentDeepWiki) return;
  window.__agentdescentDeepWiki = true;

  var REPO = 'ThinkFlowLab/agentdescent';
  var ENDPOINT = 'https://mcp.deepwiki.com/mcp';
  var PAGE = 'https://deepwiki.com/' + REPO;
  var icons = {
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>',
    logo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H20v17H7.5A2.5 2.5 0 0 0 5 21.5z"/><path d="M5 4.5v17"/><path d="M9 7h7M9 10h7"/></svg>',
    spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M12 19V5"/><path d="M6 11l6-6 6 6"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-5M12 8h.01"/></svg>'
  };

  var launcher = document.createElement('button');
  launcher.type = 'button';
  launcher.className = 'dw-launcher';
  launcher.id = 'dw-launcher';
  launcher.title = 'Ask DeepWiki';
  launcher.setAttribute('aria-label', 'Ask DeepWiki');
  launcher.setAttribute('aria-expanded', 'false');
  launcher.setAttribute('aria-controls', 'dw-panel');
  launcher.innerHTML = icons.chat + '<span class="dw-launcher-text">Ask DeepWiki</span><span class="dw-dot" aria-hidden="true"></span>';

  var panel = document.createElement('section');
  panel.className = 'dw-panel';
  panel.id = 'dw-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Ask DeepWiki');
  panel.innerHTML = [
    '<header class="dw-head">',
    '<div class="dw-brand"><span class="dw-logo">' + icons.logo + '</span>',
    '<div><strong>DeepWiki</strong><span class="dw-repo"><i></i>' + REPO + '</span></div></div>',
    '<div class="dw-head-actions">',
    '<a class="dw-icon-btn" href="/deepwiki/" title="About DeepWiki and MCP" aria-label="About DeepWiki and MCP">' + icons.info + '</a>',
    '<button type="button" class="dw-icon-btn" id="dw-new" aria-label="New chat" title="New chat">' + icons.refresh + '</button>',
    '<button type="button" class="dw-icon-btn" id="dw-close" aria-label="Close" title="Close">' + icons.close + '</button>',
    '</div></header>',
    '<div class="dw-tabs">',
    '<button type="button" class="dw-tab active">Chat</button>',
    '<a class="dw-tab" href="' + PAGE + '" target="_blank" rel="noopener">Open page \u2197</a>',
    '</div>',
    '<div class="dw-log" id="dw-log" role="log" aria-live="polite">',
    '<div class="dw-empty">',
    '<span class="dw-empty-icon">' + icons.spark + '</span>',
    '<h3>Ask the codebase</h3>',
    '<p>Ask about the architecture, a command, or where a mechanism lives. Answers come from the ThinkFlowLab index; verify the source links.</p>',
    '<div class="dw-prompts">',
    '<button type="button" class="dw-prompt" data-q="How does AgentDescent merge conflicting diffs?"><span>How does merging work?</span><small>Aggregator, conflicts, fusion</small><b>\u2192</b></button>',
    '<button type="button" class="dw-prompt" data-q="How do I evolve a skill directory with AgentDescent?"><span>Evolve a skill directory</span><small>init, plan, evolve, apply</small><b>\u2192</b></button>',
    '<button type="button" class="dw-prompt" data-q="What is the difference between the synchronous and asynchronous runtime?"><span>Sync vs async</span><small>Round barrier, staleness, tail latency</small><b>\u2192</b></button>',
    '</div></div></div>',
    '<form class="dw-form" id="dw-form">',
    '<div class="dw-input-wrap">',
    '<textarea id="dw-input" rows="1" placeholder="Ask about the code\u2026" aria-label="Your question"></textarea>',
    '<button type="submit" class="dw-send" id="dw-send" aria-label="Send">' + icons.send + '</button>',
    '</div>',
    '<div class="dw-hint"><span>DeepWiki is third-party and model-generated. Verify load-bearing answers against the source.</span><a href="/deepwiki/">Caveats</a></div>',
    '</form>'
  ].join('');

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  var log = panel.querySelector('#dw-log');
  var form = panel.querySelector('#dw-form');
  var input = panel.querySelector('#dw-input');
  var send = panel.querySelector('#dw-send');
  var close = panel.querySelector('#dw-close');
  var newChat = panel.querySelector('#dw-new');
  var emptyTemplate = log.querySelector('.dw-empty').cloneNode(true);
  var busy = false;
  var history = [];
  var controller = null;

  function scroll() { log.scrollTop = log.scrollHeight; }
  function openPanel() {
    panel.hidden = false;
    launcher.setAttribute('aria-expanded', 'true');
    input.focus();
  }
  function closePanel() {
    panel.hidden = true;
    launcher.setAttribute('aria-expanded', 'false');
    launcher.focus();
  }
  function bindPrompts(root) {
    Array.prototype.forEach.call(root.querySelectorAll('.dw-prompt'), function (prompt) {
      prompt.addEventListener('click', function () {
        input.value = prompt.getAttribute('data-q') || '';
        form.requestSubmit();
      });
    });
  }
  function resetChat() {
    if (controller) { controller.abort(); controller = null; }
    history = [];
    while (log.firstChild) log.removeChild(log.firstChild);
    var empty = emptyTemplate.cloneNode(true);
    log.appendChild(empty);
    bindPrompts(empty);
    input.value = '';
    input.style.height = 'auto';
    input.focus();
  }

  launcher.addEventListener('click', function () {
    if (panel.hidden) openPanel(); else closePanel();
  });
  close.addEventListener('click', closePanel);
  newChat.addEventListener('click', resetChat);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !panel.hidden) closePanel();
  });
  document.addEventListener('click', function (event) {
    if (!event.target || !event.target.closest) return;
    var trigger = event.target.closest('[data-deepwiki-open]');
    if (trigger) { event.preventDefault(); openPanel(); }
  });

  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener('input', function () {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 112) + 'px';
  });

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (char) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char];
    });
  }
  function inline(text) {
    var value = escapeHtml(text);
    value = value.replace(/`([^`]+)`/g, '<code>$1</code>');
    value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    value = value.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    value = value.replace(/\[([^\]]+)\]\((\/[^\s)]+)\)/g, '<a href="https://deepwiki.com$2" target="_blank" rel="noopener">$1</a>');
    return value;
  }
  function renderProse(text) {
    var lines = text.split(/\r?\n/);
    var html = '';
    var paragraph = [];
    var list = null;
    function flushParagraph() {
      if (paragraph.length) {
        html += '<p>' + inline(paragraph.join(' ')) + '</p>';
        paragraph = [];
      }
    }
    function closeList() {
      if (list) { html += '</' + list + '>'; list = null; }
    }
    lines.forEach(function (raw) {
      var line = raw.trim();
      if (!line) { flushParagraph(); closeList(); return; }
      var heading = line.match(/^(#{1,4})\s+(.*)$/);
      if (heading) { flushParagraph(); closeList(); html += '<h4>' + inline(heading[2]) + '</h4>'; return; }
      var unordered = line.match(/^[-*]\s+(.*)$/);
      if (unordered) {
        flushParagraph();
        if (list !== 'ul') { closeList(); html += '<ul>'; list = 'ul'; }
        html += '<li>' + inline(unordered[1]) + '</li>';
        return;
      }
      var ordered = line.match(/^\d+\.\s+(.*)$/);
      if (ordered) {
        flushParagraph();
        if (list !== 'ol') { closeList(); html += '<ol>'; list = 'ol'; }
        html += '<li>' + inline(ordered[1]) + '</li>';
        return;
      }
      var quote = line.match(/^>\s?(.*)$/);
      if (quote) { flushParagraph(); closeList(); html += '<blockquote>' + inline(quote[1]) + '</blockquote>'; return; }
      paragraph.push(line);
    });
    flushParagraph();
    closeList();
    return html;
  }
  function renderMarkdown(text) {
    var parts = String(text || '').split(/```[a-zA-Z0-9_-]*\n?([\s\S]*?)```/g);
    var html = '';
    for (var i = 0; i < parts.length; i += 2) {
      if (parts[i]) html += renderProse(parts[i]);
      if (i + 1 < parts.length) html += '<pre><code>' + escapeHtml(parts[i + 1].replace(/\n$/, '')) + '</code></pre>';
    }
    return html || '<p>' + escapeHtml(text) + '</p>';
  }

  function copyText(text, button) {
    if (!navigator.clipboard) { button.textContent = 'Copy unavailable'; return; }
    navigator.clipboard.writeText(text).then(function () {
      button.textContent = 'Copied';
      setTimeout(function () { button.textContent = 'Copy'; }, 1400);
    }).catch(function () { button.textContent = 'Copy failed'; });
  }

  function message(role, text) {
    var row = document.createElement('div');
    row.className = 'dw-msg dw-' + role;
    if (role === 'bot') {
      var avatar = document.createElement('span');
      avatar.className = 'dw-avatar';
      avatar.textContent = 'DW';
      row.appendChild(avatar);
    }
    var bubble = document.createElement('div');
    bubble.className = 'dw-bubble';
    if (role === 'user') {
      bubble.textContent = text;
    } else {
      var meta = document.createElement('div');
      meta.className = 'dw-meta-row';
      var label = document.createElement('span');
      label.className = 'dw-meta';
      label.textContent = 'DeepWiki';
      var copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'dw-copy';
      copy.textContent = 'Copy';
      copy.addEventListener('click', function () { copyText(text, copy); });
      meta.appendChild(label);
      meta.appendChild(copy);
      var body = document.createElement('div');
      body.className = 'dw-md';
      body.innerHTML = renderMarkdown(text);
      bubble.appendChild(meta);
      bubble.appendChild(body);
    }
    row.appendChild(bubble);
    log.appendChild(row);
    scroll();
    return row;
  }

  function thinking() {
    var row = document.createElement('div');
    row.className = 'dw-msg dw-bot dw-thinking';
    row.innerHTML = '<span class="dw-avatar">DW</span><div class="dw-bubble"><span class="dw-dots"><i></i><i></i><i></i></span><span>Searching the index\u2026</span><button type="button" class="dw-stop">Stop</button></div>';
    log.appendChild(row);
    scroll();
    return row;
  }

  function error(text, question) {
    var row = message('bot', text);
    row.querySelector('.dw-bubble').classList.add('dw-error');
    var link = document.createElement('p');
    link.innerHTML = '<a href="' + PAGE + '" target="_blank" rel="noopener">Open the DeepWiki page \u2197</a>';
    row.querySelector('.dw-md').appendChild(link);
    if (question) {
      var retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'dw-retry';
      retry.textContent = 'Retry';
      retry.addEventListener('click', function () {
        row.remove();
        ask(question);
      });
      row.querySelector('.dw-md').appendChild(retry);
    }
    scroll();
  }

  function parseSse(raw) {
    var last = null;
    raw.split(/\r?\n/).forEach(function (line) {
      if (line.indexOf('data: ') !== 0) return;
      try {
        var obj = JSON.parse(line.slice(6));
        if (obj && (obj.result || obj.error)) last = obj;
      } catch (e) { /* keep-alive or partial event */ }
    });
    if (!last) {
      try {
        var direct = JSON.parse(raw);
        if (direct && (direct.result || direct.error)) last = direct;
      } catch (e) { /* not JSON */ }
    }
    return last;
  }

  function call(question, signal) {
    var body = {
      jsonrpc: '2.0',
      id: 1,
      method: 'tools/call',
      params: {
        name: 'ask_wiki_question',
        arguments: { repoName: REPO, question: question }
      }
    };
    return fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream' },
      body: JSON.stringify(body),
      signal: signal
    }).then(function (response) {
      if (!response.ok) throw new Error('DeepWiki returned HTTP ' + response.status);
      return response.text();
    }).then(function (raw) {
      var payload = parseSse(raw);
      if (!payload) throw new Error('DeepWiki returned an unreadable response.');
      if (payload.error) throw new Error(payload.error.message || 'DeepWiki returned an error.');
      var result = payload.result || {};
      var text = (result.content || []).map(function (part) { return part.text || ''; }).join('\n').trim();
      if (result.isError) return { ok: false, text: text || 'DeepWiki could not answer.' };
      return { ok: true, text: text || 'DeepWiki returned an empty answer.' };
    });
  }

  function ask(question) {
    if (busy) return;
    busy = true;
    send.disabled = true;
    var empty = log.querySelector('.dw-empty');
    if (empty) empty.remove();
    message('user', question);
    var pending = thinking();
    var stop = pending.querySelector('.dw-stop');
    if (stop) stop.addEventListener('click', function () {
      if (controller) controller.abort();
    });
    var context = history.slice(-2).map(function (item) {
      return 'Q: ' + item.q + '\nA: ' + item.a.slice(0, 900);
    }).join('\n\n');
    var prompt = context
      ? 'Previous conversation for context:\n' + context + '\n\nNew question: ' + question
      : question;
    controller = ('AbortController' in window) ? new AbortController() : null;
    call(prompt, controller ? controller.signal : undefined).then(function (result) {
      if (pending.parentNode) pending.remove();
      if (result.ok) {
        history.push({ q: question, a: result.text });
        if (history.length > 4) history.shift();
        message('bot', result.text);
      } else {
        error(result.text, question);
      }
    }).catch(function (failure) {
      if (pending.parentNode) pending.remove();
      if (failure && failure.name === 'AbortError') {
        error('Stopped. Ask again when you are ready.', question);
      } else {
        error('DeepWiki is unavailable right now: ' + failure.message, question);
      }
    }).then(function () {
      controller = null;
      busy = false;
      send.disabled = false;
      input.focus();
    });
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var question = input.value.trim();
    if (!question) return;
    input.value = '';
    input.style.height = 'auto';
    ask(question);
  });
  bindPrompts(log);
})();
