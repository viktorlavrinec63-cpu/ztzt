(function(){
  function pick(){
    const selector = 'div[data-identifier], div[role="button"], div[tabindex="0"]';
    const elements = Array.from(document.querySelectorAll(selector));
    let candidate = elements.find((el) => el.getAttribute('data-identifier'));
    if (!candidate) {
      candidate = elements.find((el) => /@/.test(el.innerText || el.textContent || ''));
    }
    if (candidate) {
      candidate.click();
      return true;
    }
    return false;
  }

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    if (pick() || attempts > 40) {
      clearInterval(timer);
    }
  }, 250);
})();
