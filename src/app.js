(() => {
  "use strict";

  const state = {
    books: [],
    currentBook: null,
    activeJobs: new Map(),
    pollTimer: null,
    settings: null,
    renameBookId: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const libraryView = $("#libraryView");
  const bookView = $("#bookView");
  const bookGrid = $("#bookGrid");
  const emptyState = $("#emptyState");
  const dropZone = $("#dropZone");
  const fileInput = $("#fileInput");
  const dropOverlay = $("#dropOverlay");
  const bookHeader = $("#bookHeader");
  const chapterList = $("#chapterList");
  const settingsModal = $("#settingsModal");
  const modelBadge = $("#modelBadge");

  /* ---------------- Tauri IPC ---------------- */

  async function invoke(cmd, args = {}) {
    const tauri = window.__TAURI__;
    if (!tauri || !tauri.core || !tauri.core.invoke) {
      throw new Error("当前不在 Tauri 桌面环境中");
    }
    try {
      return await tauri.core.invoke(cmd, args);
    } catch (err) {
      if (typeof err === "string") throw new Error(err);
      throw new Error((err && err.message) || String(err));
    }
  }

  async function api(cmd, args = {}) {
    return invoke(cmd, args);
  }

  /* ---------------- Toast ---------------- */

  function showToast(message, type = "info", timeout = 3200) {
    const container = $("#toastContainer");
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.remove(), timeout);
  }

  /* ---------------- Library ---------------- */

  const palettes = [
    "linear-gradient(135deg, #2d4a7a, #6b3f8f)",
    "linear-gradient(135deg, #1f5f5b, #2e7d6e)",
    "linear-gradient(135deg, #7a2d3d, #b05c6e)",
    "linear-gradient(135deg, #3f2d7a, #7a4fbf)",
    "linear-gradient(135deg, #5b4a1f, #a0802e)",
    "linear-gradient(135deg, #1f3f7a, #3f8fbf)",
    "linear-gradient(135deg, #4a2d5b, #8a4f9f)",
    "linear-gradient(135deg, #243b53, #49758f)",
  ];

  function paletteFor(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
      h = (h * 31 + str.charCodeAt(i)) >>> 0;
    }
    return palettes[h % palettes.length];
  }

  async function loadBooks() {
    state.books = await api("list_books");
    renderLibrary();
  }

  function renderLibrary() {
    bookGrid.innerHTML = "";
    emptyState.classList.toggle("hidden", state.books.length > 0);
    bookGrid.classList.toggle("hidden", state.books.length === 0);

    for (const book of state.books) {
      const total = Number(book.chapter_count || 0);
      const done = Number(book.done_count || 0);
      const pct = total ? Math.round((done / total) * 100) : 0;

      const card = document.createElement("div");
      card.className = "book-card";
      card.innerHTML = `
        <div class="book-cover" style="background:${paletteFor(book.title)}">
          <div class="book-cover-spine"></div>
          <div class="book-cover-ornament">书</div>
          <div class="cover-title">${escapeHtml(book.title)}</div>
        </div>
        <div class="book-body">
          <div class="book-meta">
            <span>${total} 章</span>
            <span>${done}/${total} 笔记</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" style="width:${pct}%"></div>
          </div>
          <div class="book-card-actions">
            <button class="btn btn-mini" data-action="rename">重命名</button>
            <button class="btn btn-mini btn-danger" data-action="delete">删除</button>
          </div>
        </div>
      `;
      card.addEventListener("click", () => openBook(book.id));
      card.querySelector('[data-action="rename"]').addEventListener("click", (e) => {
        e.stopPropagation();
        openRenameModal(book);
      });
      card.querySelector('[data-action="delete"]').addEventListener("click", (e) => {
        e.stopPropagation();
        deleteBook(book);
      });
      bookGrid.appendChild(card);
    }
  }

  /* ---------------- Book detail ---------------- */

  async function openBook(bookId, silent = false) {
    const book = await api("get_book", { bookId });
    state.currentBook = book;
    renderBook();
    if (!silent) {
      libraryView.classList.add("hidden");
      bookView.classList.remove("hidden");
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function renderBook() {
    const book = state.currentBook;
    if (!book) return;

    const total = Number(book.chapter_count || 0);
    const done = Number(book.done_count || 0);
    const errors = Number(book.error_count || 0);
    const pct = total ? Math.round((done / total) * 100) : 0;

    bookHeader.innerHTML = `
      <div class="book-header-cover" style="background:${paletteFor(book.title)}">
        <div class="book-cover-spine"></div>
        <div class="book-cover-ornament">书</div>
        <div class="cover-title">${escapeHtml(book.title)}</div>
      </div>
      <div class="book-header-info">
        <h1>${escapeHtml(book.title)}</h1>
        <div class="book-stats">
          <span class="stat-chip"><strong>${total}</strong> 章</span>
          <span class="stat-chip"><strong>${done}</strong> 已完成</span>
          <span class="stat-chip"><strong>${errors}</strong> 失败</span>
          <span class="stat-chip"><strong>${pct}%</strong> 进度</span>
        </div>
        <div class="progress-track" style="margin-top:16px;max-width:420px">
          <div class="progress-fill" style="width:${pct}%"></div>
        </div>
        <div class="book-header-actions">
          <button class="btn btn-ghost" id="renameBookBtn">✎ 重命名</button>
          <button class="btn btn-ghost btn-danger" id="deleteBookBtn">删除书籍</button>
        </div>
      </div>
    `;

    const renameBtn = document.getElementById("renameBookBtn");
    const deleteBtn = document.getElementById("deleteBookBtn");
    if (renameBtn) renameBtn.addEventListener("click", () => openRenameModal(book));
    if (deleteBtn) deleteBtn.addEventListener("click", () => deleteBook(book));

    chapterList.innerHTML = "";
    for (const ch of book.chapters || []) {
      chapterList.appendChild(renderChapterCard(ch));
    }
  }

  function renderChapterCard(ch) {
    const card = document.createElement("div");
    card.className = `chapter-card ${ch.status === "running" ? "running" : ""} ${ch.status === "error" ? "error" : ""}`;
    card.dataset.chapterId = ch.id;

    const statusText = {
      pending: "待生成",
      running: "生成中",
      done: "已完成",
      error: "失败",
    }[ch.status] || ch.status;

    const btnLabel = ch.status === "done" ? "重新生成" : "生成笔记";
    const isRunning = Array.from(state.activeJobs.values()).some((v) => v.chapterId === ch.id) || ch.status === "running";

    card.innerHTML = `
      <div class="chapter-row">
        <div class="chapter-index">${ch.idx}</div>
        <div class="chapter-info">
          <div class="chapter-title">${escapeHtml(ch.title)}</div>
          <div class="chapter-meta">${Number(ch.char_count || 0).toLocaleString()} 字符</div>
        </div>
        <span class="chapter-status status-${escapeHtml(ch.status)}">${statusText}</span>
        <button class="btn btn-primary chapter-generate" data-chapter-id="${escapeHtml(ch.id)}" ${isRunning ? "disabled" : ""}>
          ${isRunning ? "生成中…" : btnLabel}
        </button>
      </div>
    `;

    if (ch.status === "error" && ch.error) {
      const err = document.createElement("div");
      err.className = "chapter-error";
      err.textContent = ch.error;
      card.appendChild(err);
    }

    if (ch.note && ch.status === "done") {
      const note = document.createElement("div");
      note.className = "chapter-note";
      note.innerHTML = renderMarkdown(ch.note);
      card.appendChild(note);
    }

    card.querySelector(".chapter-generate").addEventListener("click", (e) => {
      e.stopPropagation();
      generateChapter(ch.id, e.currentTarget);
    });

    return card;
  }

  /* ---------------- Generation ---------------- */

  async function generateChapter(chapterId, btn) {
    const bookId = state.currentBook.id;
    btn.disabled = true;
    btn.textContent = "排队中…";
    try {
      const jobId = await api("generate_chapter", { bookId, chapterId });
      state.activeJobs.set(jobId, { bookId, chapterId });
      schedulePolling();
      updateChapterCardRunning(chapterId);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "生成笔记";
      showToast(err.message, "error");
    }
  }

  async function generateAll() {
    const bookId = state.currentBook.id;
    const btn = $("#generateAllBtn");
    btn.disabled = true;
    btn.textContent = "正在创建任务…";
    try {
      const jobs = await api("generate_all", { bookId });
      for (const job of jobs || []) {
        state.activeJobs.set(job.id, { bookId, chapterId: job.chapter_id });
      }
      if (jobs && jobs.length) {
        schedulePolling();
        await refreshCurrentBook();
        showToast(`已创建 ${jobs.length} 个生成任务`, "success");
      } else {
        showToast("没有需要生成的章节", "info");
      }
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ 生成全部笔记";
    }
  }

  function updateChapterCardRunning(chapterId) {
    const card = document.querySelector(`.chapter-card[data-chapter-id="${CSS.escape(chapterId)}"]`);
    if (!card) return;
    const status = card.querySelector(".chapter-status");
    const btn = card.querySelector(".chapter-generate");
    if (status) {
      status.className = "chapter-status status-running";
      status.textContent = "生成中";
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = "生成中…";
    }
    card.classList.add("running");
  }

  /* ---------------- Polling ---------------- */

  function schedulePolling() {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(pollJobs, 1500);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function pollJobs() {
    let active = [];
    try {
      active = await api("list_jobs");
    } catch (_) {
      return;
    }

    const activeIds = new Set(active.map((j) => j.id));
    let changed = false;

    for (const id of Array.from(state.activeJobs.keys())) {
      if (!activeIds.has(id)) {
        state.activeJobs.delete(id);
        changed = true;
      }
    }

    for (const job of active) {
      if (!state.activeJobs.has(job.id)) {
        state.activeJobs.set(job.id, {
          bookId: job.book_id,
          chapterId: job.chapter_id,
        });
      }
      if (job.status === "error") {
        state.activeJobs.delete(job.id);
        showToast(`《${job.chapter_title}》生成失败：${job.error || ""}`, "error", 5000);
        changed = true;
      } else if (job.status === "running" || job.status === "queued") {
        updateChapterCardRunning(job.chapter_id);
      }
    }

    if (changed) {
      if (state.currentBook) await refreshCurrentBook();
    }

    if (state.activeJobs.size === 0) {
      stopPolling();
    }
  }

  async function refreshCurrentBook() {
    if (!state.currentBook) return;
    const book = await api("get_book", { bookId: state.currentBook.id });
    state.currentBook = book;
    renderBook();
  }

  /* ---------------- Book management ---------------- */

  function openRenameModal(book) {
    state.renameBookId = book.id;
    $("#renameTitle").value = book.title || "";
    $("#renameAuthor").value = book.author || "";
    $("#renameModal").classList.remove("hidden");
  }

  function closeRenameModal() {
    state.renameBookId = null;
    $("#renameModal").classList.add("hidden");
  }

  async function saveRename() {
    if (!state.renameBookId) return;
    const bookId = state.renameBookId;
    const title = $("#renameTitle").value.trim();
    if (!title) {
      showToast("书名不能为空", "error");
      return;
    }
    const author = $("#renameAuthor").value.trim();
    try {
      const updated = await api("update_book", { bookId, title, author });
      closeRenameModal();
      if (state.currentBook && state.currentBook.id === bookId) {
        state.currentBook = updated;
        renderBook();
      }
      await loadBooks();
      showToast("书籍信息已更新", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function deleteBook(book) {
    const ok = window.confirm(`确定删除《${book.title}》吗？\n删除后无法恢复。`);
    if (!ok) return;
    try {
      await api("delete_book", { bookId: book.id });
      if (state.currentBook && state.currentBook.id === book.id) {
        state.currentBook = null;
        bookView.classList.add("hidden");
        libraryView.classList.remove("hidden");
      }
      await loadBooks();
      showToast(`已删除《${book.title}》`, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  /* ---------------- Import ---------------- */

  async function importPath(path) {
    if (!path) return;
    showToast("正在导入并切分章节…", "info");
    try {
      const book = await api("import_path", { path });
      await loadBooks();
      await openBook(book.id);
      showToast(`已导入《${book.title}》，共 ${book.chapter_count} 章`, "success");
    } catch (err) {
      showToast(err.message, "error", 5000);
    }
  }

  async function pickAndImport() {
    try {
      const path = await api("pick_file");
      if (path) await importPath(path);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  /* ---------------- Markdown (minimal, safe) ---------------- */

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function inlineMarkdown(text) {
    let out = escapeHtml(text);
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    return out;
  }

  function parseTableRow(row) {
    let line = row.trim();
    if (line.startsWith("|")) line = line.slice(1);
    if (line.endsWith("|")) line = line.slice(0, -1);
    return line.split("|").map((cell) => cell.trim());
  }

  function renderTable(rows) {
    if (!rows.length) return "";
    const header = parseTableRow(rows[0]);
    let html = `<div class="markdown-table-wrap"><table><thead><tr>`;
    for (const cell of header) {
      html += `<th>${inlineMarkdown(cell)}</th>`;
    }
    html += `</tr></thead><tbody>`;
    for (let r = 1; r < rows.length; r++) {
      const cells = parseTableRow(rows[r]);
      // 跳过 Markdown 分隔行 |---|---|
      if (r === 1 && cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;
      html += `<tr>${cells.map((c) => `<td>${inlineMarkdown(c)}</td>`).join("")}</tr>`;
    }
    html += `</tbody></table></div>`;
    return html;
  }

  function renderMarkdown(md) {
    const lines = String(md || "").split(/\r?\n/);
    let html = "";
    let inList = false;
    let listType = null;

    const closeList = () => {
      if (inList) {
        html += listType === "ol" ? "</ol>" : "</ul>";
        inList = false;
        listType = null;
      }
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (!line) {
        closeList();
        continue;
      }

      if (line.startsWith("|")) {
        closeList();
        const tableRows = [line];
        while (i + 1 < lines.length && lines[i + 1].trim().startsWith("|")) {
          i++;
          tableRows.push(lines[i].trim());
        }
        html += renderTable(tableRows);
        continue;
      }

      if (/^###\s+/.test(line)) {
        closeList();
        html += `<h4>${inlineMarkdown(line.replace(/^###\s+/, ""))}</h4>`;
      } else if (/^##\s+/.test(line)) {
        closeList();
        html += `<h3>${inlineMarkdown(line.replace(/^##\s+/, ""))}</h3>`;
      } else if (/^#\s+/.test(line)) {
        closeList();
        html += `<h2>${inlineMarkdown(line.replace(/^#\s+/, ""))}</h2>`;
      } else if (/^>\s?/.test(line)) {
        closeList();
        html += `<blockquote>${inlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>`;
      } else if (/^\s*[-*_]\s*[-*_\s]*[-*_]\s*$/.test(line)) {
        closeList();
        html += "<hr />";
      } else if (/^[-*]\s+/.test(line)) {
        if (!inList || listType !== "ul") {
          closeList();
          html += "<ul>";
          inList = true;
          listType = "ul";
        }
        html += `<li>${inlineMarkdown(line.replace(/^[-*]\s+/, ""))}</li>`;
      } else if (/^\d+\.\s+/.test(line)) {
        if (!inList || listType !== "ol") {
          closeList();
          html += "<ol>";
          inList = true;
          listType = "ol";
        }
        html += `<li>${inlineMarkdown(line.replace(/^\d+\.\s+/, ""))}</li>`;
      } else {
        closeList();
        html += `<p>${inlineMarkdown(line)}</p>`;
      }
    }
    closeList();
    return html;
  }


  /* ---------------- Settings ---------------- */

  async function openSettings() {
    try {
      const settings = await api("get_settings");
      state.settings = settings;
      $("#settingModel").value = settings.model || "agnes";
      $("#settingBaseUrl").value = settings.base_url || "";
      $("#settingApiKey").value = settings.api_key || "";
      $("#settingTemperature").value = settings.temperature ?? 0.3;
      $("#settingMaxTokens").value = settings.max_tokens ?? 2000;
      $("#settingMaxChunkChars").value = settings.max_chunk_chars ?? 6000;
      $("#settingWorkers").value = settings.workers ?? 1;
      settingsModal.classList.remove("hidden");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function closeSettings() {
    settingsModal.classList.add("hidden");
  }

  async function saveSettings() {
    const payload = {
      model: $("#settingModel").value.trim() || "agnes",
      base_url: $("#settingBaseUrl").value.trim(),
      api_key: $("#settingApiKey").value.trim(),
      temperature: parseFloat($("#settingTemperature").value) || 0.3,
      max_tokens: parseInt($("#settingMaxTokens").value, 10) || 2000,
      max_chunk_chars: parseInt($("#settingMaxChunkChars").value, 10) || 6000,
      workers: parseInt($("#settingWorkers").value, 10) || 1,
      timeout: (state.settings && state.settings.timeout) ?? 120,
      max_retries: (state.settings && state.settings.max_retries) ?? 5,
      chunk_overlap: (state.settings && state.settings.chunk_overlap) ?? 200,
    };
    try {
      const settings = await api("save_settings", { settings: payload });
      modelBadge.textContent = settings.model || "agnes";
      closeSettings();
      showToast("模型设置已保存", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  /* ---------------- Events ---------------- */

  $("#settingsBtn").addEventListener("click", openSettings);
  $("#saveSettingsBtn").addEventListener("click", saveSettings);
  $$("[data-close-settings]").forEach((btn) => btn.addEventListener("click", closeSettings));
  $("#saveRenameBtn").addEventListener("click", saveRename);
  $$("[data-close-rename]").forEach((btn) => btn.addEventListener("click", closeRenameModal));
  $("#backBtn").addEventListener("click", () => {
    bookView.classList.add("hidden");
    libraryView.classList.remove("hidden");
    loadBooks();
  });
  $("#generateAllBtn").addEventListener("click", generateAll);

  dropZone.addEventListener("click", pickAndImport);

  // 原生拖拽事件由 Rust 侧监听并通过 app://drag-drop 转发真实路径。
  const tauri = window.__TAURI__;
  if (tauri && tauri.event) {
    tauri.event.listen("app://drag-drop", (event) => {
      const paths = event.payload && event.payload.paths;
      if (paths && paths.length) importPath(paths[0]);
    });
  }

  /* ---------------- Init ---------------- */

  loadBooks().catch((err) => showToast(err.message, "error"));
  api("get_settings")
    .then((settings) => { modelBadge.textContent = settings.model || "agnes"; })
    .catch(() => {});
})();
