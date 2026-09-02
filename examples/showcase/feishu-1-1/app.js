const state = { data: null, caseIndex: 0 };
const $ = (selector) => document.querySelector(selector);
const videos = () => [...document.querySelectorAll("video")];

async function loadText(path) {
  if (!path) return "";
  try {
    const response = await fetch(path);
    if (!response.ok) throw new Error(String(response.status));
    return await response.text();
  } catch {
    return "Prompt 读取失败";
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function render() {
  const item = state.data.cases[state.caseIndex];
  const entries = Object.values(item.groups);
  const ready = entries.filter((group) => group.status === "ready").length;

  $("#caseTitle").textContent = item.title;
  $("#caseDescription").textContent = item.description;
  $("#availability").textContent = `${ready}/4 个视频可用`;
  $("#comparison").innerHTML = "";

  for (const group of entries) {
    const card = document.createElement("article");
    card.className = `video-card ${group.prompt ? "has-prompt" : "reference-card"}`;
    const media = group.video
      ? `<video controls muted playsinline preload="metadata" ${$("#loopAll").checked ? "loop" : ""} src="${escapeHtml(group.video)}"></video>`
      : `<div class="missing">尚未生成</div>`;
    const promptPanel = group.prompt
      ? `<details><summary>查看 H3 Prompt</summary><pre>加载中…</pre></details>`
      : `<div class="reference-note">参考输出仅用于效果对照，不包含 H3 Prompt</div>`;

    card.innerHTML = `
      <div class="card-head">
        <div><span class="order">${escapeHtml(group.order)}</span><h3>${escapeHtml(group.label)}</h3></div>
        <span class="badge">${group.status === "ready" ? "已完成" : "缺失"}</span>
      </div>
      ${media}
      ${promptPanel}
    `;
    $("#comparison").appendChild(card);
    if (group.prompt) card.querySelector("pre").textContent = await loadText(group.prompt);
  }
}

async function init() {
  state.data = await fetch("cases.json").then((response) => response.json());
  const select = $("#caseSelect");
  state.data.cases.forEach((item, index) => select.add(new Option(item.title, index)));
  select.addEventListener("change", () => {
    state.caseIndex = Number(select.value);
    render();
  });
  $("#playAll").addEventListener("click", () => videos().forEach((video) => video.play()));
  $("#pauseAll").addEventListener("click", () => videos().forEach((video) => video.pause()));
  $("#restartAll").addEventListener("click", () => videos().forEach((video) => {
    video.currentTime = 0;
    video.play();
  }));
  $("#loopAll").addEventListener("change", (event) => videos().forEach((video) => {
    video.loop = event.target.checked;
  }));
  await render();
}

init();
