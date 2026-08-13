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
    // 429 carries the submit gate's honest visitor-facing message (daily
    // allowance used / one analysis at a time) — show it verbatim.
    if (response.status === 429) {
      let detail = null;
      try {
        detail = (await response.json()).detail;
      } catch {
        // a non-JSON 429 (a proxy's own) falls through to the generic text
      }
      setStatus(detail || "analyses are limited right now — try again later");
    } else {
      setStatus("request failed — try again in a moment");
    }
    return;
  }
  // 200 = a published report already answers, and its receipt carries the
  // canonical named URL; 202 = a job queued, which has no name yet — the id
  // address serves the live narration and canonicalizes after publish.
  const receipt = await response.json();
  window.location = receipt.report_url || `/reports/${hit.app_id}`;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const term = input.value.trim();
  if (term) runSearch(term);
});
