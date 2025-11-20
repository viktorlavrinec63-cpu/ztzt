
(() => {
  Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
  try { Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']}); } catch(e) {}
  try { Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]}); } catch(e) {}
  window.chrome = window.chrome || { runtime: {} };
  const toDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function() {
    try {
      const ctx = this.getContext('2d');
      if (ctx) {
        ctx.fillStyle = 'rgba(0,0,0,0.1)';
        ctx.fillRect(0,0,1,1);
      }
    } catch(e) {}
    return toDataURL.apply(this, arguments);
  };
  try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
      if (parameter === 37445) return 'Intel Inc.';
      if (parameter === 37446) return 'Intel Iris OpenGL Engine';
      return getParameter.apply(this, arguments);
    };
  } catch(e) {}
})();
