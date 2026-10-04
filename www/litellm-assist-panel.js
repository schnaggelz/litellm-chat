/**
 * LiteLLM Assist sidebar panel (panel_custom element).
 * Panel pages do not load Lovelace resources, so this module imports
 * the card module (which imports the vendored lit bundle) itself.
 */
import { LitElement, html, css } from "./lit.js";
import "./litellm-assist-chat.js";

class LiteLLMAssistPanel extends LitElement {
  static get properties() {
    return {
      hass: { state: true },
      narrow: { state: true },
      route: { state: true },
    };
  }

  static get styles() {
    return css`
      :host {
        display: block;
        height: 100%;
      }
      litellm-assist-chat {
        display: block;
        height: 100%;
        --lac-height: 100%;
      }
    `;
  }

  render() {
    if (!this.hass) return html``;
    return html`
      <litellm-assist-chat
        .hass=${this.hass}
        .config=${{ title: "Chat", height: "full" }}
      ></litellm-assist-chat>
    `;
  }
}

customElements.define("litellm-assist-panel", LiteLLMAssistPanel);
