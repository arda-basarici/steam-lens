// The chat page: send one message (POST /chat/turns), show the turn that
// comes back. The page holds two things, in memory only: what is on screen
// and the conversation's identifier, which the server hands out with the
// first reply. A reload starts a new conversation, since the server never
// sends one back. Nothing of the conversation travels in a request but the
// identifier and the new message.
//
// A reply arrives as blocks of plain text, cut by the server where it moves
// to another game, with a card (the game's art and title, linking to its
// report) over the first block of each game it offers. The blocks and
// everything else here land via textContent:
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

// A game's card: its header art and title, the whole of it a link to the
// game's report.
function gameCard(card) {
  const anchor = document.createElement("a");
  anchor.className = "chat-card";
  anchor.href = card.url;
  const art = document.createElement("img");
  art.src = card.image_url;
  art.alt = "";
  art.loading = "lazy";
  art.width = 460;
  art.height = 215;
  const title = document.createElement("span");
  title.className = "chat-card-name";
  title.textContent = card.title;
  anchor.append(art, title);
  return anchor;
}

// The reply's blocks in place of the pending line: each a paragraph, under
// its card when it has one.
function showBlocks(item, blocks) {
  item.querySelector(".chat-text").remove();
  for (const block of blocks) {
    if (block.card) item.append(gameCard(block.card));
    const paragraph = document.createElement("p");
    paragraph.className = "chat-text";
    paragraph.textContent = block.text;
    item.append(paragraph);
  }
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
// games it speaks of that no card shows (a game set aside, the one named
// for a comparison), and the way to add a game when it found nothing.
function addLinks(item, turn) {
  if (turn.about.length > 0) item.append(linkRow("also mentioned", turn.about));
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
  showBlocks(reply, turn.blocks);
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
