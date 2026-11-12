(() => {
  const library = document.querySelector("[data-library]");
  const reader = document.getElementById("reader");

  let packedPerRow = 0;

  function packShelves() {
    if (!library) return;

    const books = [...library.querySelectorAll("[data-book]")];
    if (!books.length) return;

    // Measure against a temporary row so width math matches laid-out books
    const probe = document.createElement("div");
    probe.className = "shelf-row";
    probe.innerHTML = '<div class="shelf-books"></div>';
    const probeBooks = probe.querySelector(".shelf-books");
    const sample = books[0].cloneNode(true);
    sample.classList.remove("is-entering");
    probeBooks.appendChild(sample);
    library.appendChild(probe);
    const bookWidth = probeBooks.firstElementChild.getBoundingClientRect().width || 90;
    const styles = getComputedStyle(probeBooks);
    const gap = parseFloat(styles.columnGap || styles.gap) || 8;
    const available = Math.max(probeBooks.clientWidth, library.clientWidth - 8);
    probe.remove();

    const perRow = Math.max(2, Math.floor((available + gap) / (bookWidth + gap)));
    if (library.dataset.packed === "1" && perRow === packedPerRow) return;
    packedPerRow = perRow;

    const fragment = document.createDocumentFragment();
    const animate = library.dataset.packed !== "1";

    for (let index = 0; index < books.length; index += perRow) {
      const chunk = books.slice(index, index + perRow);
      const row = document.createElement("div");
      row.className = "shelf-row";
      row.style.setProperty("--row", String(Math.floor(index / perRow)));

      const shelfBooks = document.createElement("div");
      shelfBooks.className = "shelf-books";
      chunk.forEach((book, bookIndex) => {
        if (animate) {
          book.style.setProperty("--delay", `${Math.floor(index / perRow) * 45 + bookIndex * 28}ms`);
          book.classList.add("is-entering");
        } else {
          book.classList.remove("is-entering");
          book.style.removeProperty("--delay");
        }
        shelfBooks.appendChild(book);
      });

      const plank = document.createElement("div");
      plank.className = "shelf-plank";
      plank.setAttribute("aria-hidden", "true");

      const shadow = document.createElement("div");
      shadow.className = "shelf-shadow";
      shadow.setAttribute("aria-hidden", "true");

      row.append(shelfBooks, plank, shadow);
      fragment.appendChild(row);
    }

    library.replaceChildren(fragment);
    library.dataset.packed = "1";
  }

  let packTimer = 0;
  function schedulePack() {
    window.clearTimeout(packTimer);
    packTimer = window.setTimeout(packShelves, 80);
  }

  if (library) {
    packShelves();
    window.addEventListener("resize", schedulePack);
    if ("ResizeObserver" in window) {
      new ResizeObserver(schedulePack).observe(library);
    }
  }

  if (!reader) return;

  const stage = reader.querySelector(".reader-stage");
  const coverImg = reader.querySelector("[data-reader-cover]");
  const coverFallback = reader.querySelector("[data-reader-fallback]");
  const titleEl = reader.querySelector("[data-reader-title]");
  const authorEl = reader.querySelector("[data-reader-author]");
  const statusSelect = reader.querySelector("[data-reader-status-select]");
  const statusNote = reader.querySelector("[data-reader-status-note]");
  const metaEl = reader.querySelector("[data-reader-meta]");
  const tagsEl = reader.querySelector("[data-reader-tags]");
  const synopsisEl = reader.querySelector("[data-reader-synopsis]");
  const listedEl = reader.querySelector("[data-reader-listed]");
  const deleteForm = reader.querySelector("[data-reader-delete]");
  const reenrichForm = reader.querySelector("[data-reader-reenrich]");
  const fixTitleInput = reader.querySelector("[data-reader-fix-title]");
  const reenrichNote = reader.querySelector("[data-reader-reenrich-note]");
  const reenrichSubmit = reader.querySelector("[data-reader-reenrich-submit]");
  const closeButtons = reader.querySelectorAll("[data-reader-close]");
  const llmReady = reader.dataset.llmReady === "1";

  let activeBook = null;
  let activeBookId = null;
  let opening = false;
  let reenriching = false;
  let savingStatus = false;
  let currentStatus = "";

  function parseBook(button) {
    return {
      id: button.dataset.id,
      title: button.dataset.title || "",
      rawTitle: button.dataset.rawTitle || "",
      authors: button.dataset.authors || "",
      status: button.dataset.status || "",
      statusLabel: button.dataset.statusLabel || "",
      coverUrl: button.dataset.coverUrl || "",
      subjects: button.dataset.subjects || "",
      synopsis: button.dataset.synopsis || "",
      year: button.dataset.year || "",
      pages: button.dataset.pages || "",
      needsReview: button.dataset.needsReview === "1",
      metadataSource: button.dataset.metadataSource || "",
    };
  }

  function bookFromApi(data) {
    const labels = {
      reading: "Reading",
      want_to_read: "Want to read",
      not_finished: "Not finished",
      read: "Read",
      dropped: "Dropped",
      other: "Other",
    };
    return {
      id: String(data.id),
      title: data.title || data.raw_title || "",
      rawTitle: data.raw_title || "",
      authors: data.authors || "",
      status: data.status || "",
      statusLabel: labels[data.status] || (data.status || "").split("_").join(" "),
      coverUrl: data.cover_url || "",
      subjects: data.subjects || "",
      synopsis: data.synopsis || "",
      year: data.first_publish_year ? String(data.first_publish_year) : "",
      pages: data.page_count ? String(data.page_count) : "",
      needsReview: Boolean(data.needs_review),
      metadataSource: data.metadata_source || "",
    };
  }

  function fillReader(book) {
    titleEl.textContent = book.title || book.rawTitle;
    authorEl.textContent = book.authors || "Author unknown";
    currentStatus = book.status || "";
    if (statusSelect) {
      statusSelect.value = currentStatus;
      statusSelect.className = `status-select status-${currentStatus}`;
    }
    if (statusNote) {
      statusNote.hidden = true;
      statusNote.textContent = "";
    }

    if (book.coverUrl) {
      coverImg.hidden = false;
      coverFallback.hidden = true;
      coverImg.src = book.coverUrl;
      coverImg.alt = `Cover for ${book.title || book.rawTitle}`;
    } else {
      coverImg.hidden = true;
      coverFallback.hidden = false;
      coverFallback.textContent = (book.title || book.rawTitle || "?").slice(0, 1);
    }

    if (book.rawTitle && book.title && book.rawTitle !== book.title) {
      listedEl.hidden = false;
      listedEl.textContent = `Listed as: ${book.rawTitle}`;
    } else {
      listedEl.hidden = true;
      listedEl.textContent = "";
    }

    const metaBits = [];
    if (book.year) metaBits.push(`<div><dt>Published</dt><dd>${book.year}</dd></div>`);
    if (book.pages) metaBits.push(`<div><dt>Pages</dt><dd>${book.pages}</dd></div>`);
    if (book.metadataSource) {
      metaBits.push(`<div><dt>Source</dt><dd>${escapeHtml(book.metadataSource)}</dd></div>`);
    }
    if (book.needsReview) metaBits.push(`<div><dt>Review</dt><dd>needs check</dd></div>`);
    metaEl.innerHTML = metaBits.join("");
    metaEl.hidden = metaBits.length === 0;

    if (book.subjects) {
      tagsEl.hidden = false;
      tagsEl.innerHTML = `<h3>Tags</h3><p>${escapeHtml(book.subjects)}</p>`;
    } else {
      tagsEl.hidden = true;
      tagsEl.innerHTML = "";
    }

    if (book.synopsis) {
      synopsisEl.hidden = false;
      synopsisEl.innerHTML = `<h3>Synopsis</h3><p>${escapeHtml(book.synopsis)}</p>`;
    } else {
      synopsisEl.hidden = true;
      synopsisEl.innerHTML = "";
    }

    if (fixTitleInput) {
      fixTitleInput.value = book.rawTitle || book.title || "";
    }
    if (reenrichNote) {
      reenrichNote.hidden = true;
      reenrichNote.textContent = "";
    }

    deleteForm.action = `/books/${book.id}/delete`;
    activeBookId = book.id;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function openReader(button) {
    if (opening) return;
    opening = true;
    activeBook = button;
    const book = parseBook(button);
    fillReader(book);

    const rect = button.getBoundingClientRect();
    stage.style.setProperty("--origin-x", `${rect.left + rect.width / 2}px`);
    stage.style.setProperty("--origin-y", `${rect.top + rect.height / 2}px`);

    button.classList.add("is-pulled");
    reader.hidden = false;
    document.body.classList.add("reader-open");

    requestAnimationFrame(() => {
      reader.classList.add("is-open");
      stage.classList.add("is-open");
    });

    window.setTimeout(() => {
      opening = false;
    }, 520);

    enrichFromApi(book.id);
  }

  async function enrichFromApi(id) {
    try {
      const response = await fetch(`/api/books/${id}`);
      if (!response.ok) return;
      const data = await response.json();
      fillReader(bookFromApi(data));
    } catch (_) {
      // Keep the shelf data already shown.
    }
  }

  function syncShelfButton(book) {
    if (!activeBook) return;
    activeBook.dataset.title = book.title || book.rawTitle;
    activeBook.dataset.rawTitle = book.rawTitle;
    activeBook.dataset.authors = book.authors || "";
    activeBook.dataset.status = book.status || "";
    activeBook.dataset.statusLabel = book.statusLabel || "";
    activeBook.dataset.coverUrl = book.coverUrl || "";
    activeBook.dataset.subjects = book.subjects || "";
    activeBook.dataset.synopsis = book.synopsis || "";
    activeBook.dataset.year = book.year || "";
    activeBook.dataset.pages = book.pages || "";
    activeBook.dataset.needsReview = book.needsReview ? "1" : "0";
    activeBook.dataset.metadataSource = book.metadataSource || "";
    activeBook.setAttribute("aria-label", `Open ${book.title || book.rawTitle}`);

    const mark = activeBook.querySelector(".book-mark");
    if (book.needsReview && !mark) {
      const span = document.createElement("span");
      span.className = "book-mark";
      span.title = "Needs review";
      activeBook.appendChild(span);
    } else if (!book.needsReview && mark) {
      mark.remove();
    }

    const img = activeBook.querySelector(".book-face img");
    const spine = activeBook.querySelector(".spine-label");
    if (book.coverUrl) {
      activeBook.classList.add("has-cover");
      activeBook.classList.remove("spine-only");
      if (img) {
        img.src = book.coverUrl;
      } else if (spine) {
        spine.remove();
        const next = document.createElement("img");
        next.src = book.coverUrl;
        next.alt = "";
        next.loading = "lazy";
        activeBook.querySelector(".book-face").appendChild(next);
      }
    }
  }

  async function saveStatus(nextStatus) {
    if (!activeBookId || savingStatus || !nextStatus || nextStatus === currentStatus) return;

    savingStatus = true;
    if (statusSelect) statusSelect.disabled = true;
    if (statusNote) {
      statusNote.hidden = false;
      statusNote.textContent = "Saving…";
    }

    try {
      const response = await fetch(`/api/books/${activeBookId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Could not update status");
      }
      const book = bookFromApi(await response.json());
      fillReader(book);
      syncShelfButton(book);
      if (statusNote) {
        statusNote.hidden = false;
        statusNote.textContent = `Moved to ${book.statusLabel}.`;
      }
    } catch (err) {
      if (statusSelect) statusSelect.value = currentStatus;
      if (statusNote) {
        statusNote.hidden = false;
        statusNote.textContent = err.message || "Could not update status";
      }
    } finally {
      savingStatus = false;
      if (statusSelect) statusSelect.disabled = false;
    }
  }

  async function submitReenrich(event) {
    event.preventDefault();
    if (!activeBookId || reenriching) return;

    const title = (fixTitleInput?.value || "").trim();
    if (!title) {
      if (reenrichNote) {
        reenrichNote.hidden = false;
        reenrichNote.textContent = "Enter a title first.";
      }
      return;
    }

    reenriching = true;
    if (reenrichSubmit) {
      reenrichSubmit.disabled = true;
      reenrichSubmit.textContent = llmReady ? "Asking AI…" : "Rechecking…";
    }
    if (reenrichNote) {
      reenrichNote.hidden = false;
      reenrichNote.textContent = "Looking up metadata…";
    }

    try {
      const response = await fetch(`/api/books/${activeBookId}/reenrich`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, use_llm: llmReady }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Recheck failed");
      }
      const data = await response.json();
      const book = bookFromApi(data);
      fillReader(book);
      syncShelfButton(book);
      if (reenrichNote) {
        reenrichNote.hidden = false;
        const source = book.metadataSource || "none";
        reenrichNote.textContent = book.needsReview
          ? `Updated from ${source} — still needs a look.`
          : `Updated from ${source}.`;
      }
    } catch (err) {
      if (reenrichNote) {
        reenrichNote.hidden = false;
        reenrichNote.textContent = err.message || "Recheck failed";
      }
    } finally {
      reenriching = false;
      if (reenrichSubmit) {
        reenrichSubmit.disabled = false;
        const serverLabel = reenrichSubmit.getAttribute("data-default-label");
        reenrichSubmit.textContent = serverLabel || (llmReady ? "Recheck with gemini" : "Recheck metadata");
      }
    }
  }

  function closeReader() {
    if (!reader.classList.contains("is-open")) return;
    reader.classList.remove("is-open");
    stage.classList.remove("is-open");
    document.body.classList.remove("reader-open");
    if (activeBook) activeBook.classList.remove("is-pulled");

    window.setTimeout(() => {
      reader.hidden = true;
      activeBook = null;
      activeBookId = null;
    }, 380);
  }

  // Event delegation survives shelf reflows
  document.addEventListener("click", (event) => {
    const book = event.target.closest("[data-book]");
    if (book && library && library.contains(book)) {
      openReader(book);
    }
  });

  closeButtons.forEach((button) => {
    button.addEventListener("click", closeReader);
  });

  if (reenrichForm) {
    if (reenrichSubmit) {
      reenrichSubmit.setAttribute("data-default-label", reenrichSubmit.textContent.trim());
    }
    reenrichForm.addEventListener("submit", submitReenrich);
  }

  if (statusSelect) {
    statusSelect.addEventListener("change", () => {
      saveStatus(statusSelect.value);
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeReader();
  });
})();
