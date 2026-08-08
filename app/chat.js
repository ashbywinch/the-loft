/** The Loft's chat box — the one way to build a chat surface.
 *  Layout: messages → input bar → action row (actions BELOW the input), send
 *  bottom-left, busy state disables everything, nothing told is lost
 *  (docs/CHAT-UX.md). New chat functionality goes through this module.
 */

import { el } from "./ui.js";

const ASSISTANT_NAME = "The Loft";
const MAX_INPUT_HEIGHT = 200;

/** A chat textarea grows with its content, capped so a long story scrolls
 *  instead of filling the screen (docs/CHAT-UX.md). */
function autoGrow(textarea) {
  const fit = () => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  };
  textarea.addEventListener("input", fit);
  fit();
  return textarea;
}

/** An input that autocompletes over suggestions with a filtered dropdown —
 *  NOT a native datalist, which does not work on mobile browsers (user,
 *  2026-08-03). */
export function autocomplete({ suggestions = [], placeholder = "" } = {}) {
  const input = el("input", { class: "field", placeholder, autocomplete: "off", "aria-label": "Type to search" });
  const list = el("div", { class: "ac-list", role: "listbox", hidden: true });
  const node = el("div", { class: "ac" }, [input, list]);

  let highlighted = -1;
  const matches = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) return [];
    return suggestions.filter((s) => s.toLowerCase().includes(q)).slice(0, 8);
  };

  const render = () => {
    const items = matches();
    list.replaceChildren(
      ...items.map((s, i) =>
        el(
          "button",
          {
            type: "button",
            class: `ac-item${i === highlighted ? " highlight" : ""}`,
            onclick: () => {
              input.value = s;
              input.dispatchEvent(new Event("input", { bubbles: true }));
              list.hidden = true;
            },
          },
          s,
        ),
      ),
    );
    // the input bar is pinned at the bottom — open upward when there is more
    // room above, so the list never falls off the screen (user, 2026-08-03)
    const rect = input.getBoundingClientRect();
    node.classList.toggle("ac-up", rect.top > window.innerHeight - rect.bottom);
    list.hidden = items.length === 0;
  };

  input.addEventListener("input", () => {
    highlighted = -1;
    render();
  });
  input.addEventListener("focus", () => {
    if (input.value.trim()) render();
  });
  input.addEventListener("blur", () =>
    setTimeout(() => {
      list.hidden = true;
    }, 150),
  );
  input.addEventListener("keydown", (e) => {
    const items = matches();
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      highlighted = (highlighted + 1) % items.length;
      render();
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      highlighted = (highlighted - 1 + items.length) % items.length;
      render();
    } else if (e.key === "Enter" && highlighted >= 0 && items[highlighted]) {
      e.preventDefault();
      input.value = items[highlighted];
      list.hidden = true;
      input.dispatchEvent(new Event("input", { bubbles: true })); // updateSend — the click path does the same
    }
  });

  return { node, input, value: () => input.value };
}

/** The chat column: messages, the input bar (send bottom-left), the action
 *  row below the input, and a busy state that disables everything. */
