/**
 * Chat widget for real-time event search with SSE streaming.
 * Uses PEP 649 deferred annotations and REACT agent backend.
 */

interface ChatEvent {
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
}

// Shown instantly, and while the real greeting is fetched from the API.
// Deliberately shorter than the served one: it is a placeholder for the
// moment before the fetch returns, not a second copy to keep in sync.
const FALLBACK_GREETING = `🏙️ **I'm Loopara**, your guide to what's on in Chicago.

Sandburg called this the City of the Big Shoulders. Ask me what you're in the mood for and I'll find it.

So - what are we doing tonight? ⚡`;

class ChatWidget {
  private container: HTMLElement;
  private messageList: HTMLElement;
  private inputField: HTMLInputElement;
  private sendButton: HTMLButtonElement;
  private newChatButton: HTMLButtonElement;
  private threadId: string | null = null;
  private conversationEnded = false;
  private isStreaming = false;
  private toolResults: Record<string, string> = {};
  private isCollapsed = true;
  private toggleBtn: HTMLButtonElement | null = null;
  private ctaLabel: HTMLElement | null = null;

  constructor(containerId: string) {
    this.container = document.getElementById(containerId)!;
    this.messageList = this.container.querySelector(".chat-messages")!;
    this.inputField = this.container.querySelector(".chat-input")!;
    this.sendButton = this.container.querySelector(".chat-send")!;
    this.newChatButton = this.container.querySelector(".chat-new")!;

    this.createToggleButton();
    this.setupEventListeners();
    this.collapseChat();
    this.showWelcomeGreeting();
  }

  private createToggleButton(): void {
    this.toggleBtn = document.createElement("button");
    this.toggleBtn.className = "chat-toggle-btn show";
    this.toggleBtn.title = "Open chat";

    // Create Loopara logo image
    const logo = document.createElement("img");
    logo.src = "/loopara-logo.svg";
    logo.style.width = "32px";
    logo.style.height = "32px";
    logo.style.filter = "drop-shadow(0 2px 4px rgba(0,0,0,0.2))";
    this.toggleBtn.appendChild(logo);

    this.toggleBtn.addEventListener("click", () => this.toggleChat());
    document.body.appendChild(this.toggleBtn);

    this.ctaLabel = document.createElement("div");
    this.ctaLabel.className = "chat-cta";
    this.ctaLabel.textContent = "🤖 Not sure?\nAsk Loopara!";
    document.body.appendChild(this.ctaLabel);
  }

  private toggleChat(): void {
    this.isCollapsed ? this.expandChat() : this.collapseChat();
  }

  private collapseChat(): void {
    this.isCollapsed = true;
    this.container.classList.add("collapsed");
    document.body.classList.add("chat-collapsed");
    if (this.toggleBtn) {
      this.toggleBtn.style.display = "flex";
      this.toggleBtn.title = "Open chat";
      const logo = this.toggleBtn.querySelector("img");
      if (logo) logo.style.opacity = "1";
    }
    if (this.ctaLabel) {
      this.ctaLabel.style.display = "block";
    }
  }

  private expandChat(): void {
    this.isCollapsed = false;
    this.container.classList.remove("collapsed");
    document.body.classList.remove("chat-collapsed");
    if (this.toggleBtn) {
      this.toggleBtn.title = "Close chat";
      this.toggleBtn.style.display = "none";
      const logo = this.toggleBtn.querySelector("img");
      if (logo) logo.style.opacity = "0.5";
    }
    if (this.ctaLabel) {
      this.ctaLabel.style.display = "none";
    }
    this.inputField.focus();
  }

