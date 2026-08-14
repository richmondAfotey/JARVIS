"""
Tools package - capabilities JARVIS can call while answering.

Modules:
    * base.py           - the Tool interface and ToolError
    * registry.py       - ToolRegistry + the streaming ToolCallParser
    * builtin.py        - the default offline-safe tools
    * system_control.py - Phase 7 computer control (apps, files, URLs)
    * filesystem.py     - Phase 8 file intelligence (read/list/search/write)
    * web.py            - Phase 10 web search (Tavily) + weather (OpenWeatherMap)
    * notes.py          - Phase 11 notes + reminders (SQLite-backed)
    * documents.py      - Phase 12 document intelligence (PDF/Word/Excel/PPT)
    * vision.py         - Phase 13 screenshot + image analysis (Gemini)
    * memory.py         - Phase 14 long-term memory (remember/recall)
    * scripts.py        - Phase 15 task scripts (advanced automation)
    * updates.py        - Phase 21 self-update check (report only)
    * design.py         - Phase 23 graphic design (posters, suit prototypes,
                          UI wireframes - all rendered locally with Pillow)
    * codeaudit.py      - Phase 24 code security audit + patch (defensive;
                          reviews the user's own software)
    * research.py       - Phase 26 in-app research: search the web + read
                          the top pages and return a digest the model turns
                          into a sourced answer (works with no API key)
    * filesystem.py     - Phase 8/27 files: read/list/search/write,
                          create_folder + write_project (scaffold a whole
                          code project from a file list)
"""

from __future__ import annotations

from tools.base import Tool, ToolError
from tools.registry import ToolRegistry, ToolCallParser


def build_default_registry(database=None, reminders=None) -> ToolRegistry:
    """Create a registry pre-loaded with every built-in tool.

    Args:
        database: optional memory.Database used by notes/reminder tools.
        reminders: optional memory.reminders.ReminderService used by the
            reminder tools to wake the scheduler.
    """
    from tools.builtin import register_defaults
    from tools.codeaudit import register_codeaudit_tools
    from tools.design import register_design_tools
    from tools.documents import register_document_tools
    from tools.filesystem import register_filesystem_tools
    from tools.memory import register_memory_tools
    from tools.notes import register_notes_tools
    from tools.research import register_research_tools
    from tools.scripts import register_scripts_tools
    from tools.system_control import register_system_tools
    from tools.updates import register_update_tools
    from tools.vision import register_vision_tools
    from tools.web import register_web_tools
    from tools.rag import register_rag_tools
    from tools.scheduler import register_scheduler_tools
    from tools.email import register_email_tools
    from tools.chat_search import register_chat_search_tools
    from tools.export import register_export_tools
    from tools.mood import register_mood_tools
    from tools.plugins import register_plugin_tools
    from tools.briefing import register_briefing_tools
    from tools.voice_confirm import register_voice_confirm_tools
    from tools.messaging import register_messaging_tools
    from tools.contacts import register_contacts_tools
    from tools.glasses import register_glasses_tools
    from tools.security_lab import register_security_lab_tools
    from tools.capabilities import register_capability_tools
    from tools.einstein import register_einstein_tools
    from tools.lighting import register_lighting_tools
    from tools.printing import register_printing_tools
    from tools.bedtime import register_bedtime_tools

    registry = ToolRegistry()
    register_defaults(registry)
    register_system_tools(registry)
    register_filesystem_tools(registry)
    register_web_tools(registry)
    register_notes_tools(registry, database=database, reminders=reminders)
    register_document_tools(registry)
    register_vision_tools(registry)
    register_memory_tools(registry, database=database)
    register_scripts_tools(registry, database=database)
    register_update_tools(registry)
    register_design_tools(registry)
    register_codeaudit_tools(registry)
    register_research_tools(registry)
    register_rag_tools(registry)
    register_scheduler_tools(registry)
    register_email_tools(registry)
    register_chat_search_tools(registry)
    register_export_tools(registry)
    register_mood_tools(registry)
    register_plugin_tools(registry)
    register_briefing_tools(registry)
    register_voice_confirm_tools(registry)
    register_messaging_tools(registry)
    register_contacts_tools(registry)
    register_glasses_tools(registry)
    register_security_lab_tools(registry)
    register_capability_tools(registry)
    register_einstein_tools(registry)
    register_lighting_tools(registry)
    register_printing_tools(registry)
    register_bedtime_tools(registry)
    return registry


__all__ = [
    "Tool",
    "ToolError",
    "ToolRegistry",
    "ToolCallParser",
    "build_default_registry",
]
