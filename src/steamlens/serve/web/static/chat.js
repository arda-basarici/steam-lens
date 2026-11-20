// The chat page: send one message (POST /chat/turns), show the turn that
// comes back. The page holds two things, in memory only: what is on screen
// and the conversation's identifier, which the server hands out with the
// first reply. A reload starts a new conversation, since the server never
// sends one back. Nothing of the conversation travels in a request but the
// identifier and the new message.
//
// A reply is plain text. It and everything else here land via textContent:
// the chat's words are a model's, written from reviews, and are hostile
// input under the same assumption the templates hold. String-to-DOM APIs
// are banned outright (a CI test scans this file for them).
//
// A refusal (a cap, a busy chat, a conversation that has ended) is not a
// message: it shows as a line by the input, and the message that drew it
// goes back into the box, because the server did not take it.

const form = document.getElementById("chat-form");
const input = document.getElementById("chat-input");
const sendButton = document.getElementById("chat-send");
const newButton = document.getElementById("chat-new");
const log = document.getElementById("chat-log");
const statusLine = document.getElementById("chat-status");
const announce = document.getElementById("chat-announce");

let conversation = null; // the identifier, once the server has given one
let over = false; // the conversation on screen can take no further message

function setStatus(text) {
  statusLine.hidden = !text;
  statusLine.textContent = text;
  if (text) announce.textContent = text;
}

function setWaiting(waiting) {
  input.disabled = waiting || over;
  sendButton.disabled = waiting || over;
}

function addMessage(speaker, text) {
  const item = document.createElement("li");
  item.className = `chat-message from-${speaker}`;
  const who = document.createElement("span");
  who.className = "chat-speaker";
  who.textContent = speaker === "player" ? "you" : "chat";
  const body = document.createElement("p");
  body.className = "chat-text";
  body.textContent = text;
  item.append(who, body);
  log.append(item);
  item.scrollIntoView({ block: "nearest" });
  return item;
}

function linkRow(label, links) {
  const row = document.createElement("p");
  row.className = "chat-links";
  const name = document.createElement("span");
  name.className = "chat-links-label";
  name.textContent = label;
  row.append(name);
  for (const link of links) {
    const anchor = document.createElement("a");
    anchor.href = link.url;
    anchor.textContent = link.title;
    row.append(anchor);
  }
  return row;
}

// The links the server says belong under this reply: the reports of the
// games it offers, apart from those of the games it only speaks of, and the
// way to add a game when it found nothing. "Also mentioned" only means
// something beside a row of offered games: on a turn about one game, that
// game's report is simply the report.
function addLinks(item, turn) {
  if (turn.offered.length > 0) item.append(linkRow("reports", turn.offered));
  if (turn.about.length > 0) {
    item.append(linkRow(turn.offered.length > 0 ? "also mentioned" : "reports", turn.about));
  }
  if (turn.add_game_url) {
    item.append(
      linkRow("missing a game?", [{ url: turn.add_game_url, title: "add it to the library" }]),
    );
  }
}

async function refusalLine(response) {
  try {
    const detail = (await response.json()).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // a body that is not JSON (a proxy's own page) falls through to the generic line
  }
  return "The chat could not answer just now. Try again in a moment.";
}

async function send(text) {
  setStatus("");
  setWaiting(true);
  const mine = addMessage("player", text);
  const reply = addMessage("chat", "working on a reply…");
  reply.classList.add("pending");
  announce.textContent = "The chat is working on a reply.";
  input.value = "";

  // The server did not take the message: it comes off the screen and goes
  // back into the box, and the line says why.
  const takeBack = (line) => {
    mine.remove();
    reply.remove();
    input.value = text;
    setStatus(line);
  };

  let response;
  try {
    response = await fetch("/chat/turns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation }),
    });
  } catch {
    takeBack("The message did not go through. Check the connection and try again.");
    setWaiting(false);
    return;
  }
  if (!response.ok) {
    // 410: this conversation can take no more (ended, or at its length).
    // What is on screen stays readable, and only a new one can go on.
    over = response.status === 410;
    takeBack(await refusalLine(response));
    setWaiting(false);
    if (over) newButton.focus();
    return;
  }

  const turn = await response.json();
  conversation = turn.conversation;
  reply.classList.remove("pending");
  reply.dataset.ending = turn.ending;
  reply.querySelector(".chat-text").textContent = turn.text;
  addLinks(reply, turn);
  reply.scrollIntoView({ block: "nearest" });
  announce.textContent = turn.text;
  setWaiting(false);
  input.focus();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (text && !input.disabled) send(text);
});

// Enter sends, Shift+Enter breaks the line.
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

newButton.addEventListener("click", () => {
  conversation = null;
  over = false;
  log.replaceChildren();
  setStatus("");
  announce.textContent = "A new conversation.";
  setWaiting(false);
  input.focus();
});
