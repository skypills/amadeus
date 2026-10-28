from .applications import application_tool, launch_application
from .bootstrap import build_registry
from .notifications import notification_tool, send_notification
from .registry import Tool, ToolError, ToolRegistry
from .system_actions import (
    clipboard_tool,
    copy_to_clipboard,
    get_volume,
    media_control,
    media_tool,
    open_url,
    open_url_tool,
    screenshot_tool,
    set_volume,
    take_screenshot,
    volume_tools,
)
from .system_info import collect_system_info, system_info_tool
from .web_search import (
    SearchResult,
    WebSearch,
    WebSearchError,
    parse_ddg_html,
    render_results,
    render_sources,
    web_search_tool,
)

__all__ = [
    "Tool",
    "ToolError",
    "SearchResult",
    "ToolRegistry",
    "application_tool",
    "clipboard_tool",
    "copy_to_clipboard",
    "build_registry",
    "collect_system_info",
    "get_volume",
    "launch_application",
    "media_control",
    "media_tool",
    "open_url",
    "open_url_tool",
    "notification_tool",
    "screenshot_tool",
    "send_notification",
    "set_volume",
    "WebSearch",
    "WebSearchError",
    "system_info_tool",
    "take_screenshot",
    "parse_ddg_html",
    "render_results",
    "render_sources",
    "volume_tools",
    "web_search_tool",
]