export function chatBox({ placeholder = "Write here…" } = {}) {
  let input = autoGrow(el("textarea", { class: "field", rows: 1, placeholder }));
  let inputNode = input;
  const messages = el("div", { class: "chat-msgs", role: "log" });
  const send = el("button", { class: "btn btn-primary", "aria-label": "Send", disabled: true }, "Send");
  const inputRow = el("div", { class: "chat-bar" }, [input, send]); // send on the right — the thumb side
  const selection = el("div", { class: "chat-selection", hidden: true });
  const quick = el("div", { class: "chat-quick", hidden: true });
  const node = el("div", { class: "chat" }, [messages, selection, quick, inputRow]);

  let busy = false;
  let onSend = null;

  const updateSend = () => {
    send.disabled = busy || !input.value.trim();
  };
  const scroll = () => {
    node.scrollTop = node.scrollHeight;
  };

  input.addEventListener("input", updateSend);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  });

  function doSend() {
    const value = input.value.trim();
    if (!value || busy || !onSend) return;
    input.value = "";
    updateSend();
    onSend(value);
  }

  send.addEventListener("click", doSend);

  /** Drive the flow programmatically — the draft replay reconstructs the
   *  transcript by sending the stored messages through the live handlers. */
  function submit(value) {
    input.value = value;
    doSend();
  }

  function addUser(text) {
    messages.append(el("div", { class: "bubble bubble-user" }, text));
    scroll();
  }

  function addAssistant(text, label = ASSISTANT_NAME) {
    messages.append(
      el("div", { class: "bubble bubble-ai" }, [
        label ? el("div", { class: "bubble-who" }, label) : null,
        el("div", { class: "bubble-text" }, text),
      ]),
    );
    scroll();
  }

  /** Busy disables typing and sending while the assistant works (reading,
   *  assessing, saving) — the narrator cannot type over it (user, 2026-08-03). */
  function setBusy(flag, note = null) {
    busy = flag;
    input.disabled = flag;
    inputRow.classList.toggle("busy", flag);
    updateSend();
    if (flag) quick.hidden = true; // the typing indicator replaces the chips
    if (flag && note) addAssistant(note);
  }

  // Quick replies are chips between the last message and the input bar —
  // nothing interactive goes below the composer (docs/CHAT-UX.md). Tapping a
  // chip "sends" it, and the suggestions clear like any sent reply; in
  // multi mode (a "who was there" question) chips stay so the narrator can
  // pick several before the finishing chip.
  function setQuickReplies(chips, { multi = false } = {}) {
    quick.replaceChildren(
      ...chips.map(({ label, onClick, primary = false }) =>
        el(
          "button",
          {
            type: "button",
            class: `chip${primary ? " chip-primary" : ""}`,
            onclick: () => {
              if (!multi) quick.hidden = true;
              onClick();
            },
          },
          label,
        ),
      ),
    );
    quick.hidden = busy;
  }

  // A committed value (the narrator, or each person picked for a "who was
  // there" answer) is a removable pill — the combobox-with-committed-value
  // pattern (docs/CHAT-UX.md): the remove control is a real button with an
  // accessible name; removal is immediate.
  function setSelection(selections) {
    const items = Array.isArray(selections) ? selections : [selections];
    selection.replaceChildren(
      ...items.map(({ label, onRemove }) =>
        el("div", { class: "chip chip-selection" }, [
          el("span", { class: "chip-label" }, label),
          // a committed value's remove is a real button (docs/CHAT-UX.md);
          // a fixed identity (the signed-in narrator, 2026-08-06) has no
          // remove — it is not a claim to dismiss
          ...(onRemove
            ? [
                el(
                  "button",
                  {
                    type: "button",
                    class: "chip-remove",
                    "aria-label": `Remove ${label}`,
                    onclick: () => {
                      if (selection.children.length <= 1) selection.hidden = true;
                      onRemove();
                    },
                  },
                  "✕",
                ),
              ]
            : []),
        ]),
      ),
    );
    selection.hidden = false;
  }

  function clearQuickReplies() {
    quick.hidden = true;
  }

  function clearSelection() {
    selection.hidden = true;
    selection.replaceChildren();
  }

  /** Swap the input element (the who-stage uses the autocomplete, everything
   *  else the textarea) — the send button keeps working on the new input. */
  function swapInput(newInput) {
    const next = newInput.node ?? newInput;
    inputRow.replaceChild(next, inputNode);
    inputNode = next;
    input = newInput.input ?? newInput;
    if (input.tagName === "TEXTAREA") autoGrow(input);
    input.addEventListener("input", updateSend);
    if (input.tagName !== "TEXTAREA") {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.defaultPrevented) {
          e.preventDefault();
          doSend();
        }
      });
    }
    updateSend();
  }

  function onSendHandler(handler) {
    onSend = handler;
  }

  return {
    node,
    messages,
    input,
    send,
    addUser,
    addAssistant,
    setBusy,
    setQuickReplies,
    clearQuickReplies,
    setSelection,
    clearSelection,
    swapInput,
    submit,
    onSend: onSendHandler,
    focus: () => input.focus(),
    scroll,
  };
}
