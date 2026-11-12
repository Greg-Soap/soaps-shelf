import { loadWebToEpubContext, listRegisteredHosts } from "./sandbox.mjs";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function asText(value) {
  if (value == null) return null;
  if (typeof value === "string") return value.trim() || null;
  if (value.textContent != null) return String(value.textContent).trim() || null;
  return String(value).trim() || null;
}

function adapterIdFor(parser, url) {
  const name = parser?.constructor?.name || "DefaultParser";
  const host = (() => {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return "unknown";
    }
  })();
  if (name && name !== "DefaultParser") {
    return name.replace(/Parser$/, "").replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase();
  }
  return host;
}

function serializeContent(content, ctx) {
  if (!content) return "";
  try {
    if (ctx.util?.xmlToString) return ctx.util.xmlToString(content);
  } catch {
    // fall through
  }
  return content.innerHTML || content.outerHTML || "";
}

async function fetchInitialDom(ctx, url) {
  const response = await ctx.HttpClient.wrapFetch(url);
  return response.responseXML;
}

/**
 * Headless compile: WebToEpub parsers → chapter HTML JSON.
 */
export async function compileFiction(options) {
  const url = String(options.url || "").trim();
  if (!url) throw new Error("url is required");

  const chapterFrom = Number.isFinite(options.chapterFrom) ? Number(options.chapterFrom) : 0;
  const chapterTo =
    options.chapterTo == null || options.chapterTo === ""
      ? null
      : Number(options.chapterTo);
  const limit =
    options.limit == null || options.limit === "" ? null : Number(options.limit);
  const delayMs = Math.max(
    0,
    Math.round((Number(options.delay) || 0.55) * 1000),
  );

  const ctx = loadWebToEpubContext();
  const prefs = ctx.__headlessPreferences || ctx.UserPreferences.readFromLocalStorage();
  prefs.skipImages.value = true;
  prefs.skipChaptersThatFailFetch.value = true;

  const firstPageDom = await fetchInitialDom(ctx, url);
  const parser = ctx.parserFactory.fetch(url, firstPageDom);
  if (!parser) throw new Error(`No WebToEpub parser for ${url}`);

  parser.onUserPreferencesUpdate(prefs);
  parser.state.firstPageDom = firstPageDom;
  parser.state.chapterListUrl = url;

  const chapterUrlsUI = new ctx.ChapterUrlsUI(parser);
  let chapters = await parser.getChapterUrls(firstPageDom, chapterUrlsUI);
  if (!Array.isArray(chapters) || chapters.length === 0) {
    throw new Error("No chapters found for URL");
  }
  chapters = parser.cleanWebPageUrls(chapters);
  chapters.forEach((chapter) => {
    if (chapter.isIncludeable === undefined) chapter.isIncludeable = true;
    if (chapter.title) chapter.title = String(chapter.title).trim();
  });
  chapters = chapters.filter((chapter) => chapter.isIncludeable !== false);
  if (chapters.length === 0) {
    throw new Error("No includeable chapters found (all locked/filtered)");
  }

  let selected = chapters.slice(Math.max(0, chapterFrom));
  if (chapterTo != null && Number.isFinite(chapterTo)) {
    selected = chapters.slice(Math.max(0, chapterFrom), Math.max(0, chapterTo) + 1);
  }
  if (limit != null && Number.isFinite(limit) && limit > 0) {
    selected = selected.slice(0, limit);
  }
  if (selected.length === 0) throw new Error("Chapter range produced no chapters");

  const throttle = Math.max(delayMs, parser.getRateLimit?.() || parser.minimumThrottle || 500);
  const compiled = [];

  for (let index = 0; index < selected.length; index += 1) {
    const chapter = selected[index];
    if (index > 0) await sleep(throttle);

    const pageParser = chapter.parser || parser;
    if (chapter.parser == null) {
      // Match parserFactory.addParsersToPages behaviour loosely.
      chapter.parser = parser;
    }

    let pageDom;
    try {
      pageDom = await pageParser.fetchChapter(chapter.sourceUrl);
    } catch (err) {
      if (prefs.skipChaptersThatFailFetch.value) {
        console.warn(`Skipping failed chapter ${chapter.sourceUrl}:`, err.message);
        continue;
      }
      throw err;
    }

    pageParser.preprocessRawDom(pageDom);
    const webPage = {
      ...chapter,
      rawDom: pageDom,
      sourceUrl: chapter.sourceUrl,
      title: chapter.title || "[placeholder]",
    };

    let content;
    try {
      content = pageParser.convertRawDomToContent(webPage);
    } catch (err) {
      content = pageParser.findContent(pageDom);
      if (!content) {
        if (prefs.skipChaptersThatFailFetch.value) {
          console.warn(`No content for ${chapter.sourceUrl}:`, err.message);
          continue;
        }
        throw err;
      }
    }

    const title =
      asText(webPage.title) ||
      asText(pageParser.findChapterTitle?.(pageDom)) ||
      `Chapter ${chapterFrom + index + 1}`;

    compiled.push({
      index: chapterFrom + index,
      title,
      sourceUrl: chapter.sourceUrl,
      html: serializeContent(content, ctx),
    });
  }

  if (compiled.length === 0) throw new Error("All chapter fetches failed");

  const title =
    asText(parser.extractTitle?.(firstPageDom)) ||
    asText(parser.extractTitleImpl?.(firstPageDom)) ||
    "Untitled";
  const authors = asText(parser.extractAuthor?.(firstPageDom));
  const synopsis =
    asText(parser.extractDescription?.(firstPageDom)) ||
    asText(firstPageDom.querySelector?.("meta[name='description']")?.getAttribute?.("content"));
  const coverUrl =
    asText(parser.findCoverImageUrl?.(firstPageDom)) || null;
  let subjects = asText(parser.extractSubject?.(firstPageDom));
  if (Array.isArray(subjects)) subjects = subjects.join(", ");

  return {
    adapter: adapterIdFor(parser, url),
    parser: parser.constructor?.name || "Parser",
    title,
    authors,
    synopsis,
    coverUrl,
    subjects,
    sourceUrl: url,
    chapterCount: compiled.length,
    chapters: compiled,
  };
}

export function detectParser(url) {
  const ctx = loadWebToEpubContext();
  const parser = ctx.parserFactory.fetchByUrl(url);
  if (!parser) {
    return { supported: false, adapter: null, parser: null, hosts: listRegisteredHosts().length };
  }
  return {
    supported: true,
    adapter: adapterIdFor(parser, url),
    parser: parser.constructor?.name || "Parser",
    hosts: listRegisteredHosts().length,
  };
}

export { listRegisteredHosts };
