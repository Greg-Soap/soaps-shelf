import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { parseHTML } from "linkedom";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../..");
const VENDOR_ROOT = path.join(REPO_ROOT, "vendor/webtoepub");
const SCRIPT_ORDER = path.join(VENDOR_ROOT, "script-order.txt");

const SKIP_SCRIPTS = new Set([
  "js/main.js",
  "js/EpubPacker.js",
]);

function i18nGetMessage(key, substitutions) {
  let text = String(key || "")
    .replace(/^__MSG_/, "")
    .replace(/__$/g, "")
    .replace(/_/g, " ")
    .trim();
  if (!text) text = String(key || "");
  if (Array.isArray(substitutions)) {
    for (const value of substitutions) text += ` ${value}`;
  } else if (substitutions != null) {
    text += ` ${substitutions}`;
  }
  return text;
}

function createChromeStub() {
  return {
    i18n: { getMessage: i18nGetMessage },
    runtime: {
      getURL: () => "chrome-extension://soaps-shelf-headless/",
      lastError: null,
      getManifest: () => ({ manifest_version: 3 }),
      sendMessage: () => {},
      getPlatformInfo: async () => ({ os: "linux" }),
    },
    cookies: {
      getAll: async () => [],
      set: async () => {},
      remove: async () => {},
    },
    declarativeNetRequest: {
      getSessionRules: async () => [],
      updateSessionRules: async () => {},
    },
    storage: {
      local: {
        get: (keys, cb) => {
          if (typeof cb === "function") cb({});
          return Promise.resolve({});
        },
        set: (items, cb) => {
          if (typeof cb === "function") cb();
          return Promise.resolve();
        },
        remove: (keys, cb) => {
          if (typeof cb === "function") cb();
          return Promise.resolve();
        },
        clear: (cb) => {
          if (typeof cb === "function") cb();
          return Promise.resolve();
        },
        getBytesInUse: (keys, cb) => {
          if (typeof cb === "function") cb(0);
          return Promise.resolve(0);
        },
      },
    },
    tabs: {
      create: async () => ({}),
      executeScript: (_tabId, _opts, cb) => cb && cb([]),
    },
    downloads: {
      download: (_opts, cb) => cb && cb(1),
      onChanged: { addListener() {} },
    },
    scripting: { executeScript: async () => [] },
    webRequest: { onBeforeSendHeaders: { addListener() {} } },
  };
}

function createStubElement(document, id) {
  const lower = id.toLowerCase();
  let tag = "div";
  if (lower.includes("table")) tag = "table";
  else if (lower.includes("select")) tag = "select";
  else if (lower.includes("checkbox") || lower.includes("input") || lower.endsWith("tag")) tag = "input";
  else if (lower.includes("button")) tag = "button";
  else if (lower.includes("form")) tag = "form";
  else if (lower.includes("span")) tag = "span";

  const el = document.createElement(tag);
  el.id = id;
  if (tag === "input") {
    el.type = lower.includes("checkbox") ? "checkbox" : "text";
    el.checked = false;
    el.value = "";
  }
  if (tag === "table") {
    el.appendChild(document.createElement("tbody"));
  }
  el.hidden = false;
  el.style = el.style || {};
  el.onclick = null;
  el.onchange = null;
  el.onsubmit = null;
  const originalAdd = el.addEventListener?.bind(el);
  el.addEventListener = (...args) => {
    try {
      return originalAdd ? originalAdd(...args) : undefined;
    } catch {
      return undefined;
    }
  };
  document.body.appendChild(el);
  return el;
}

function installDomShims(window, document) {
  const realGet = document.getElementById.bind(document);
  document.getElementById = (id) => {
    if (!id) return null;
    return realGet(id) || createStubElement(document, id);
  };

  const store = new Map();
  window.localStorage = {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(String(key), String(value)),
    removeItem: (key) => store.delete(key),
    clear: () => store.clear(),
  };

  window.alert = () => {};
  window.confirm = () => true;
  window.prompt = () => null;
}

class FileReaderStub {
  constructor() {
    this.onload = null;
    this.onerror = null;
    this.result = null;
  }

  readAsArrayBuffer(blob) {
    Promise.resolve()
      .then(async () => {
        if (blob?.arrayBuffer) this.result = await blob.arrayBuffer();
        else this.result = new ArrayBuffer(0);
        this.onload?.({ target: this });
      })
      .catch((err) => this.onerror?.(err));
  }

  readAsText(blob) {
    Promise.resolve()
      .then(async () => {
        if (typeof blob === "string") this.result = blob;
        else if (blob?.text) this.result = await blob.text();
        else this.result = "";
        this.onload?.({ target: this });
      })
      .catch((err) => this.onerror?.(err));
  }
}

