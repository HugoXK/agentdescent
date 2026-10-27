(() => {
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const copy = async (text, button) => {
    try {
      await navigator.clipboard.writeText(text);
      const before = button.textContent;
      button.textContent = 'Copied ✓';
      setTimeout(() => { button.textContent = before; }, 1300);
    } catch (_) {
      button.title = 'Clipboard unavailable; select the adjacent text to copy.';
    }
  };
  $$('[data-copy]').forEach((button) =>
    button.addEventListener('click', () => copy(button.dataset.copy, button)));

  const buttons = $$('[data-lang-btn]');
  const apply = (lang) => {
    const next = lang === 'en' ? 'en' : 'zh';
    document.documentElement.lang = next === 'zh' ? 'zh-CN' : 'en';
    $$('[data-lang]').forEach((node) => {
      node.hidden = node.dataset.lang !== next;
    });
    buttons.forEach((button) => {
      button.setAttribute('aria-pressed', button.dataset.langBtn === next ? 'true' : 'false');
    });
    try { localStorage.setItem('agentdescent-lang', next); } catch (_) { /* storage may be unavailable */ }
  };
  let saved = 'zh';
  try { saved = localStorage.getItem('agentdescent-lang') || 'zh'; } catch (_) { /* storage may be unavailable */ }
  if (buttons.length) {
    buttons.forEach((button) =>
      button.addEventListener('click', () => apply(button.dataset.langBtn)));
    apply(saved);
  }
})();
