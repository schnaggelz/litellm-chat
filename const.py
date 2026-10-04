"""Constants for the LiteLLM Assist integration."""

import logging

DOMAIN = "litellm_assist"

LOGGER_NAME = "litellm_assist"
LOGGER = logging.getLogger(LOGGER_NAME)

# Static asset served to the frontend (registered via hass.http)
STATIC_URL = "/litellm_assist"
STATIC_PATH = "www"
CARD_RESOURCE_URL = f"{STATIC_URL}/litellm-assist-chat.js"

# WS command prefixes
WS_PREFIX = "litellm_assist"
WS_MODELS = f"{WS_PREFIX}/models"
WS_STREAM = f"{WS_PREFIX}/stream"
WS_CANCEL_STREAM = f"{WS_PREFIX}/cancel_stream"
WS_ASSIST_PROCESS = f"{WS_PREFIX}/assist_process"
WS_CONVERSATIONS = f"{WS_PREFIX}/conversations"
WS_PREFS = f"{WS_PREFIX}/prefs"

# Storage
STORAGE_KEY = f"{DOMAIN}/conversations"
STORAGE_VERSION = 1

# Options
CONF_MAX_CONVERSATIONS = "max_conversations"
CONF_PER_USER_HISTORY = "per_user_history"
CONF_DEFAULT_MODE = "default_mode"
CONF_DEFAULT_SYSTEM_PROMPT = "default_system_prompt"

DEFAULT_MAX_CONVERSATIONS = 50
DEFAULT_PER_USER_HISTORY = True
DEFAULT_MODE = "chat"

MODE_CHAT = "chat"
MODE_ASSIST = "assist"

# SSE → WS relay tuning
STREAM_HEARTBEAT_SECONDS = 15.0
MAX_STREAM_LENGTH = 128 * 1024
