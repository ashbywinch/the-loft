import { describe, expect, it, vi } from "vitest";
import { autocomplete, chatBox } from "../chat.js";

describe("chatBox layout (docs/CHAT-UX.md)", () => {
  it("orders messages, then selection, then quick replies, then the input bar", () => {
    const chat = chatBox();
    chat.addAssistant("Anything else?");
    chat.setSelection({ label: "Alex Hale", onRemove: () => {} });
    chat.setQuickReplies([{ label: "That's everything", primary: true, onClick: () => {} }]);
    const children = [...chat.node.children];
    expect(children[0].classList.contains("chat-msgs")).toBe(true);
    expect(children[1].classList.contains("chat-selection")).toBe(true);
    expect(children[2].classList.contains("chat-quick")).toBe(true);
    expect(children[3].classList.contains("chat-bar")).toBe(true);
    expect(children[3].nextElementSibling).toBe(null); // the composer is the bottom-most element
  });

  it("shows a committed value as a removable pill with an accessible X", () => {
    const chat = chatBox();
    let removed = 0;
    chat.setSelection({
      label: "Alex Hale",
      onRemove: () => {
        removed += 1;
      },
    });
    const chip = chat.node.querySelector(".chip-selection");
    expect(chip.querySelector(".chip-label").textContent).toBe("Alex Hale");
    const x = chip.querySelector(".chip-remove");
    expect(x.getAttribute("aria-label")).toBe("Remove Alex Hale"); // APG: the X names its target
    x.click();
    expect(removed).toBe(1);
    expect(chat.node.querySelector(".chat-selection").hidden).toBe(true);
  });

  it("multi-mode chips stay after a tap so several can be picked", () => {
    const chat = chatBox();
    const picked = [];
    chat.setQuickReplies(
      [
        { label: "Mum", onClick: () => picked.push("Mum") },
        { label: "That's everyone", primary: true, onClick: () => {} },
      ],
      { multi: true },
    );
    chat.node.querySelector(".chat-quick .chip").click();
    expect(picked).toEqual(["Mum"]);
    expect(chat.node.querySelector(".chat-quick").hidden).toBe(false); // still picking
  });

  it("shows several committed values as removable pills", () => {
    const chat = chatBox();
    const removed = [];
    chat.setSelection([
      { label: "Mum", onRemove: () => removed.push("Mum") },
      { label: "Harper", onRemove: () => removed.push("Harper") },
    ]);
    const chips = [...chat.node.querySelectorAll(".chip-selection")];
    expect(chips.length).toBe(2);
    expect(chips[1].querySelector(".chip-remove").getAttribute("aria-label")).toBe("Remove Harper");
    chips[1].querySelector(".chip-remove").click();
    expect(removed).toEqual(["Harper"]);
  });

  it("renders chips and clears the row when one is tapped", () => {
    const chat = chatBox();
    let tapped = 0;
    chat.setQuickReplies([
      {
        label: "That's everything",
        primary: true,
        onClick: () => {
          tapped += 1;
        },
      },
      { label: "Skip", onClick: () => {} },
    ]);
    const chips = [...chat.node.querySelectorAll(".chat-quick .chip")];
    expect(chips.map((c) => c.textContent)).toEqual(["That's everything", "Skip"]);
    expect(chips[0].classList.contains("chip-primary")).toBe(true);
    chips[0].click();
    expect(tapped).toBe(1);
    expect(chat.node.querySelector(".chat-quick").hidden).toBe(true);
  });

  it("puts the send button on the right of the input — the thumb side (user, 2026-08-03)", () => {
    const chat = chatBox();
    const bar = chat.node.querySelector(".chat-bar");
    expect(bar.lastElementChild.classList.contains("btn")).toBe(true);
    expect(bar.firstElementChild.tagName).toBe("TEXTAREA");
  });

  it("sends only when there is text, and clears after send", () => {
    const chat = chatBox();
    const sent = [];
    chat.onSend((value) => sent.push(value));
    const send = chat.node.querySelector(".chat-bar .btn-primary");
    expect(send.disabled).toBe(true);
    chat.input.value = "hello";
    chat.input.dispatchEvent(new Event("input"));
    expect(send.disabled).toBe(false);
    send.click();
    expect(sent).toEqual(["hello"]);
    expect(chat.input.value).toBe("");
    expect(send.disabled).toBe(true);
  });

  it("busy disables typing and sending, and shows the note in the stream", () => {
    const chat = chatBox();
    chat.input.value = "x";
    chat.input.dispatchEvent(new Event("input"));
    chat.setBusy(true, "Reading your story…");
    expect(chat.input.disabled).toBe(true);
    expect(chat.node.querySelector(".chat-bar .btn-primary").disabled).toBe(true);
    expect(chat.node.querySelector(".chat-quick").hidden).toBe(true);
    expect(chat.node.textContent).toContain("Reading your story…");
    chat.setBusy(false);
    expect(chat.input.disabled).toBe(false);
  });

  it("renders the assistant header as a separate line from the body", () => {
    const chat = chatBox();
    chat.addAssistant("Who's telling this?");
    const bubble = chat.node.querySelector(".bubble-ai");
    expect(bubble.querySelector(".bubble-who").textContent).toBe("The Loft");
    expect(bubble.querySelector(".bubble-text").textContent).toBe("Who's telling this?");
  });
});

