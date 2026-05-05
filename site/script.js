// VoiceType marketing site — minimal JS
// Theme toggle (persisted), latest-version fetch, smooth scroll.

(function () {
  // --- Theme toggle ---
  const root = document.documentElement;
  const stored = localStorage.getItem('vt-theme') || 'dark';
  root.setAttribute('data-theme', stored);

  const toggle = document.getElementById('theme-toggle');
  const label  = document.getElementById('theme-label');

  function updateLabel(theme) {
    if (label) label.textContent = theme === 'dark' ? 'light' : 'dark';
  }

  updateLabel(stored);

  if (toggle) {
    toggle.addEventListener('click', () => {
      const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      localStorage.setItem('vt-theme', next);
      updateLabel(next);
    });
  }

  // --- Latest release version + SHA256 ---
  fetch('https://api.github.com/repos/polistician/voicetype/releases/latest')
    .then(r => r.ok ? r.json() : null)
    .then(release => {
      if (!release) return;
      const v = release.tag_name || 'v0.9.1';
      document.querySelectorAll('[data-latest-version]').forEach(el => el.textContent = v);

      const sha = (release.assets || []).find(a => a.name === 'VoiceType.dmg.sha256');
      if (sha) {
        fetch(sha.browser_download_url).then(r => r.text()).then(text => {
          const checksum = text.trim().split(/\s+/)[0];
          document.querySelectorAll('[data-latest-sha256]').forEach(el => el.textContent = checksum);
        });
      }
    })
    .catch(() => { /* keep HTML defaults */ });
})();
