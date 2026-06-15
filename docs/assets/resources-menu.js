document.addEventListener('DOMContentLoaded', () => {
  try {
    const header = document.querySelector('.md-header__options') || document.querySelector('.md-header__inner');
    if (!header) return;
    if (header.querySelector('.resources-menu')) return;

    const menu = document.createElement('div');
    menu.className = 'resources-menu';
    menu.innerHTML = `
      <button class="resources-toggle" type="button" aria-haspopup="true" aria-expanded="false">Resources ▾</button>
      <div class="resources-dropdown" role="menu">
        <a href="https://github.com/deep-instinct/dsx-connect/releases" target="_blank" rel="noreferrer" role="menuitem">Docker Compose Bundles</a>
        <a href="https://hub.docker.com/repositories/dsxconnect" target="_blank" rel="noreferrer" role="menuitem">DSX-Connect Image Repo</a>
        <a href="https://github.com/deep-instinct/dsx-connect" target="_blank" rel="noreferrer" role="menuitem">GitHub</a>
      </div>
    `;

    header.appendChild(menu);

    const toggle = menu.querySelector('.resources-toggle');
    const dropdown = menu.querySelector('.resources-dropdown');
    const closeDropdown = () => {
      dropdown.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
    };
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = dropdown.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', closeDropdown);
  } catch (e) {
    console.warn('Failed to inject resources menu', e);
  }
});
