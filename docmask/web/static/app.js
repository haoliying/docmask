(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const els = {
    version: $("versionText"),
    footerVersion: $("footerVersion"),
    dropzone: $("dropzone"),
    fileInput: $("fileInput"),
    dropHint: $("dropHint"),
    fileList: $("fileList"),
    fileMeta: $("fileMeta"),
    clearBtn: $("clearBtn"),
    strategyGrid: $("strategyGrid"),
    strategyNote: $("strategyNote"),
    entityGroups: $("entityGroups"),
    selectAllBtn: $("selectAllBtn"),
    selectNoneBtn: $("selectNoneBtn"),
    customWords: $("customWords"),
    rulesText: $("rulesText"),
    maskChar: $("maskChar"),
    keepLength: $("keepLength"),
    stripMetadata: $("stripMetadata"),
    pdfMode: $("pdfMode"),
    selectionSummary: $("selectionSummary"),
    previewBtn: $("previewBtn"),
    redactBtn: $("redactBtn"),
    status: $("status"),
    previewPanel: $("previewPanel"),
    previewTotal: $("previewTotal"),
    previewBody: $("previewBody"),
    resultPanel: $("resultPanel"),
    resultBody: $("resultBody"),
    resultWarnings: $("resultWarnings"),
    downloadBtn: $("downloadBtn"),
  };

  const state = {
    config: null,
    files: [],
    enabled: new Set(),
    strategy: "mask",
    busy: false,
    entityLabels: new Map(),
  };

  const WORD_TYPE_ALIASES = {
    姓名: "PERSON",
    名字: "PERSON",
    人名: "PERSON",
    公司: "ORG",
    单位: "ORG",
    机构: "ORG",
    地址: "ADDRESS",
    身份证: "CN_ID",
    手机号: "CN_MOBILE",
    邮箱: "EMAIL",
    自定义: "CUSTOM",
  };

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1024 / 1024).toFixed(2) + " MB";
  }

  function setStatus(message, kind) {
    els.status.textContent = "";
    els.status.className = "status" + (kind ? " is-" + kind : "");
    if (!message) return;
    const inner = make("div", "status-inner", message);
    els.status.appendChild(inner);
  }

  function setBusy(busy, which) {
    state.busy = busy;
    if (busy) {
      els.previewBtn.classList.add("is-busy");
      els.redactBtn.classList.add("is-busy");
      if (which === "preview") els.previewBtn.textContent = "识别中…";
      if (which === "redact") {
        els.redactBtn.querySelector("span").textContent = "脱敏中…";
      }
    } else {
      els.previewBtn.classList.remove("is-busy");
      els.redactBtn.classList.remove("is-busy");
      els.previewBtn.textContent = "预览识别";
      els.redactBtn.querySelector("span").textContent = "开始脱敏";
    }
    updateControls();
  }

  function updateControls() {
    const total = state.files.reduce((sum, item) => sum + item.file.size, 0);
    const ready = state.files.length > 0 && state.enabled.size > 0;
    els.previewBtn.disabled = state.busy || !ready;
    els.redactBtn.disabled = state.busy || !ready;
    els.selectionSummary.textContent =
      state.files.length +
      " 个文件 · " +
      state.enabled.size +
      " 类规则 · " +
      formatSize(total);
    els.clearBtn.classList.toggle("hidden", state.files.length === 0);
    els.fileMeta.textContent = state.files.length
      ? "共 " + state.files.length + " 个文件，合计 " + formatSize(total)
      : "";
  }

  // ---------------------------------------------------------------- config
  async function loadConfig() {
    try {
      const res = await fetch("/api/config", { cache: "no-store" });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "配置加载失败");
      state.config = data;
      els.version.textContent = "v" + data.version;
      els.footerVersion.textContent = "v" + data.version;
      const exts = data.extensions.map((ext) => ext.replace(".", "").toUpperCase());
      els.dropHint.textContent = "支持 " + exts.join(" / ");
      data.entities.forEach((entity) => state.entityLabels.set(entity.type, entity.label));
      renderStrategies(data.strategies);
      renderEntities(data.entities);
      updateControls();
    } catch (error) {
      setStatus("无法连接本地服务：" + error.message, "error");
    }
  }

  function renderStrategies(strategies) {
    els.strategyGrid.textContent = "";
    strategies.forEach((item) => {
      const label = make("label", "strategy-option");
      const input = make("input");
      input.type = "radio";
      input.name = "strategy";
      input.value = item.key;
      input.checked = item.key === state.strategy;
      input.addEventListener("change", () => {
        if (input.checked) {
          state.strategy = item.key;
          updateStrategyNote();
        }
      });
      const dot = make("span", "strategy-dot");
      const name = make("span", "strategy-name", item.label);
      const hint = make("span", "strategy-hint", item.hint);
      label.append(input, dot, name, hint);
      els.strategyGrid.appendChild(label);
    });
    updateStrategyNote();
  }

  function updateStrategyNote() {
    if (!state.config) return;
    const item = state.config.strategies.find((entry) => entry.key === state.strategy);
    let note = item ? item.label + "：" + item.hint + "。" : "";
    if (state.strategy === "replace") {
      note += " 输出 ZIP 内会包含 mapping.csv，含原文与占位符对应关系。";
    }
    if (state.strategy === "partial") {
      note += " 保留首尾字符，适合需要人工核对格式的场景。";
    }
    if (state.strategy === "hash") {
      note += " 使用本次运行随机盐，无法从哈希反推原文。";
    }
    els.strategyNote.textContent = note;
  }

  function renderEntities(entities) {
    els.entityGroups.textContent = "";
    const groups = new Map();
    entities.forEach((entity) => {
      if (!groups.has(entity.group)) groups.set(entity.group, []);
      groups.get(entity.group).push(entity);
      if (entity.default) state.enabled.add(entity.type);
    });
    groups.forEach((items, groupName) => {
      const group = make("div", "entity-group");
      group.appendChild(make("div", "entity-group-title", groupName));
      const grid = make("div", "entity-grid");
      items.forEach((entity) => {
        const label = make("label", "entity-option");
        label.title = entity.description || entity.label;
        const input = make("input");
        input.type = "checkbox";
        input.value = entity.type;
        input.checked = state.enabled.has(entity.type);
        input.addEventListener("change", () => {
          if (input.checked) state.enabled.add(entity.type);
          else state.enabled.delete(entity.type);
          updateControls();
        });
        const box = make("span", "entity-box");
        const name = make("span", "entity-name", entity.label);
        label.append(input, box, name);
        grid.appendChild(label);
      });
      group.appendChild(grid);
      els.entityGroups.appendChild(group);
    });
  }

  function setAllEntities(checked) {
    els.entityGroups.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = checked;
      if (checked) state.enabled.add(input.value);
      else state.enabled.delete(input.value);
    });
    updateControls();
  }

  // ----------------------------------------------------------------- files
  function addFiles(fileList) {
    if (!state.config) return;
    const allowed = new Set(state.config.extensions);
    const maxFile = state.config.limits.max_file_mb * 1024 * 1024;
    let rejected = [];
    Array.from(fileList).forEach((file) => {
      const dot = file.name.lastIndexOf(".");
      const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : "";
      if (!allowed.has(ext)) {
        rejected.push(file.name + "（格式不支持）");
        return;
      }
      if (file.size > maxFile) {
        rejected.push(file.name + "（超过 " + state.config.limits.max_file_mb + "MB）");
        return;
      }
      const key = file.name + ":" + file.size + ":" + file.lastModified;
      if (state.files.some((item) => item.key === key)) return;
      state.files.push({
        id: "f" + Math.random().toString(36).slice(2) + Date.now().toString(36),
        key: key,
        file: file,
      });
    });
    renderFiles();
    if (rejected.length) {
      setStatus("已忽略：" + rejected.join("；"), "error");
    } else {
      setStatus("", "");
    }
  }

  function renderFiles() {
    els.fileList.textContent = "";
    state.files.forEach((item) => {
      const li = make("li", "file-item");
      const name = make("span", "file-name", item.file.name);
      const size = make("span", "file-size", formatSize(item.file.size));
      const remove = make("button", "file-remove", "×");
      remove.type = "button";
      remove.title = "移除";
      remove.setAttribute("aria-label", "移除 " + item.file.name);
      remove.addEventListener("click", () => {
        state.files = state.files.filter((entry) => entry.id !== item.id);
        renderFiles();
        if (!state.files.length) setStatus("", "");
      });
      li.append(name, size, remove);
      els.fileList.appendChild(li);
    });
    updateControls();
  }

  function readAsBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result || "");
        const index = result.indexOf(",");
        resolve(index >= 0 ? result.slice(index + 1) : result);
      };
      reader.onerror = () => reject(reader.error || new Error("读取文件失败"));
      reader.readAsDataURL(file);
    });
  }

  async function buildFilePayload() {
    const payload = [];
    for (const item of state.files) {
      try {
        const data = await readAsBase64(item.file);
        payload.push({ name: item.file.name, data: data });
      } catch (error) {
        throw new Error(item.file.name + " 读取失败：" + error.message);
      }
    }
    return payload;
  }

  // --------------------------------------------------------------- options
  function parseCustomWords(text) {
    const words = {};
    text.split(/\r?\n/).forEach((raw) => {
      let line = raw.trim();
      if (!line || line.startsWith("#")) return;
      let type = "CUSTOM";
      let word = line;
      const match = line.match(/^([^:：]{1,20})[:：]\s*(.+)$/);
      if (match) {
        const left = match[1].trim();
        const upper = left.toUpperCase();
        if (WORD_TYPE_ALIASES[left]) {
          type = WORD_TYPE_ALIASES[left];
          word = match[2].trim();
        } else if (/^[A-Za-z0-9_]+$/.test(left)) {
          type = upper;
          word = match[2].trim();
        }
      }
      if (word.length < 2) return;
      if (!words[type]) words[type] = [];
      if (!words[type].includes(word)) words[type].push(word);
    });
    return words;
  }

  function buildOptions() {
    const rulesSource = els.rulesText.value.trim();
    if (rulesSource) {
      try {
        const parsed = JSON.parse(rulesSource);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("根节点必须是 JSON 对象");
        }
      } catch (error) {
        throw new Error("自定义规则 JSON 格式错误：" + error.message);
      }
    }
    return {
      strategy: state.strategy,
      enabled: Array.from(state.enabled),
      custom_words: parseCustomWords(els.customWords.value),
      rules_text: rulesSource,
      mask_char: els.maskChar.value || "*",
      keep_length: els.keepLength.checked,
      strip_metadata: els.stripMetadata.checked,
      pdf_mode: els.pdfMode.value,
    };
  }

  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let data = null;
    try {
      data = await res.json();
    } catch (error) {
      throw new Error("服务返回了无法解析的响应");
    }
    if (!res.ok || !data || data.ok === false) {
      throw new Error((data && data.error) || "请求失败（" + res.status + "）");
    }
    return data;
  }

  // ---------------------------------------------------------------- preview
  async function runPreview() {
    if (state.busy) return;
    let options;
    try {
      options = buildOptions();
    } catch (error) {
      setStatus(error.message, "error");
      return;
    }
    setBusy(true, "preview");
    setStatus("正在本机解析文件并识别敏感信息…", "busy");
    try {
      const files = await buildFilePayload();
      const data = await postJson("/api/preview", { files: files, options: options });
      renderPreview(data);
      setStatus(
        "预览完成：共 " + data.total + " 处命中，仅展示掩码后的片段。",
        "success"
      );
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function entityLabel(type) {
    return state.entityLabels.get(type) || type;
  }

  function renderPreview(data) {
    els.previewTotal.textContent = data.total;
    els.previewBody.textContent = "";
    data.files.forEach((file) => {
      const block = make("div", "preview-file");
      const head = make("div", "preview-file-head");
      head.appendChild(make("span", "preview-file-name", file.source));
      head.appendChild(
        make("span", "preview-file-total", file.error ? "解析失败" : file.total + " 处")
      );
      block.appendChild(head);

      if (file.error) {
        block.appendChild(make("p", "preview-error", file.error));
        els.previewBody.appendChild(block);
        return;
      }

      if (file.counts && Object.keys(file.counts).length) {
        const chips = make("div", "count-chips");
        Object.entries(file.counts)
          .sort((a, b) => b[1] - a[1])
          .forEach(([type, count]) => {
            const chip = make("span", "count-chip");
            chip.appendChild(document.createTextNode(entityLabel(type) + " "));
            chip.appendChild(make("strong", "", count));
            chips.appendChild(chip);
          });
        block.appendChild(chips);
      }

      if (file.items && file.items.length) {
        const list = make("ul", "sample-list");
        file.items.forEach((item) => {
          const row = make("li", "sample-item");
          row.appendChild(make("span", "sample-label", item.label));
          row.appendChild(make("span", "sample-text", item.preview));
          list.appendChild(row);
        });
        block.appendChild(list);
      } else {
        block.appendChild(make("p", "panel-note", "未发现敏感信息"));
      }
      els.previewBody.appendChild(block);
    });
    els.previewPanel.hidden = false;
    els.resultPanel.hidden = true;
    els.previewPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ----------------------------------------------------------------- redact
  async function runRedact() {
    if (state.busy) return;
    let options;
    try {
      options = buildOptions();
    } catch (error) {
      setStatus(error.message, "error");
      return;
    }
    setBusy(true, "redact");
    setStatus("正在脱敏并打包，文件不会离开本机…", "busy");
    try {
      const files = await buildFilePayload();
      const data = await postJson("/api/redact", { files: files, options: options });
      renderResult(data);
      setStatus(
        "脱敏完成：处理 " +
          data.summary.ok +
          "/" +
          data.summary.files +
          " 个文件，命中 " +
          data.summary.total +
          " 处。",
        data.summary.failed ? "error" : "success"
      );
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function renderResult(data) {
    els.resultBody.textContent = "";
    const stats = [
      ["处理文件", data.summary.ok + " / " + data.summary.files],
      ["命中总数", data.summary.total],
      ["失败文件", data.summary.failed],
    ];
    stats.forEach(([label, value]) => {
      const box = make("div", "result-stat");
      box.appendChild(make("strong", "", value));
      box.appendChild(make("span", "", label));
      els.resultBody.appendChild(box);
    });

    const files = make("div", "result-files");
    data.files.forEach((file) => {
      const row = make("div", "result-file");
      row.appendChild(make("span", "", file.source));
      const status = make(
        "span",
        file.status === "ok" ? "ok" : "bad",
        file.status === "ok" ? "已脱敏 · " + Object.values(file.counts || {}).reduce((a, b) => a + b, 0) + " 处" : file.error || "失败"
      );
      row.appendChild(status);
      files.appendChild(row);
    });
    els.resultBody.appendChild(files);

    els.resultWarnings.textContent = "";
    if (data.mapping_included) {
      const warn = make(
        "div",
        "warning is-danger",
        "ZIP 内含 mapping.csv（原文与占位符对应关系），请与脱敏文件分开保管，不要随文件一起外发。"
      );
      els.resultWarnings.appendChild(warn);
    }
    const seen = new Set();
    data.files.forEach((file) => {
      (file.warnings || []).forEach((text) => {
        const line = "[" + file.source + "] " + text;
        if (seen.has(line)) return;
        seen.add(line);
        els.resultWarnings.appendChild(make("div", "warning", line));
      });
    });
    const general =
      "图片、扫描件、批注、图表与嵌入对象中的文字不会被自动识别，请人工复核。";
    if (!seen.has(general)) {
      els.resultWarnings.appendChild(make("div", "warning", general));
    }

    const stamp = new Date()
      .toISOString()
      .slice(0, 19)
      .replace(/[-:T]/g, "")
      .slice(0, 14);
    els.downloadBtn.href = data.download;
    els.downloadBtn.setAttribute("download", "docmask_" + stamp + ".zip");
    els.resultPanel.hidden = false;
    els.previewPanel.hidden = true;
    els.resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ------------------------------------------------------------------ wiring
  function wire() {
    els.dropzone.addEventListener("click", () => els.fileInput.click());
    els.dropzone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        els.fileInput.click();
      }
    });
    ["dragenter", "dragover"].forEach((name) => {
      els.dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        els.dropzone.classList.add("is-over");
      });
    });
    ["dragleave", "drop"].forEach((name) => {
      els.dropzone.addEventListener(name, (event) => {
        event.preventDefault();
        els.dropzone.classList.remove("is-over");
      });
    });
    els.dropzone.addEventListener("drop", (event) => {
      if (event.dataTransfer && event.dataTransfer.files) {
        addFiles(event.dataTransfer.files);
      }
    });
    els.fileInput.addEventListener("change", () => {
      addFiles(els.fileInput.files);
      els.fileInput.value = "";
    });
    els.clearBtn.addEventListener("click", () => {
      state.files = [];
      renderFiles();
      setStatus("", "");
    });
    els.selectAllBtn.addEventListener("click", () => setAllEntities(true));
    els.selectNoneBtn.addEventListener("click", () => setAllEntities(false));
    els.previewBtn.addEventListener("click", runPreview);
    els.redactBtn.addEventListener("click", runRedact);
    els.maskChar.addEventListener("input", () => {
      if (els.maskChar.value.length > 1) {
        els.maskChar.value = els.maskChar.value.slice(0, 1);
      }
    });
  }

  wire();
  loadConfig();
})();
