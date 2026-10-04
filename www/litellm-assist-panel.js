/**
 * LiteLLM Assist sidebar panel (panel_custom element).
 * Panel pages do not load Lovelace resources and get no automatic HA toolbar,
 * so this module renders ha-top-app-bar-fixed with a hamburger itself and
 * imports the card module (which imports the vendored lit bundle).
 */
import { LitElement, html, css, nothing } from "./lit.js";
import "./litellm-assist-chat.js";

const MENU_ICON =
  "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"; // mdi:menu

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

  _toggleMenu() {
    // Opens the HA drawer overlay on narrow screens; must bubble+compose
    // so the home-assistant root element receives it.
    this.dispatchEvent(
      new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })
    );
  }

  render() {
    if (!this.hass) return html``;
    return html`
      <ha-top-app-bar-fixed .narrow=${this.narrow}>
        ${this.narrow
          ? html`<ha-icon-button
              slot="navigationIcon"
              .path=${MENU_ICON}
              @click=${this._toggleMenu}
            ></ha-icon-button>`
          : nothing}
        <span slot="title">Chat</span>
        <litellm-assist-chat
          .hass=${this.hass}
          .config=${{ title: "Chat", height: "full" }}
        ></litellm-assist-chat>
      </ha-top-app-bar-fixed>
    `;
  }
}

customElements.define("litellm-assist-panel", LiteLLMAssistPanel);
