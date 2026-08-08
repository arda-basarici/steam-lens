// The live narration surface: EventSource over the job's SSE stream, the
// stage checklist filling as the pipeline narrates, and the hand-off to the
// published report on the end frame. Reconnects replay the whole history by
// design (the server's ruled behavior), so onopen resets all state and the
// replay rebuilds it — idempotent by construction. All narration text lands
// via textContent; messages quote review content and are hostile input.

const STAGES = [
  ["serve.job", "queue"],
  ["serve.resolve", "resolve the game"],
  ["serve.plan", "plan the sample"],
  ["serve.fetch", "fetch reviews"],
  ["serve.classify", "classify"],
  ["serve.detect", "episode markers"],
  ["serve.runner", "labels banked"],
  ["serve.mint", "mint the numbers"],
  ["serve.compose", "compose the narrative"],
  ["serve.report", "publish"],
];

const appId = document.querySelector(".live").dataset.appId;
const stageList = document.getElementById("live-stages");
const statusLine = document.getElementById("live-status");
const log = document.getElementById("live-log");

// Honest time-awareness: elapsed since the page opened (the requester lands
// here the moment the job queues), never a predicted remainder — there is no
// calibrated timing model to mint one from.
const elapsedLine = document.getElementById("live-elapsed");
const openedAt = Date.now();
setInterval(() => {
  const seconds = Math.floor((Date.now() - openedAt) / 1000);
  const minutes = Math.floor(seconds / 60);
  elapsedLine.textContent =
    `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}, 1000);

const rows = new Map();
for (const [stage, label] of STAGES) {
  const item = document.createElement("li");
  item.className = "stage-row stage-pending";
  const name = document.createElement("span");
  name.className = "stage-name";
  name.textContent = label;
  const message = document.createElement("span");
  message.className = "stage-message";
  item.append(name, message);
  stageList.append(item);
  rows.set(stage, { item, message });
}

function reset() {
  statusLine.hidden = true;
  log.replaceChildren();
  for (const { item, message } of rows.values()) {
    item.className = "stage-row stage-pending";
    message.textContent = "";
  }
}

function onStage(payload) {
  const row = rows.get(payload.stage);
  if (row) {
    row.message.textContent = payload.message;
    if (payload.kind === "done") row.item.className = "stage-row stage-done";
    else if (payload.kind === "warn") row.item.className = "stage-row stage-warn";
    else row.item.className = "stage-row stage-active";
  }
  const line = document.createElement("li");
  line.textContent = `${payload.stage} ${payload.kind}: ${payload.message}`;
  // Stick to the newest line unless the reader has scrolled up to study
  // history — a pinned tail that fights manual scrolling reads as broken.
  const pinned =
    log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.append(line);
  if (pinned) log.scrollTop = log.scrollHeight;
}

const source = new EventSource(`/analyses/${appId}/events`);
source.onopen = reset;
source.addEventListener("stage", (event) => onStage(JSON.parse(event.data)));
source.addEventListener("end", (event) => {
  source.close();
  const { state, error } = JSON.parse(event.data);
  if (state === "done") {
    // The report row committed before the job settled (the runner publishes
    // inside the run), so a reload serves the published page.
    window.location.reload();
    return;
  }
  statusLine.hidden = false;
  statusLine.textContent = `analysis failed: ${error} — searching again re-queues it;
 labels already bought make the re-run nearly free`;
});
source.onerror = () => {
  // EventSource reconnects on its own; a 404 here means the job settled and
  // left the queue between frames — reload resolves to the report or an
  // honest state either way.
  if (source.readyState === EventSource.CLOSED) window.location.reload();
};
