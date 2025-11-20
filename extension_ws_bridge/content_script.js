
(function(){
  function notify(){
    try{ chrome.runtime.sendMessage({event:"pageReady", url: location.href}); }catch(e){}
  }
  if (document.readyState === "complete" || document.readyState === "interactive") setTimeout(notify, 0);
  window.addEventListener("load", notify, {once:true});
  document.addEventListener("DOMContentLoaded", notify, {once:true});
  (function(history){
    const p = history.pushState, r = history.replaceState;
    history.pushState = function(){ const rv = p.apply(this, arguments); setTimeout(notify, 0); return rv; };
    history.replaceState = function(){ const rv = r.apply(this, arguments); setTimeout(notify, 0); return rv; };
  })(window.history);
  window.addEventListener("popstate", notify);
})();
