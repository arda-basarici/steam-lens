// The search flow: resolve a typed name to pickable games (GET /search),
// then submit the pick as an analysis request (POST /analyses) and open its
// report page. All text lands via textContent — result names are hostile
// input under the same assumption the templates hold; string-to-DOM APIs are
// banned outright (a CI test scans this file for them).

const form = document.getElementById("search-form");
const input = document.getElementById("search-input");
const statusLine = document.getElementById("search-status");
const results = document.getElementById("search-results");

function setStatus(text) {
  statusLine.hidden = !text;
  statusLine.textContent = text;
}

function hitRow(hit) {
  const item = document.createElement("li");
  const pick = document.createElement("button");
  pick.type = "button";
  pick.className = "result";
  const capsule = document.createElement("img");
  capsule.src = hit.capsule_url;
  capsule.alt = "";
  capsule.loading = "lazy";
  const name = document.createElement("span");
  name.textContent = hit.name;
  pick.append(capsule, name);
  pick.addEventListener("click", () => submitPick(hit));
  item.append(pick);
  return item;
}

async function runSearch(term) {
  setStatus("searching…");
  results.replaceChildren();
  let response;
  try {
    response = await fetch(`/search?q=${encodeURIComponent(term)}`);
  } catch {
    setStatus("search failed — check the connection and try again");
    return;
  }
  if (!response.ok) {
    setStatus("search failed — try again in a moment");
    return;
  }
  const hits = await response.json();
  if (hits.length === 0) {
    setStatus("no games found for that name");
    return;
  }
  setStatus("");
  results.replaceChildren(...hits.map(hitRow));
}

async function submitPick(hit) {
  setStatus(`requesting analysis of ${hit.name}…`);
  let response;
  try {
    response = await fetch("/analyses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_id: hit.app_id, requested_name: hit.name }),
    });
  } catch {
    setStatus("request failed — check the connection and try again");
    return;
  }
  if (!response.ok) {
    setStatus("request failed — try again in a moment");
    return;
  }
  // 200 = a published report already answers; 202 = a job queued — either
  // way the report page is the destination (it becomes the live narration
  // surface in a later build chunk).
  window.location = `/reports/${hit.app_id}`;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const term = input.value.trim();
  if (term) runSearch(term);
});
