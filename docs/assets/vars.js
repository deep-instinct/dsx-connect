document.addEventListener("DOMContentLoaded", () => {
  const inputs = document.querySelectorAll("[data-var-input]");
  const values = {};
  const codeBlocks = document.querySelectorAll("pre > code");

  function applyValue(name, value) {
    values[name] = value;
    document.querySelectorAll(`[data-var="${name}"]`).forEach((el) => {
      el.textContent = value;
    });

    codeBlocks.forEach((el) => {
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
});
