/**
 * Chat widget for real-time event search with SSE streaming.
 * Uses PEP 649 deferred annotations and REACT agent backend.
 */

interface ChatEvent {
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
}

class ChatWidget {
  private container: HTMLElement;
  private messageList: HTMLElement;
  private inputField: HTMLInputElement;
  private sendButton: HTMLButtonElement;
  private newChatButton: HTMLButtonElement;
  private threadId: string | null = null;
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

  private showWelcomeGreeting(): void {
    const greeting = `🏙️ **Meet Loopara!**

I'm your AI event discovery assistant, powered by Python 3.15, PydanticAI, and production-grade resilience patterns. Ready to find your next great event?

💡 **Try asking me:**
• "What's happening this weekend?"
• "Show me comedy events this month"
• "Any free events tonight?"
• "Jazz concerts in October"
• "Something like that concert but cheaper"

🔄 **Behind the scenes:**
- REACT agent reasoning with Claude
- Semantic similarity matching with NLTK
- Circuit breaker resilience patterns
- Real-time SSE streaming

Let's find your next great event! ⚡`;

    this.addMessageToUI("assistant", greeting);
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
    this.inputField.disabled = true;
    this.sendButton.style.display = "none";
    this.newChatButton.style.display = "inline-block";
  }

  private startNewChat(): void {
    // Reset thread ID to start a new conversation
    this.threadId = null;
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

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      // Keep last incomplete line in buffer
      buffer = lines.pop() || "";

      let i = 0;
      while (i < lines.length) {
        const line = lines[i];

        if (line.startsWith("event: ")) {
          const eventType = line.slice(7);
          const dataLine = lines[i + 1];
          console.log("Chat: Event type:", eventType);

          if (dataLine?.startsWith("data: ")) {
            try {
              const data = JSON.parse(dataLine.slice(6));
              console.log("Chat: Event data:", data);
              await this.handleStreamEvent(eventType, data, (msg) => {
                currentAssistantMessage += msg;
              });
            } catch (e) {
              console.error("Chat: Failed to parse event data:", e);
            }
            i += 2; // Skip event and data lines
          } else {
            i += 1;
          }
        } else {
          i += 1;
        }
      }
    }

    // Add final assistant message
    console.log("Chat: Final message:", currentAssistantMessage);
    if (currentAssistantMessage) {
      this.addMessageToUI("assistant", currentAssistantMessage);
    } else {
      this.addMessageToUI("error", "No response received from AI");
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
          this.showStatus("✋ Chat ended - token limit reached. Start a new chat!");
          this.endConversation();
        }
        break;

      case "complete":
        const remaining = data.remaining_turns as number || 0;
        this.showStatus(
          remaining === 0
            ? `✅ Chat complete (token limit reached)`
            : `✅ Complete (${data.tokens_used} tokens)`
        );
        if (remaining === 0) {
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
    // Convert markdown bold to HTML
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Convert backtick code to HTML
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    // Convert newlines last
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  private showStatus(status: string): void {
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
