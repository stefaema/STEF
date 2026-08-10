"""Every legend the screen writes, marked for translation before there is any.

The catalogs do not exist yet, and waiting for them would mean going back over
every template and every label later to find the strings. Marking them now costs
one call each and makes the extraction a build step rather than an archaeology.

English is the source language, so the untranslated path is the identity
function and the screen reads correctly with no catalog installed at all.
"""

from __future__ import annotations

import gettext as _gettext
from pathlib import Path

DOMAIN = "stef"
LOCALES = Path(__file__).resolve().parent.parent / "locales"


def translation(language: str | None = None) -> _gettext.NullTranslations:
    """Return the catalog for a language, or the identity where none is installed."""
    languages = [language] if language else None
    return _gettext.translation(
        DOMAIN, localedir=str(LOCALES), languages=languages, fallback=True
    )


_active = translation()


def gettext(message: str) -> str:
    """Return one legend in the operator's language."""
    return _active.gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    """Return one legend that counts, since not every language pluralises like English."""
    return _active.ngettext(singular, plural, count)


def mark(message: str) -> str:
    """Return the message unchanged, so the extractor sees a string it must collect.

    For legends written where there is no operator yet to translate for, a module
    constant being the usual case. The translation happens at the point of use.
    """
    return message


_ = gettext
