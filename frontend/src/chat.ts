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

  constructor(containerId: string) {
    this.container = document.getElementById(containerId)!;
    this.messageList = this.container.querySelector(".chat-messages")!;
    this.inputField = this.container.querySelector(".chat-input")!;
    this.sendButton = this.container.querySelector(".chat-send")!;
    this.newChatButton = this.container.querySelector(".chat-new")!;

    this.setupEventListeners();
    this.showWelcomeGreeting();
  }

  private showWelcomeGreeting(): void {
    const greeting = `🏙️ **EventLoop: Async Event Discovery in the 312**

Welcome to the future of event discovery! Powered by Python 3.15, PydanticAI, and production-grade resilience patterns.

💡 **Try asking:**
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
    this.newChatButton.addEventListener("click", () => this.startNewChat());
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
        this.showStatus(`🔧 Calling ${data.tool}: ${data.args}`);
        break;

      case "tool_result":
        this.showStatus(
          `✓ Found ${data.result_count} results: ${data.snippet}`
        );
        break;

      case "response":
        this.clearStatus();
        appendMessage(data.message as string);
        break;

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

    // Check if content contains event results (starts with Found N great match)
    if (content.includes("📍 **Found") && content.includes("**")) {
      contentEl.innerHTML = this.parseMarkdownAndEvents(content);
    } else {
      contentEl.textContent = content;
    }

    messageEl.appendChild(avatar);
    messageEl.appendChild(contentEl);
    this.messageList.appendChild(messageEl);
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  private parseMarkdownAndEvents(text: string): string {
    // Convert markdown bold to HTML
    let html = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Convert emojis and newlines
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
