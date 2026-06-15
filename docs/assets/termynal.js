(function () {
  "use strict";

  function toNumber(value, fallback) {
    var num = Number(value);
    return Number.isFinite(num) ? num : fallback;
  }

  function initTermynal(el) {
    if (el.dataset.termynalRendered === "true") {
      return;
    }
    el.dataset.termynalRendered = "true";

    var typerDelay = toNumber(el.dataset.typerDelay, 30);
    var lineDelay = toNumber(el.dataset.tyLineDelay, 500);
    var lineNodes = Array.prototype.slice.call(el.querySelectorAll("[data-ty]"));
    var lines = lineNodes.map(function (node) {
      return {
        type: node.dataset.ty || "output",
        text: node.textContent || ""
      };
    });

    el.innerHTML = "";
    el.classList.add("termynal");

    var lineIndex = 0;

    function appendLine(line) {
      var lineEl = document.createElement("div");
      lineEl.className = "termynal-line termynal-" + line.type;
      el.appendChild(lineEl);
      return lineEl;
    }

    function typeLine(line) {
      if (!line) {
        return;
      }
      var lineEl = appendLine(line);
      if (!line.text) {
        lineIndex += 1;
        setTimeout(function () {
          typeLine(lines[lineIndex]);
        }, lineDelay);
        return;
      }

      var i = 0;

      function step() {
        lineEl.textContent += line.text.charAt(i);
        i += 1;
        if (i < line.text.length) {
          setTimeout(step, typerDelay);
        } else {
          lineIndex += 1;
          setTimeout(function () {
            typeLine(lines[lineIndex]);
          }, lineDelay);
        }
      }

      step();
    }

    setTimeout(function () {
      typeLine(lines[lineIndex]);
    }, lineDelay);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var elements = document.querySelectorAll("[data-termynal]");
    elements.forEach(function (el) {
      initTermynal(el);
    });
  });
})();