describe("autocomplete (a working dropdown, not a datalist)", () => {
  const cast = ["Nora Hale", "Mum", "Mummy", "Alex Hale", "Alex"];

  it("filters suggestions as you type", () => {
    const ac = autocomplete({ suggestions: cast });
    ac.input.value = "alex";  // matches Alex Hale and Alex
    ac.input.dispatchEvent(new Event("input"));
    const items = [...ac.node.querySelectorAll(".ac-item")].map((b) => b.textContent);
    expect(items).toEqual(["Alex Hale", "Alex"]);
  });

  it("selects a suggestion on tap", () => {
    const ac = autocomplete({ suggestions: cast });
    ac.input.value = "mum";
    ac.input.dispatchEvent(new Event("input"));
    [...ac.node.querySelectorAll(".ac-item")][0].click();
    expect(ac.value()).toBe("Mum");
    expect(ac.node.querySelector(".ac-list").hidden).toBe(true);
  });

  it("shows no dropdown when nothing matches", () => {
    const ac = autocomplete({ suggestions: cast });
    ac.input.value = "zzz";
    ac.input.dispatchEvent(new Event("input"));
    expect(ac.node.querySelectorAll(".ac-item").length).toBe(0);
    expect(ac.node.querySelector(".ac-list").hidden).toBe(true);
  });

  it("opens upward when the input sits near the bottom of the screen", () => {
    const ac = autocomplete({ suggestions: cast });
    // the input bar is pinned at the bottom — the list must not fall off-screen
    vi.spyOn(ac.input, "getBoundingClientRect").mockReturnValue({ top: 800, bottom: 845 });
    ac.input.value = "alex";  // matches Alex Hale and Alex
    ac.input.dispatchEvent(new Event("input"));
    expect(ac.node.classList.contains("ac-up")).toBe(true); // styles.css anchors the list upward
  });

  it("auto-grows the textarea with the message, capped at the max", () => {
    const chat = chatBox();
    Object.defineProperty(chat.input, "scrollHeight", { value: 120, configurable: true });
    chat.input.value = "a long story that needs several lines";
    chat.input.dispatchEvent(new Event("input"));
    expect(chat.input.style.height).toBe("120px");
    Object.defineProperty(chat.input, "scrollHeight", { value: 500, configurable: true });
    chat.input.dispatchEvent(new Event("input"));
    expect(chat.input.style.height).toBe("200px");
  });

  it("Enter-selecting a suggestion enables the send button", () => {
    // reviewer, 2026-08-03: the Enter path set the value without an input
    // event, so updateSend never ran and send stayed disabled when the value
    // arrived without a keystroke first
    const chat = chatBox();
    const ac = autocomplete({ suggestions: cast });
    chat.swapInput(ac);
    ac.input.value = "alex";  // matches Alex Hale and Alex // no input event — updateSend has never seen this value
    ac.input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    ac.input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(chat.node.querySelector(".chat-bar .btn-primary").disabled).toBe(false);
  });

  it("opens downward when there is room below", () => {
    const ac = autocomplete({ suggestions: cast });
    vi.spyOn(ac.input, "getBoundingClientRect").mockReturnValue({ top: 100, bottom: 145 });
    ac.input.value = "alex";  // matches Alex Hale and Alex
    ac.input.dispatchEvent(new Event("input"));
    expect(ac.node.classList.contains("ac-up")).toBe(false);
  });
});
