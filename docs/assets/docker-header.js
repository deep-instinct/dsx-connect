document.addEventListener('DOMContentLoaded', () => {
  try {
    const repoButton = document.querySelector('.md-header__source');
    const headerActions = document.querySelector('.md-header__options') || document.querySelector('.md-header__inner');
    if (!repoButton && !headerActions) return;
    // Avoid duplicates on hot-reload
    if ((repoButton && repoButton.parentElement && repoButton.parentElement.querySelector('.md-header__docker')) ||
        (headerActions && headerActions.querySelector('.md-header__docker'))) return;
    const dockerLink = document.createElement('a');
    dockerLink.className = 'md-header__button md-header__docker';
    dockerLink.href = 'https://hub.docker.com/repositories/dsxconnect';
    dockerLink.target = '_blank';
    dockerLink.rel = 'noreferrer';
    dockerLink.title = 'Go to Docker Hub image repository';
    // Use inline SVG icon
    dockerLink.innerHTML = `
      <svg class="docker-icon" aria-hidden="true" viewBox="0 0 640 512">
        <path d="M349.5 236.3h52.8c5.7 0 10.4-4.6 10.4-10.3V174c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c0 5.7 4.7 10.4 10.4 10.4zm-67.2 0h52.8c5.8 0 10.4-4.6 10.4-10.3V174c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c-.1 5.7 4.6 10.4 10.4 10.4zm-67.2 0h52.8c5.8 0 10.4-4.6 10.4-10.3V174c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c0 5.7 4.7 10.4 10.4 10.4zm-67.2 0h52.9c5.7 0 10.4-4.6 10.4-10.3V174c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c-.1 5.7 4.6 10.4 10.3 10.4zm-67.3 0h52.8c5.8 0 10.4-4.6 10.4-10.3V174c0-5.7-4.6-10.3-10.4-10.3H80.6c-5.7 0-10.4 4.6-10.4 10.3v51.9c0 5.7 4.7 10.4 10.4 10.4zM349.5 167h52.8c5.7 0 10.4-4.7 10.4-10.4V104.8c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c0 5.8 4.7 10.4 10.4 10.4zm-67.2 0h52.8c5.8 0 10.4-4.7 10.4-10.4V104.8c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c-.1 5.8 4.6 10.4 10.4 10.4zm-67.2 0h52.8c5.8 0 10.4-4.7 10.4-10.4V104.8c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c0 5.8 4.7 10.4 10.4 10.4zm-67.2 0h52.9c5.7 0 10.4-4.7 10.4-10.4V104.8c0-5.7-4.7-10.3-10.4-10.3h-52.8c-5.8 0-10.4 4.6-10.4 10.3v51.9c-.1 5.8 4.6 10.4 10.3 10.4zm-67.3 0h52.8c5.8 0 10.4-4.7 10.4-10.4V104.8c0-5.7-4.6-10.3-10.4-10.3H80.6c-5.7 0-10.4 4.6-10.4 10.3v51.9c0 5.8 4.7 10.4 10.4 10.4zm396.7 45.5c-2.8-2.1-18.3-13.4-53.4-13.4-9.2 0-18.4.8-27.5 2.3-6.5-45.2-44.5-67.5-46.7-68.8l-7.6-4.4-5 7c-7.6 11.4-13.1 24-16.8 36.9-6.3 22-6.3 43.2 0 60.7-14.1 8-33.5 12.9-56.1 12.9h-97.7c-27.8 0-50.4 22.3-50.4 49.7 0 32 9.8 58.1 29.1 77.5 17.4 17.5 41.9 27.1 68.9 27.1 13.5 0 26.8-1.6 39.3-4.8 20.7-5.1 39.5-13.6 56.1-25 26.8-18.6 47-43.5 59.1-72.3 29 1.3 60.1-4.7 87.1-17.5 22.5-10.7 50-30.3 59.3-63.2 0-0.1 1.1-3.2-2.1-5.6z"/>\n      </svg>\n    `;
    if (repoButton && repoButton.insertAdjacentElement) {
      repoButton.insertAdjacentElement('afterend', dockerLink);
    } else if (headerActions) {
      headerActions.appendChild(dockerLink);
    }
  } catch (e) {
    console.warn('Failed to inject Docker header link', e);
  }
});
