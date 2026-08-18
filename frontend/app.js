const state = {
  assets: [],
  counters: { image: 0, video: 0, audio: 0 },
  job: null,
  resultCache: {},
  activeResult: "context_ir.json",
  pollTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const elements = {
  request: $("#userRequest"), requestCount: $("#requestCount"),
  fileInput: $("#fileInput"), dropzone: $("#dropzone"), assetList: $("#assetList"),
  emptyAssets: $("#emptyAssets"), assetCounter: $("#assetCounter"),
  generate: $("#generateButton"), audit: $("#auditBadge"), toast: $("#toast"),
  serviceCluster: $("#serviceCluster"), resultEmpty: $("#resultEmpty"),
  jobProgress: $("#jobProgress"), resultView: $("#resultView"),
  progressTitle: $("#progressTitle"), progressPercent: $("#progressPercent"),
  progressBar: $("#progressBar"), progressSteps: $("#progressSteps"),
  resultContent: $("#resultContent"), resultFilename: $("#resultFilename"),
};

const roles = {
  image: [
    ["product", "商品外观"], ["identity", "人物身份"], ["outfit", "服装造型"],
    ["wearing", "正确佩戴 / 使用方式"], ["scene", "场景与背景"],
    ["style", "视觉风格"], ["first_frame", "首帧"], ["last_frame", "尾帧"],
  ],
  video: [
    ["motion", "动作与表演"], ["transition", "转场与节奏"],
    ["camera", "运镜方式"], ["structure", "镜头结构"], ["style", "视觉风格"],
  ],
  audio: [
    ["music", "音乐参考"], ["voice", "人声 / 音色"], ["rhythm", "节拍与卡点"],
    ["sound_effects", "音效参考"], ["reuse", "直接复用音频"],
  ],
};

function mediaType(file) {
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  if (file.type.startsWith("audio/")) return "audio";
  const ext = file.name.split(".").pop().toLowerCase();
  if (["jpg","jpeg","png","webp","bmp"].includes(ext)) return "image";
  if (["mp4","mov","mkv","webm","avi"].includes(ext)) return "video";
  if (["wav","mp3","m4a","aac","flac","ogg"].includes(ext)) return "audio";
  return null;
}

function labelFor(type, number) {
  return `${{ image: "图片", video: "视频", audio: "音频" }[type]} ${number}`;
}

function toast(message, error = false) {
  elements.toast.textContent = message;
  elements.toast.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => elements.toast.className = "toast", 3200);
}

function addFiles(files) {
  [...files].forEach((file) => {
    const type = mediaType(file);
    if (!type) return toast(`暂不支持 ${file.name}`, true);
    if (file.size > 1024 * 1024 * 1024) return toast(`${file.name} 超过 1 GB`, true);
    state.counters[type] += 1;
    state.assets.push({
      id: crypto.randomUUID(), file, type, number: state.counters[type],
      role: roles[type][0][0], note: "", url: URL.createObjectURL(file),
    });
  });
  renderAssets();
}

function renderAssets() {
  elements.assetList.innerHTML = "";
  elements.emptyAssets.classList.toggle("hidden", state.assets.length > 0);
  elements.assetCounter.textContent = `${state.assets.length} 个素材`;
  state.assets.forEach((asset) => {
    const card = $("#assetTemplate").content.firstElementChild.cloneNode(true);
    card.dataset.id = asset.id;
    card.querySelector(".asset-index").textContent = labelFor(asset.type, asset.number);
    card.querySelector(".asset-filename").textContent = `${asset.file.name} · ${formatBytes(asset.file.size)}`;
    const preview = card.querySelector(".asset-preview");
    if (asset.type === "image") {
      const image = new Image(); image.src = asset.url; image.alt = asset.file.name; preview.append(image);
    } else if (asset.type === "video") {
      const video = document.createElement("video"); video.src = asset.url; video.muted = true; video.preload = "metadata"; preview.append(video);
    } else {
      preview.querySelector("span").textContent = "♪";
    }
    const select = card.querySelector(".asset-role");
    roles[asset.type].forEach(([value, text]) => select.add(new Option(text, value, false, value === asset.role)));
    select.addEventListener("change", () => asset.role = select.value);
    const note = card.querySelector(".asset-note"); note.value = asset.note;
    note.addEventListener("input", () => asset.note = note.value);
    card.querySelector(".remove-asset").addEventListener("click", () => removeAsset(asset.id));
    elements.assetList.append(card);
  });
}

function removeAsset(id) {
  const asset = state.assets.find((item) => item.id === id);
  if (asset) URL.revokeObjectURL(asset.url);
  state.assets = state.assets.filter((item) => item.id !== id);
  renderAssets();
}

function formatBytes(value) {
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

async function healthCheck() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const data = await response.json();
    const services = data.services;
    elements.serviceCluster.innerHTML = [services.vlm, services.glm].map((service) =>
      `<span class="service-pill ${service.ready ? "ready" : "missing"}"><i></i>${escapeHtml(service.label)}</span>`
    ).join("");
    $("#submitHint").textContent = services.ready
      ? "素材会自动保存在新的 case 文件夹"
      : "可创建任务，但需管理员补齐未连接的模型服务";
  } catch {
    elements.serviceCluster.innerHTML = '<span class="service-pill missing"><i></i>后端服务未连接</span>';
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
}

