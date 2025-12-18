document.addEventListener('DOMContentLoaded', () => {
  try {
    const repoButton = document.querySelector('.md-header__source');
    if (!repoButton) return;
    // Avoid duplicates on hot-reload
    if (document.querySelector('.md-header__docker')) return;
    const dockerLink = document.createElement('a');
    dockerLink.className = 'md-header__button md-header__docker';
    dockerLink.href = 'https://hub.docker.com/repositories/dsxconnect';
    dockerLink.target = '_blank';
    dockerLink.rel = 'noreferrer';
    dockerLink.title = 'Docker Hub';
    dockerLink.textContent = 'Docker';
    repoButton.insertAdjacentElement('afterend', dockerLink);
  } catch (e) {
    console.warn('Failed to inject Docker header link', e);
  }
});
