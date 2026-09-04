// api-shim: wrapper promesses compatible chrome.* et browser.*
const fcBrowser = (() => {
  const b = typeof browser !== "undefined" ? browser : null;
  const c = typeof chrome !== "undefined" ? chrome : null;
  const hasBrowser = !!b && !!b.runtime;
  function promisify(fn, ctx) {
    return (...args) => new Promise((resolve, reject) => {
      try {
        if (hasBrowser && fn) return fn(...args).then(resolve, reject);
        fn.call(ctx, ...args, (res) => {
          if (c && c.runtime && c.runtime.lastError) reject(c.runtime.lastError);
          else resolve(res);
        });
      } catch (e) { reject(e); }
    });
  }
  return {
    storageLocalGet: (keys) => {
      if (hasBrowser && b.storage && b.storage.local) return b.storage.local.get(keys);
      return promisify(c.storage.local.get, c.storage.local)(keys);
    },
    storageLocalSet: (obj) => {
      if (hasBrowser && b.storage && b.storage.local) return b.storage.local.set(obj);
      return promisify(c.storage.local.set, c.storage.local)(obj);
    },
    cookiesGetAll: (details) => {
      if (hasBrowser && b.cookies) return b.cookies.getAll(details);
      return promisify(c.cookies.getAll, c.cookies)(details);
    },
    tabsQuery: (q) => {
      if (hasBrowser && b.tabs) return b.tabs.query(q);
      return promisify(c.tabs.query, c.tabs)(q);
    },
    tabsSendMessage: (tabId, msg) => {
      if (hasBrowser && b.tabs) return b.tabs.sendMessage(tabId, msg);
      return promisify(c.tabs.sendMessage, c.tabs)(tabId, msg);
    },
    runtimeSendMessage: (msg) => {
      if (hasBrowser && b.runtime) return b.runtime.sendMessage(msg);
      return promisify(c.runtime.sendMessage, c.runtime)(msg);
    },
    getUrl: (path) => (hasBrowser ? b.runtime.getURL(path) : c.runtime.getURL(path)),
  };
})();
