/**
 * LiteLLM Assist Chat card for Home Assistant.
 * Served from /litellm_assist/litellm-assist-chat.js (registered by the integration).
 * Depends on ./lit.js (vendored lit ESM bundle).
 */
import { LitElement, html, css, nothing } from "./lit.js";

const MD_MODES = { chat: "chat", assist: "assist" };

/* ------------------------------------------------------------------ */
/* Tiny safe markdown: escape first, then allow bold/italic/code/pre. */
/* ------------------------------------------------------------------ */
function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function mdLite(text) {
  if (!text) return "";
  const blocks = [];
  // fenced code blocks first
  let src = String(text).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push(
      `<pre class="code-block"><code>${esc(code.replace(/\n$/, ""))}</code></pre>`
    );
    return `\u0000${blocks.length - 1}\u0000`;
  });
  src = esc(src);
  // inline code
  src = src.replace(/`([^`\n]+)`/g, '<code class="inline-code">$1</code>');
  // bold / italic
  src = src.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  src = src.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  // restore blocks
  src = src.replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[Number(i)]);
  return src;
}

/* ------------------------------------------------------------------ */

class LiteLLMAssistChat extends LitElement {
  static get properties() {
    return {
      hass: { state: true },
      config: { state: true },
      _models: { state: true },
      _agents: { state: true },
      _conv: { state: true },
      _convs: { state: true },
      _streamText: { state: true },
      _streaming: { state: true },
      _assistBusy: { state: true },
      _draft: { state: true },
      _error: { state: true },
      _model: { state: true },
      _agent: { state: true },
    };
  }

  static getStubConfig() {
    return { title: "Chat" };
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      .wrap {
        display: flex;
        flex-direction: column;
        height: var(--lac-height, 560px);
        min-height: 420px;
        background: var(--card-background-color, var(--primary-background-color));
        color: var(--primary-text-color);
        border-radius: var(--ha-card-border-radius, 12px);
        overflow: hidden;
      }
      header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-bottom: 1px solid var(--divider-color, rgba(128, 128, 128, 0.2));
      }
      header .title {
        font-weight: 600;
        font-size: 1em;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      select,
      textarea,
      button {
        font: inherit;
        color: var(--primary-text-color);
      }
      select {
        margin-left: auto;
        max-width: 45%;
        background: var(--card-background-color, #111);
        color: var(--primary-text-color, #eee);
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.3));
        border-radius: 8px;
        padding: 4px 6px;
      }
      select.mode {
        margin-left: auto;
        max-width: none;
        flex: 0 0 auto;
      }
      .thinking {
        animation: pulse 1.2s ease-in-out infinite;
      }
      @keyframes pulse {
        50% {
          opacity: 0.5;
        }
      }
      select option {
        background: var(--card-background-color, #111);
        color: var(--primary-text-color, #eee);
      }
      .msgs {
        flex: 1;
        overflow-y: auto;
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-height: 0;
        -webkit-overflow-scrolling: touch;
      }
      .row {
        display: flex;
      }
      .row.user {
        justify-content: flex-end;
      }
      .bubble {
        max-width: 85%;
        padding: 8px 12px;
        border-radius: 14px;
        line-height: 1.45;
        overflow-wrap: break-word;
        white-space: pre-wrap;
        color: var(--primary-text-color, #eee);
        background: var(--secondary-background-color, rgba(128, 128, 128, 0.2));
      }
      .row.user .bubble {
        background: var(--primary-color, #03a9f4);
        color: var(--text-primary-color, #fff);
        border-bottom-right-radius: 4px;
      }
      .row.assistant .bubble {
        border-bottom-left-radius: 4px;
      }
      .bubble .code-block {
        background: var(--markdown-code-background-color, rgba(0, 0, 0, 0.25));
        padding: 8px;
        border-radius: 8px;
        overflow-x: auto;
        font-family: var(--code-font-family, monospace);
        font-size: 0.9em;
        white-space: pre;
      }
      .bubble .inline-code {
        background: var(--markdown-code-background-color, rgba(0, 0, 0, 0.2));
        padding: 1px 5px;
        border-radius: 6px;
        font-family: var(--code-font-family, monospace);
      }
      .cursor {
        display: inline-block;
        width: 8px;
        height: 1em;
        background: var(--primary-color);
        vertical-align: text-bottom;
        animation: blink 1s steps(1) infinite;
      }
      @keyframes blink {
        50% {
          opacity: 0;
        }
      }
      .error {
        color: var(--error-color, #db4437);
        font-size: 0.9em;
        padding: 4px 12px;
      }
      .composer {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        padding: 8px 12px calc(8px + env(safe-area-inset-bottom, 0px));
        border-top: 1px solid var(--divider-color, rgba(128, 128, 128, 0.2));
      }
      .composer textarea {
        flex: 1;
        resize: none;
        border: 1px solid var(--divider-color, rgba(128, 128, 128, 0.3));
        border-radius: 12px;
        background: transparent;
        padding: 10px 12px;
        max-height: 120px;
        min-height: 40px;
        line-height: 1.4;
      }
      .iconbtn {
        border: none;
        background: transparent;
        cursor: pointer;
        padding: 8px;
        border-radius: 50%;
        color: var(--primary-color);
        font-size: 18px;
        line-height: 1;
      }
      .iconbtn:disabled {
        opacity: 0.4;
        cursor: default;
      }
      .empty {
        margin: auto;
        color: var(--secondary-text-color);
        text-align: center;
        padding: 24px;
      }
    `;
  }

  constructor() {
    super();
    this._models = [];
    this._agents = [];
    this._convs = [];
    this._conv = null;
    this._streamText = "";
    this._streaming = false;
    this._assistBusy = false;
    this._draft = "";
    this._error = "";
    this._model = "";
    this._agent = "";
    this._unsub = null;
  }

  setConfig(config) {
    this.config = {
      title: "Chat",
      height: 560,
      default_model: "",
      ...config,
    };
  }

  set hass(hass) {
    const first = !this.__hass;
    this.__hass = hass;
    if (first) this._init();
  }

  get hass() {
    return this.__hass;
  }

  getCardSize() {
    return 8;
  }

  async _init() {
    try {
      const res = await this.hass.callWS({ type: "litellm_assist/models" });
      this._models = res.models;
      this._agents = res.agents;
      const prefs = await this.hass.callWS({
        type: "litellm_assist/prefs",
        action: "get",
      });
      if (!this._model && prefs.model && this._models.includes(prefs.model)) {
        this._model = prefs.model;
      }
      if (
        !this._agent &&
        prefs.agent &&
        this._agents.some((a) => a.entity_id === prefs.agent)
      ) {
        this._agent = prefs.agent;
      }
      if (!this._model) {
        this._model =
          this.config.default_model && this._models.includes(this.config.default_model)
            ? this.config.default_model
            : (res.models[0] ?? "");
      }
      if (!this._agent && res.agents.length) this._agent = res.agents[0].entity_id;
      await this._loadConvs();
    } catch (e) {
      this._error = `models: ${e.message || e}`;
    }
  }

  _agentName(id) {
    return this._agents.find((a) => a.entity_id === id)?.name ?? id;
  }

  async _loadConvs() {
    const res = await this.hass.callWS({
      type: "litellm_assist/conversations",
      action: "list",
    });
    this._convs = res.conversations;
  }

  async _openConv(id) {
    const res = await this.hass.callWS({
      type: "litellm_assist/conversations",
      action: "get",
      conversation_id: id,
    });
    this._conv = res.conversation;
    this._error = "";
    this._scrollEnd();
  }

  async _newConv(mode) {
    const useMode = mode || "chat";
    const res = await this.hass.callWS({
      type: "litellm_assist/conversations",
      action: "create",
      data: {
        mode: useMode,
        model: this._model,
        agent_id: useMode === "assist" ? this._agent : undefined,
      },
    });
    this._conv = res.conversation;
    this._convs = [ { ...res.conversation, messages: undefined }, ...this._convs ];
    this._error = "";
  }

  async _setMode(mode) {
    if (!this._conv) {
      await this._newConv(mode);
      return;
    }
    this._conv = {
      ...this._conv,
      mode,
      agent_id: mode === "assist" ? this._agent : this._conv.agent_id,
    };
    await this.hass.callWS({
      type: "litellm_assist/conversations",
      action: "update",
      conversation_id: this._conv.id,
      data: { mode, agent_id: this._conv.agent_id },
    });
  }

  async _send() {
    const text = this._draft.trim();
    const mode = this._conv?.mode || "chat";
    if (!text || this._streaming || this._assistBusy) return;
    if (mode === "chat" && !this._model) {
      this._error = "No model selected";
      return;
    }
    if (mode === "assist" && !this._agent) {
      this._error = "No Assist agent selected";
      return;
    }
    if (!this._conv) await this._newConv(mode);
    const conv = this._conv;
    const draft = text;
    this._draft = "";
    this._error = "";
    conv.messages = [
      ...(conv.messages || []),
      { role: "user", content: draft, ts: new Date().toISOString() },
    ];
    if (conv.title === "New chat") conv.title = draft.slice(0, 40);
    this._streamText = "";
    this._scrollEnd();

    if (mode === "assist") {
      this._assistBusy = true;
      this._scrollEnd();
      try {
        const result = await this.hass.callWS({
          type: "litellm_assist/assist_process",
          conversation_id: conv.id,
          agent_id: this._agent,
          text: draft,
        });
        conv.messages.push({
          role: "assistant",
          content: result.response?.speech?.plain?.speech ?? "(no answer)",
          ts: new Date().toISOString(),
          agent_id: this._agent,
        });
        await this._loadConvs();
      } catch (e) {
        this._error = e.message || String(e);
      } finally {
        this._assistBusy = false;
        this._scrollEnd();
      }
      return;
    }

    this._streaming = true;
    this._scrollEnd();

    try {
      this._unsub = await this.hass.connection.subscribeMessage(
        (event) => this._onEvent(event),
        {
          type: "litellm_assist/stream",
          conversation_id: conv.id,
          text: draft,
          model: this._model,
        }
      );
    } catch (e) {
      this._error = e.message || String(e);
      this._streaming = false;
    }
  }

  _onEvent(event) {
    if (event.type === "delta") {
      this._streamText += event.content;
      this._scrollEnd();
    } else if (event.type === "usage") {
      this._lastUsage = event;
    } else if (event.type === "cancelled") {
      this._finishStream(true);
    } else if (event.type === "done") {
      this._finishStream(false);
    }
  }

  async _finishStream(cancelled) {
    this._streaming = false;
    if (this._unsub) {
      try { this._unsub(); } catch (_) {}
      this._unsub = null;
    }
    if (this._streamText) {
      this._conv.messages.push({
        role: "assistant",
        content: this._streamText,
        ts: new Date().toISOString(),
        model: this._model,
      });
    }
    this._streamText = "";
    if (!cancelled) await this._loadConvs();
    this._scrollEnd();
  }

  async _stop() {
    if (!this._conv) return;
    await this.hass.callWS({
      type: "litellm_assist/cancel_stream",
      conversation_id: this._conv.id,
    });
    // result arrives via subscription; _finishStream called from done/cancelled
  }

  _scrollEnd() {
    requestAnimationFrame(() => {
      const el = this.renderRoot?.querySelector(".msgs");
      if (el) el.scrollTop = el.scrollHeight;
    });
  }

  _keyDown(ev) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      this._send();
    }
  }

  _bubble(msg, streaming) {
    return html`<div class="row ${msg.role}">
      <div class="bubble">
        ${streaming
          ? html`${msg.content}<span class="cursor"></span>`
          : unsafeHTMLLite(mdLite(msg.content))}
      </div>
    </div>`;
  }

  render() {
    if (!this.hass) return html``;
    const conv = this._conv;
    const mode = conv?.mode || "chat";
    const msgs = conv?.messages ?? [];
    const streamingMsg = this._streaming
      ? { role: "assistant", content: this._streamText }
      : null;
    const busy = this._streaming || this._assistBusy;

    return html`
      <div class="wrap" style=${this._heightStyle()}>
        <header>
          <span class="title">${this.config.title}</span>
          <select
            class="mode"
            .value=${mode}
            @change=${(e) => this._setMode(e.target.value)}
            ?disabled=${busy}
          >
            <option value="chat" ?selected=${mode === "chat"}>💬 Chat</option>
            <option value="assist" ?selected=${mode === "assist"}>🏠 Assist</option>
          </select>
          ${mode === "chat"
            ? html`<select
                .value=${this._model}
                @change=${(e) => (this._model = e.target.value)}
                ?disabled=${busy}
              >
                ${this._models.map(
                  (m) => html`<option value=${m} ?selected=${m === this._model}>${m}</option>`
                )}
              </select>`
            : html`<select
                .value=${this._agent}
                @change=${(e) => (this._agent = e.target.value)}
                ?disabled=${busy}
              >
                ${this._agents.map(
                  (a) =>
                    html`<option
                      value=${a.entity_id}
                      ?selected=${a.entity_id === this._agent}
                    >
                      ${a.name}
                    </option>`
                )}
              </select>`}
          <button
            class="iconbtn"
            title="New chat"
            @click=${() => this._newConv()}
            ?disabled=${busy}
          >
            ＋
          </button>
        </header>

        <div class="msgs">
          ${msgs.length === 0 && !streamingMsg && !this._assistBusy
            ? html`<div class="empty">${this.config.welcome ?? "Ask anything…"}</div>`
            : nothing}
          ${msgs.map((m) => this._bubble(m, false))}
          ${streamingMsg ? this._bubble(streamingMsg, true) : nothing}
          ${this._assistBusy
            ? html`<div class="row assistant">
                <div class="bubble thinking">🏠 thinking…</div>
              </div>`
            : nothing}
        </div>

        ${this._error ? html`<div class="error">${this._error}</div>` : nothing}

        <div class="composer">
          <button
            class="iconbtn"
            title=${this._streaming ? "Stop" : "New chat"}
            @click=${this._streaming ? this._stop : () => this._newConv()}
            ?disabled=${this._assistBusy}
          >
            ${this._streaming ? "⏹" : "＋"}
          </button>
          <textarea
            rows="1"
            placeholder="Message…"
            .value=${this._draft}
            @input=${(e) => (this._draft = e.target.value)}
            @keydown=${this._keyDown}
          ></textarea>
          <button
            class="iconbtn"
            title="Send"
            @click=${this._send}
            ?disabled=${busy || !this._draft.trim()}
          >
            ➤
          </button>
        </div>
      </div>
    `;
  }

  _heightStyle() {
    const h = this.config.height;
    if (h === "full") {
      // Fill the host (panel views); grid views fall back to min-height.
      return "--lac-height: 100%";
    }
    return `--lac-height: ${typeof h === "number" ? h : 560}px`;
  }
}

/* unsafeHTML without lit/directives: render via template element is overkill;
   we build trusted HTML from escaped input only, so use innerHTML through
   a tiny helper returning TemplateResult via html() with unsafeHTML-like
   static array is complex — instead use `unsafeHTML`-free approach:
   render markdown into a span via `html` with result of a custom directive
   is not available, so we fall back to a wrapper that sets innerHTML. */

function unsafeHTMLLite(htmlString) {
  // We rely on mdLite having escaped all input; the only tags present are ours.
  return html`<span class="md" .innerHTML=${htmlString}></span>`;
}

customElements.define("litellm-assist-chat", LiteLLMAssistChat);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "litellm-assist-chat",
  name: "LiteLLM Assist Chat",
  description: "Chat with your LiteLLM models",
});
