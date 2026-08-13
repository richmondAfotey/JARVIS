"""
Contacts address book (Phase 32) - lets JARVIS resolve names to numbers.

When the user says "message Mummy", JARVIS has no idea what number that is
unless there is an address book. This module provides:

    * save_contact     - add or update a contact (name + phone/email)
    * list_contacts    - show everyone in the book
    * forget_contact   - remove a contact by name
    * resolve_recipient() - helper used by send_message to turn a name
                            into a real number or email address.

Contacts are stored in `data/contacts.json` next to the SQLite database,
and are read/written defensively (corrupt/missing files fall back to an
empty book).
"""

from __future__ import annotations

import json

from config import settings
from tools.base import Tool, ToolError


def _contacts_file():
    return settings.data_dir / "contacts.json"


def load_contacts() -> dict[str, dict]:
    """Load the address book. Returns {name(lower): {name, phone, email}}."""
    path = _contacts_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip().lower(): raw[k] for k, v in raw.items() if isinstance(v, dict)}


def save_contacts(book: dict[str, dict]) -> None:
    """Atomically write the address book to disk."""
    path = _contacts_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(book, path.open("w", encoding="utf-8"), indent=2, ensure_ascii=False)


def resolve_recipient(value: str) -> str:
    """Turn a contact *name* (or raw number/email) into a usable recipient.

    Returns the raw value unchanged when it already looks like an email or
    a phone number. Otherwise looks the name up in the address book and
    returns the contact's phone (falling back to email). Raises ToolError
    when the name is unknown (listing known names to help).
    """
    v = (value or "").strip()
    if not v:
        raise ToolError("Please give me a recipient (email, phone or contact name).")

    book = load_contacts()
    entry = book.get(v.lower())
    if entry is not None:
        number = (entry.get("phone") or "").strip()
        email = (entry.get("email") or "").strip()
        if number:
            return number
        if email:
            return email
        raise ToolError(f"Contact {entry.get('name', v)!r} has no phone or email saved.")

    if not v.replace("+", "").replace(" ", "").replace("-", "").replace(
        "(", ""
    ).replace(")", "").replace(".", "").isdigit() and "@" not in v:
        known = ", ".join(sorted(entry["name"] for entry in book.values() if entry.get("name")))
        hint = f" Known contacts: {known}." if known else ""
        raise ToolError(f"{value!r} is not a number or email, and is not in the "
                        f"address book.{hint} Try 'save_contact' first.")
    return v


class SaveContactTool(Tool):
    name = "save_contact"
    description = (
        "Add or update a contact in the address book (a name mapped to a "
        "phone number and/or email), so later requests like 'message "
        "Mummy' work. Call this whenever the user tells you a name and "
        "number/email to reach."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The contact's name, e.g. Mummy."},
            "phone": {"type": "string", "description": "Phone number with country code, e.g. +233XXXXXXXXX."},
            "email": {"type": "string", "description": "Email address (optional if phone given)."},
        },
        "required": ["name"],
    }

    def execute(self, args: dict) -> str:
        name = ((args or {}).get("name") or "").strip()
        phone = ((args or {}).get("phone") or "").strip()
        email = ((args or {}).get("email") or "").strip()
        if not name:
            raise ToolError("Please give the contact a name.")
        if not phone and not email:
            raise ToolError("Give the contact a phone number or an email.")

        book = load_contacts()
        key = name.lower()
        existing = book.get(key, {})
        book[key] = {
            "name": existing.get("name") or name,
            "phone": phone or existing.get("phone") or "",
            "email": email or existing.get("email") or "",
        }
        save_contacts(book)
        return f"Saved {book[key]['name']}: phone {book[key]['phone'] or '-'}, email {book[key]['email'] or '-'}."


class ListContactsTool(Tool):
    name = "list_contacts"
    description = "List everyone in the JARVIS address book."
    parameters = {"type": "object", "properties": {}}

    def execute(self, args: dict) -> str:
        book = load_contacts()
        entries = sorted(
            (entry for entry in book.values() if entry.get("name")),
            key=lambda e: e["name"].lower(),
        )
        if not entries:
            return "Your address book is empty. Use 'save_contact' to add someone."
        lines = [f"{len(entries)} contact(s):"]
        for entry in entries:
            target = entry.get("phone") or entry.get("email") or "-"
            lines.append(f"* {entry['name']} - {target}")
        return "\n".join(lines)


class ForgetContactTool(Tool):
    name = "forget_contact"
    description = "Remove a contact from the address book by name."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The contact name to remove."}
        },
        "required": ["name"],
    }

    def execute(self, args: dict) -> str:
        name = ((args or {}).get("name") or "").strip()
        if not name:
            raise ToolError("Tell me the contact name to forget.")
        book = load_contacts()
        entry = book.pop(name.lower(), None)
        if entry is None:
            raise ToolError(f"No contact named {name!r} in the address book.")
        save_contacts(book)
        return f"Forgot contact {entry.get('name', name)}."


def register_contacts_tools(registry) -> None:
    """Register the Phase 32 address-book tools on a registry."""
    registry.register(SaveContactTool())
    registry.register(ListContactsTool())
    registry.register(ForgetContactTool())