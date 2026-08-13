"""AI provider implementations.

Each provider is a class implementing `BaseProvider`. New providers
(e.g. Gemini, local LLMs) can be added here without touching the rest
of the application - the rest of the app only talks to `ai.brain.Brain`.
"""