function hardenHeadlessBehavior(context) {
  const browserHeaders = {
    "User-Agent":
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
  };

  if (context.HttpClient) {
    const originalMakeOptions = context.HttpClient.makeOptions.bind(context.HttpClient);
    context.HttpClient.makeOptions = function makeOptions() {
      const options = originalMakeOptions();
      options.headers = { ...(options.headers || {}), ...browserHeaders };
      // Node fetch does not implement cookie jars; drop credentials to avoid noise.
      delete options.credentials;
      return options;
    };
  }

  if (context.FetchErrorHandler?.prototype) {
    context.FetchErrorHandler.prototype.promptUserForRetry = function promptUserForRetry(
      url,
      wrapOptions,
      _response,
      failError,
    ) {
      if (wrapOptions.retry?.retryDelay?.length > 0) {
        return this.retryFetch(url, wrapOptions);
      }
      return Promise.reject(failError);
    };
  }

  if (context.ChapterUrlsUI) {
    context.ChapterUrlsUI.prototype.connectButtonHandlers = function connectButtonHandlers() {};
    const originalPopulate = context.ChapterUrlsUI.prototype.populateChapterUrlsTable;
    context.ChapterUrlsUI.prototype.populateChapterUrlsTable = function populateChapterUrlsTable(chapters) {
      try {
        return originalPopulate.call(this, chapters);
      } catch {
        (chapters || []).forEach((chapter) => {
          chapter.row = null;
          if (chapter.isIncludeable === undefined) chapter.isIncludeable = true;
        });
      }
    };
    context.ChapterUrlsUI.showDownloadState = function showDownloadState() {};
  }

  if (context.ProgressBar) {
    context.ProgressBar.setMax = () => {};
    context.ProgressBar.setValue = () => {};
    context.ProgressBar.updateValue = () => {};
  }

  if (context.ErrorLog) {
    context.ErrorLog.showErrorMessage = (msg) => {
      console.error("[webtoepub]", msg?.message || String(msg));
    };
    context.ErrorLog.log = (msg) => {
      console.error("[webtoepub]", msg?.message || msg);
    };
  }

  try {
    const prefs = context.UserPreferences.readFromLocalStorage();
    prefs.skipImages.value = true;
    prefs.skipChaptersThatFailFetch.value = true;
    prefs.noDownloadPopup.value = true;
    context.__headlessPreferences = prefs;
  } catch (err) {
    console.warn("Could not init UserPreferences:", err.message);
  }
}

let cachedContext = null;

export function getVendorRoot() {
  return VENDOR_ROOT;
}

export function loadWebToEpubContext() {
  if (cachedContext) return cachedContext;

  const shell = parseHTML(`<!DOCTYPE html><html><head></head><body>
    <table id="chapterUrlsTable"><tbody></tbody></table>
    <tr id="loadingChapterUrlsPleaseWaitRow" hidden></tr>
    <select id="selectRangeStartChapter"></select>
    <select id="selectRangeEndChapter"></select>
    <input id="themeColorTag" />
    <button id="selectAllUrlsButton"></button>
    <button id="unselectAllUrlsButton"></button>
    <button id="reverseChapterUrlsOrderButton"></button>
    <button id="editChaptersUrlsButton"></button>
    <button id="copyUrlsToClipboardButton"></button>
    <input id="showChapterUrlsCheckbox" type="checkbox" />
    <form id="sbFiltersForm"></form>
    <span id="spanParserName"></span>
    <span id="spanDelayMs"></span>
    <button id="packEpubButton"></button>
  </body></html>`);

  const { window, document } = shell;
  installDomShims(window, document);
  const chromeStub = createChromeStub();

  const context = {
    console,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    fetch,
    URL,
    URLSearchParams,
    TextDecoder,
    TextEncoder,
    atob,
    btoa,
    Buffer,
    performance,
    AbortController,
    AbortSignal,
    FileReader: FileReaderStub,
    Blob: globalThis.Blob,
    queue: 0,
    window,
    document,
    navigator: { userAgent: "SoapShelf-WebToEpub/1.0" },
    location: { href: "https://localhost/" },
    Node: window.Node,
    Element: window.Element,
    HTMLElement: window.HTMLElement,
    NodeFilter: window.NodeFilter,
    DOMParser: window.DOMParser,
    XMLSerializer: window.XMLSerializer,
    XPathResult: window.XPathResult,
    MutationObserver: window.MutationObserver || class { observe() {} disconnect() {} },
    Image: window.HTMLImageElement,
    chrome: chromeStub,
    browser: chromeStub,
  };

  context.globalThis = context;
  context.self = context;
  window.chrome = chromeStub;
  window.browser = chromeStub;
  window.AbortController = AbortController;
  window.FileReader = FileReaderStub;
  window.fetch = fetch;

  vm.createContext(context);

  const order = fs
    .readFileSync(SCRIPT_ORDER, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  let loaded = 0;
  let failed = 0;
  for (const rel of order) {
    if (SKIP_SCRIPTS.has(rel)) continue;
    const full = path.join(VENDOR_ROOT, rel);
    if (!fs.existsSync(full)) {
      console.warn("Missing vendor script:", rel);
      failed += 1;
      continue;
    }
    const code = fs.readFileSync(full, "utf8");
    try {
      vm.runInContext(code, context, { filename: full, timeout: 20000 });
      loaded += 1;
    } catch (err) {
      failed += 1;
      console.warn(`Failed loading ${rel}:`, err.message);
    }
  }
  console.log(`WebToEpub scripts loaded=${loaded} failed=${failed}`);

  // Classic scripts use let/class — visible to later scripts in the VM, but not as
  // plain properties on the context object. Mirror the symbols we need.
  vm.runInContext(
    `
    globalThis.__wte = {
      parserFactory,
      Parser,
      UserPreferences,
      HttpClient,
      ChapterUrlsUI,
      util,
      UIText,
      ErrorLog,
      ProgressBar,
      FetchErrorHandler,
      ImageCollector,
      CoverImageUI: (typeof CoverImageUI !== "undefined") ? CoverImageUI : null,
      DefaultParser: (typeof DefaultParser !== "undefined") ? DefaultParser : null,
    };
    `,
    context,
    { filename: "export-wte-globals.js" },
  );

  const wte = context.__wte;
  for (const [key, value] of Object.entries(wte)) {
    context[key] = value;
  }

  hardenHeadlessBehavior(context);
  cachedContext = context;
  return context;
}

export function listRegisteredHosts() {
  const ctx = loadWebToEpubContext();
  const hosts = [];
  if (ctx.parserFactory?.parsers) {
    for (const host of ctx.parserFactory.parsers.keys()) {
      hosts.push(host);
    }
  }
  return hosts.sort();
}
