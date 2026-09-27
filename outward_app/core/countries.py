from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QLocale


FALLBACK_COUNTRY_BY_NEEDLE: dict[str, tuple[str, ...]] = {
    "DE": ("germany", "deutsch", "frankfurt", "berlin"),
    "US": ("oregon", "united", "usa", "america", "us-"),
    "SG": ("singapore", "sg-"),
    "NL": ("amsterdam", "netherlands", "dutch", "nl-"),
}


def normalize_country_code(code: str | None) -> str:
    code = (code or "").strip().upper()
    if not code:
        return ""
    country = QLocale.codeToCountry(code)
    if country == QLocale.Country.AnyCountry:
        return ""
    return QLocale.countryToCode(country).upper()


@lru_cache(maxsize=1)
def country_options() -> tuple[tuple[str, str], ...]:
    countries: dict[str, str] = {}
    for locale in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript, QLocale.Country.AnyCountry):
        country = locale.country()
        if country == QLocale.Country.AnyCountry:
            continue
        code = QLocale.countryToCode(country).upper()
        if not code or code in countries:
            continue
        name = QLocale.countryToString(country) or code
        countries[code] = name
    return tuple(sorted(countries.items(), key=lambda item: item[1].casefold()))


def country_label(code: str) -> str:
    code = normalize_country_code(code)
    if not code:
        return "Auto / Unknown"
    country = QLocale.codeToCountry(code)
    name = QLocale.countryToString(country) or code
    return f"{code} {name}"


def guess_country_code(*parts: str) -> str:
    text = " ".join(part or "" for part in parts).lower()
    for code, needles in FALLBACK_COUNTRY_BY_NEEDLE.items():
        if any(needle in text for needle in needles):
            return code
    return ""