async function generate() {
  const request = elements.request.value.trim();
  const taskType = $("#taskType").value;
  if (!request) return toast("请先描述你想生成的视频", true);
  if (taskType !== "t2va" && !state.assets.length) return toast("请至少上传一个参考素材", true);
  const form = new FormData();
  form.append("user_request", request);
  form.append("task_type", taskType);
  form.append("duration_seconds", $("#duration").value);
  form.append("aspect_ratio", $("#aspectRatio").value);
  form.append("style", $("#style").value);
  form.append("generate_audio", $("#generateAudio").checked ? "true" : "false");
  const metadata = state.assets.map((asset) => ({
    media_type: asset.type,
    role: asset.role,
    label: `${labelFor(asset.type, asset.number)} · ${roles[asset.type].find(([value]) => value === asset.role)?.[1]}${asset.note ? ` · ${asset.note}` : ""}`,
  }));
  form.append("asset_metadata", JSON.stringify(metadata));
  state.assets.forEach((asset) => form.append("files", asset.file, asset.file.name));
  setRunning(true);
  try {
    const response = await fetch("/api/jobs", { method: "POST", body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "任务创建失败");
    state.job = data.job;
    showProgress(
      state.job.progress_label || "素材已上传，正在等待处理",
      state.job.progress_percent ?? 8,
      state.job.progress_stage ?? 0,
    );
    pollJob();
  } catch (error) {
    setRunning(false);
    showFailure(error.message);
  }
}

function setRunning(running) {
  elements.generate.disabled = running;
  elements.generate.querySelector("span").textContent = running ? "正在生成…" : "生成 Context-IR";
  if (running) {
    elements.resultEmpty.classList.add("hidden");
    elements.resultView.classList.add("hidden");
    elements.jobProgress.classList.remove("hidden");
    elements.audit.className = "audit-badge running";
    elements.audit.textContent = "处理中";
  }
}

function showProgress(title, percent, activeStep) {
  elements.progressTitle.textContent = title;
  elements.progressPercent.textContent = `${percent}%`;
  elements.progressBar.style.width = `${percent}%`;
  [...elements.progressSteps.children].forEach((step, index) => {
    step.className = index < activeStep ? "done" : index === activeStep ? "active" : "";
  });
}

async function pollJob() {
  clearTimeout(state.pollTimer);
  try {
    const response = await fetch(`/api/jobs/${state.job.job_id}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "无法读取任务状态");
    state.job = data.job;
    if (["queued", "running"].includes(state.job.status)) {
      showProgress(
        state.job.progress_label || "正在处理 Context-IR",
        state.job.progress_percent ?? 10,
        state.job.progress_stage ?? 0,
      );
    }
    if (state.job.status === "completed") return showCompleted();
    if (state.job.status === "failed") return showFailure(state.job.error || "生成失败");
    state.pollTimer = setTimeout(pollJob, 1400);
  } catch (error) {
    showFailure(error.message);
  }
}

async function showCompleted() {
  setRunning(false);
  showProgress("H3 Prompt 已生成并通过审计", 100, 5);
  elements.jobProgress.classList.add("hidden");
  elements.resultView.classList.remove("hidden");
  elements.audit.className = "audit-badge passed";
  elements.audit.textContent = "审计通过";
  await loadResult("context_ir.json");
  toast(`已生成 ${state.job.case_id}`);
}

function showFailure(message) {
  setRunning(false);
  elements.audit.className = "audit-badge failed";
  elements.audit.textContent = "生成失败";
  elements.jobProgress.classList.add("hidden");
  elements.resultEmpty.classList.remove("hidden");
  elements.resultEmpty.querySelector("h3").textContent = "任务未完成";
  elements.resultEmpty.querySelector("p").textContent = message;
  toast(message, true);
}

async function loadResult(filename) {
  state.activeResult = filename;
  document.querySelectorAll(".result-tabs button").forEach((button) => button.classList.toggle("active", button.dataset.result === filename));
  elements.resultFilename.textContent = filename;
  if (!state.resultCache[filename]) {
    const response = await fetch(`/api/jobs/${state.job.job_id}/files/${filename}`);
    if (!response.ok) throw new Error("结果文件不可用");
    const text = await response.text();
    state.resultCache[filename] = filename.endsWith(".json") ? JSON.stringify(JSON.parse(text), null, 2) : text;
  }
  elements.resultContent.textContent = state.resultCache[filename];
}

elements.request.addEventListener("input", () => elements.requestCount.textContent = `${elements.request.value.length} / 4000`);
elements.dropzone.addEventListener("click", () => elements.fileInput.click());
elements.dropzone.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) elements.fileInput.click(); });
elements.fileInput.addEventListener("change", () => { addFiles(elements.fileInput.files); elements.fileInput.value = ""; });
["dragenter", "dragover"].forEach((type) => elements.dropzone.addEventListener(type, (event) => { event.preventDefault(); elements.dropzone.classList.add("dragover"); }));
["dragleave", "drop"].forEach((type) => elements.dropzone.addEventListener(type, (event) => { event.preventDefault(); elements.dropzone.classList.remove("dragover"); }));
elements.dropzone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
elements.generate.addEventListener("click", generate);
$("#exampleButton").addEventListener("click", () => {
  elements.request.value = "制作一个15秒竖屏高级美甲广告。商品外观严格参考图片1，正确佩戴方式参考图片2，动作、转场和节奏参考视频1。视频开头展示素甲，变装后才出现美甲，美甲展示不少于总时长的60%。必须保持产品颜色、纹理、形状和佩戴方向；生成契合主题的BGM和卡点音效，不生成旁白。";
  elements.request.dispatchEvent(new Event("input"));
});
document.querySelectorAll(".result-tabs button").forEach((button) => button.addEventListener("click", () => loadResult(button.dataset.result).catch((error) => toast(error.message, true))));
$("#copyResult").addEventListener("click", async () => { await navigator.clipboard.writeText(elements.resultContent.textContent); toast("已复制到剪贴板"); });
$("#downloadResult").addEventListener("click", () => {
  const blob = new Blob([elements.resultContent.textContent], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = state.activeResult; link.click(); URL.revokeObjectURL(link.href);
});

healthCheck();
