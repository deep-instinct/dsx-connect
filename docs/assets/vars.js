function initVars() {
  const inputs = document.querySelectorAll("[data-var-input]");
  const values = {};

  function applyValue(name, value) {
    values[name] = value;
    document.querySelectorAll(`[data-var="${name}"]`).forEach((el) => {
      el.textContent = value;
    });

    document.querySelectorAll("pre > code").forEach((el) => {
      if (!el.dataset.originalText) {
        el.dataset.originalText = el.textContent;
      }
      let nextText = el.dataset.originalText;
      Object.entries(values).forEach(([key, val]) => {
        const token = new RegExp(`\\{\\{${key}\\}\\}`, "g");
        nextText = nextText.replace(token, val);
      });
      el.textContent = nextText;
    });
  }

  inputs.forEach((input) => {
    const name = input.getAttribute("data-var-input");
    const defaultValue = input.value;
    applyValue(name, defaultValue);

    input.addEventListener("input", (e) => {
      applyValue(name, e.target.value);
    });
  });
}

if (window.document$ && typeof window.document$.subscribe === "function") {
  window.document$.subscribe(initVars);
} else {
  document.addEventListener("DOMContentLoaded", initVars);
}