  private async showWelcomeGreeting(): Promise<void> {
    // Fetched rather than hardcoded, so the persona and the Chicago facts
    // live in one place on the server and the fact can rotate per chat.
    // Rendered immediately from the fallback first: a greeting that appears
    // a second late makes the panel look broken on open.
    this.addMessageToUI("assistant", FALLBACK_GREETING);
    try {
      const base = (import.meta as any).env?.VITE_API_URL || "http://localhost:8000";
      const response = await fetch(`${base}/api/chat/greeting`);
      if (!response.ok) return;
      const { greeting } = await response.json();
      if (!greeting) return;
      // Replace the placeholder in place rather than appending, or the user
      // reads the same introduction twice.
      const messages = this.messageList.querySelectorAll(".chat-message");
      const first = messages[messages.length - 1];
      if (first) first.remove();
      this.addMessageToUI("assistant", greeting);
    } catch {
      // Offline or the API is down. The fallback is already on screen, and a
      // chat that cannot reach the server has a bigger problem to report than
      // a missing Chicago fact.
    }
  }

  private setupEventListeners(): void {
    this.sendButton.addEventListener("click", () => this.sendMessage());
    this.inputField.addEventListener("keypress", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });
    this.inputField.addEventListener("focus", () => {
      if (this.isCollapsed) this.expandChat();
    });
    this.newChatButton.addEventListener("click", () => this.startNewChat());

    // Wire up close button
    const closeBtn = document.getElementById("chat-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => this.collapseChat());
    }
  }

  private endConversation(): void {
    // The input stays usable so "start" can be typed. Disabling it was the
    // only way out before, which meant the one thing a person naturally does
    // at the end of a conversation - keep typing - did nothing at all.
    this.sendButton.style.display = "none";
    this.newChatButton.style.display = "inline-block";
    this.conversationEnded = true;
    this.inputField.disabled = false;
    this.inputField.placeholder = 'Type "start" for a new chat...';
    this.inputField.focus();
  }

  private startNewChat(): void {
    // Reset thread ID to start a new conversation
    this.threadId = null;
    this.conversationEnded = false;
    this.inputField.placeholder = "Ask about events...";
    this.inputField.disabled = false;
    this.sendButton.style.display = "inline-block";
    this.newChatButton.style.display = "none";

    // Clear history and show new greeting
    this.messageList.innerHTML = "";
    this.showWelcomeGreeting();
    this.inputField.focus();
  }

  private async sendMessage(): Promise<void> {
    const message = this.inputField.value.trim();
    if (!message || this.isStreaming) return;

    // After a conversation ends, "start" begins a fresh one. Accepted in the
    // words people actually use, and only while ended - mid-chat, "start
    // over" is a question about events somewhere, not a command.
    if (this.conversationEnded) {
      if (/^(start|start over|new|new chat|restart|again)[.!]?$/i.test(message)) {
        this.inputField.value = "";
        this.startNewChat();
        return;
      }
      // Anything else: say what to do rather than silently doing nothing.
      this.inputField.value = "";
      this.addMessageToUI("user", message);
      this.addMessageToUI(
        "assistant",
        'That one\'s done - type **start** (or hit **New Chat**) and I\'ll pick it up fresh.'
      );
      return;
    }

    // Add user message to UI
    this.addMessageToUI("user", message);
    this.inputField.value = "";
    this.isStreaming = true;

    try {
      await this.streamChat(message);
    } catch (error) {
      this.addMessageToUI("error", `Error: ${error}`);
    } finally {
      this.isStreaming = false;
    }
  }

  private async streamChat(message: string): Promise<void> {
    console.log("Chat: Sending message:", message);
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        thread_id: this.threadId,
      }),
    });

    console.log("Chat: Response status:", response.status);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // Stream state for UI
    let currentAssistantMessage = "";
    // Whether the server signalled it had finished. Without this, a dropped
    // connection and a genuinely empty answer were reported identically.
    let streamCompleted = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on the blank line that ends an SSE frame, not on single lines.
      //
      // The previous version read "event:" and took lines[i + 1] as its data,
      // which assumes the two arrive in the same network chunk. They often do
      // not: when a chunk boundary fell between them, lines[i + 1] was
      // undefined, the event line was dropped, and the orphaned data line was
      // skipped on the next read because it did not start with "event:". The
      // whole reply vanished and the user got "No response received from AI" -
      // more often on long replies, which is the worst possible bias.
      //
      // A frame is the unit the protocol actually defines, so split on that
      // and keep any trailing partial frame for the next chunk.
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        let eventType = "message";
        const dataLines: string[] = [];

        for (const line of frame.split(/\r?\n/)) {
          if (line.startsWith(":")) continue;           // comment / keep-alive
          if (line.startsWith("event:")) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            // A frame may carry several data lines; the spec joins them.
            dataLines.push(line.slice(5).replace(/^ /, ""));
          }
        }

        if (!dataLines.length) continue;
        try {
          const data = JSON.parse(dataLines.join("\n"));
          if (eventType === "complete") streamCompleted = true;
          await this.handleStreamEvent(eventType, data, (msg) => {
            currentAssistantMessage += msg;
          });
        } catch (e) {
          console.error("Chat: failed to parse SSE frame:", frame, e);
        }
      }
    }

    // Add final assistant message
    console.log("Chat: Final message:", currentAssistantMessage);
    if (currentAssistantMessage) {
      this.addMessageToUI("assistant", currentAssistantMessage);
    } else if (!streamCompleted) {
      // The stream ended before the server said it was done. That is a lost
      // connection, not a failure to answer - in development it is usually
      // the reloader restarting mid-request - and reporting it as "No
      // response received from AI" sent us looking in the wrong place more
      // than once.
      this.addMessageToUI(
        "error",
        "Lost the connection before I finished - the answer was on its way. Try asking again."
      );
    } else {
      this.addMessageToUI(
        "error",
        "I got nothing back for that one. Try rewording it?"
      );
    }
  }

  private async handleStreamEvent(
    eventType: string,
    data: Record<string, unknown>,
    appendMessage: (msg: string) => void
  ): Promise<void> {
    switch (eventType) {
      case "chat_started":
        this.threadId = data.thread_id as string;
        this.showStatus("Starting chat...");
        break;

      case "thinking":
        this.showStatus(`🤔 ${data.status}`);
        break;

      case "tool_call":
        this.showStatus(`🔧 Calling ${data.tool}...`);
        break;

      case "tool_result": {
        const tool = data.tool as string;
        // Store tool result for later - if there's backend data, capture it
        if (data.backend_data) {
          this.toolResults[tool] = data.backend_data as string;
        }
        this.showStatus(
          `✓ Found ${data.result_count} results`
        );
        break;
      }

      case "response": {
        this.clearStatus();
        let message = data.message as string;

        // If we have tool results and the message is generic, prepend formatted results
        if (Object.keys(this.toolResults).length > 0 && message.includes("Something went wrong")) {
          // This is a fallback, format the tool results we have
          const formatted = this.formatToolResults();
          if (formatted) {
            message = formatted;
          }
        }

        appendMessage(message);
        this.toolResults = {}; // Reset for next message
        break;
      }

      case "conversation_status":
        if (data.status === "limit_approaching") {
          this.showStatus(
            `⏳ One more question available (${data.remaining_turns} turns left)`
          );
        } else if (data.status === "limit_reached") {
          // The goodbye itself arrives as a response event and is already on
          // screen; this only needs to close the input. It used to be the
          // only notice the user got, as a grey chip reading "token limit
          // reached" - jargon, and the wrong jargon when turns ran out.
          const why = data.reason === "tokens" ? "reply budget" : "questions";
          this.showStatus(`\u2736 Out of ${why} - hit New Chat to keep going`);
          this.endConversation();
        }
        break;

      case "complete":
        // `?? -1` rather than `|| 0`. A missing field used to read as zero,
        // which ended the whole conversation and blamed the token limit: the
        // out-of-scope reply ("tell me a joke") sent no budget fields at all,
        // so a single off-topic question killed the chat. -1 means "the
        // server did not say", which is not a reason to stop.
        const turnsLeft = (data.remaining_turns as number) ?? -1;
        const tokensLeft = (data.remaining_tokens as number) ?? -1;
        const exhausted = turnsLeft === 0 || tokensLeft === 0;

        // Never the bare word "Complete" for a turn that finished normally -
        // it reads as the conversation ending, and did: a mid-chat "✅
        // Complete" chip had the user asking whether a new one had started.
        // Say how much is left, or say nothing.
        this.showStatus(
          exhausted
            // Name the limit actually reached. It said "token limit" either
            // way, while the turn limit is the one that runs out first.
            ? turnsLeft === 0
              ? `✶ That's the last question - hit New Chat to keep going`
              : `✶ Reply budget used up - hit New Chat to keep going`
            : turnsLeft > 0
              ? `✓ ${turnsLeft} question${turnsLeft === 1 ? "" : "s"} left`
              : ``
        );
        if (exhausted) {
          this.endConversation();
        }
        break;

      case "error":
        this.addMessageToUI("error", data.error as string);
        break;
    }
  }

  private addMessageToUI(role: string, content: string): void {
    const messageEl = document.createElement("div");
    messageEl.className = `chat-message chat-message-${role}`;

    const avatar = document.createElement("div");
    avatar.className = "chat-avatar";
    avatar.textContent = role === "user" ? "👤" : "🤖";

    const contentEl = document.createElement("div");
    contentEl.className = "chat-content";

    // Check if content contains formatted event results or markdown
    if (content.includes("**") || content.includes("📍") || content.includes("🎉") || content.includes("[")) {
      contentEl.innerHTML = this.parseMarkdownAndEvents(content);
    } else {
      contentEl.textContent = content;
    }

    messageEl.appendChild(avatar);
    messageEl.appendChild(contentEl);
    this.messageList.appendChild(messageEl);
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  private formatToolResults(): string {
    const searchResults = this.toolResults["search_local_db"];
    if (!searchResults) return "";

    // The search_local_db already returns formatted markdown
    // Just need to parse it for display
    return searchResults;
  }

  private parseMarkdownAndEvents(text: string): string {
    // Convert markdown links to HTML FIRST (before processing newlines)
    let html = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');

    // Headings, before newlines become <br>. The model writes "## From our
    // database", which was rendering with the hashes visible - the one piece
    // of markdown it uses most and the only one not handled here. Rendered as
    // bold rather than real <h2>, because a heading's margins are wrong
    // inside a chat bubble.
    html = html.replace(/^\s{0,3}#{1,4}\s+(.+)$/gm, '<strong class="chat-heading">$1</strong>');

    // The Chicago flag's four stars, in the flag's own red and centered.
    // Matched before bold so the characters are not mistaken for markup.
    html = html.replace(
      /^\s*(\u2736(?:\s+\u2736){3})\s*$/gm,
      '<div class="chat-flag-stars">$1</div>'
    );

    // Convert markdown bold to HTML
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Italic, for the Chicago fact in the greeting.
    html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    // Convert backtick code to HTML
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Convert newlines last
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  private showStatus(status: string): void {
    // An empty status means "nothing worth saying", so remove the chip rather
    // than leave a blank one sitting under the reply.
    if (!status) {
      this.clearStatus();
      return;
    }
    let statusEl = this.messageList.querySelector(".chat-status") as HTMLElement;
    if (!statusEl) {
      statusEl = document.createElement("div");
      statusEl.className = "chat-status";
      this.messageList.appendChild(statusEl);
    }
    statusEl.textContent = status;
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  private clearStatus(): void {
    const statusEl = this.messageList.querySelector(".chat-status");
    if (statusEl) statusEl.remove();
  }
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
  new ChatWidget("chat-widget");
});
