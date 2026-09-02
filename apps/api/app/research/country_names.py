"""A small, deliberately non-exhaustive country name -> ISO 3166-1 alpha-2 map.

Not a geo-database. The avoid-list a traveller states is free text, often in
Russian ("Египет"), while a candidate's country_code is always ISO alpha-2 —
without resolving the name we can't reliably connect the two. Covers common
warm/beach destinations relevant to this product's launch market; extend as
real avoid-list terms surface that this misses.
"""

COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "egypt": "EG",
    "египет": "EG",
    "turkey": "TR",
    "турция": "TR",
    "турцию": "TR",
    "thailand": "TH",
    "таиланд": "TH",
    "vietnam": "VN",
    "вьетнам": "VN",
    "greece": "GR",
    "греция": "GR",
    "spain": "ES",
    "испания": "ES",
    "italy": "IT",
    "италия": "IT",
    "portugal": "PT",
    "португалия": "PT",
    "cyprus": "CY",
    "кипр": "CY",
    "uae": "AE",
    "united arab emirates": "AE",
    "оаэ": "AE",
    "dubai": "AE",
    "дубай": "AE",
    "oman": "OM",
    "оман": "OM",
    "morocco": "MA",
    "марокко": "MA",
    "tunisia": "TN",
    "тунис": "TN",
    "maldives": "MV",
    "мальдивы": "MV",
    "sri lanka": "LK",
    "шри-ланка": "LK",
    "шри ланка": "LK",
    "indonesia": "ID",
    "индонезия": "ID",
    "bali": "ID",
    "бали": "ID",
    "malaysia": "MY",
    "малайзия": "MY",
    "philippines": "PH",
    "филиппины": "PH",
    "mexico": "MX",
    "мексика": "MX",
    "dominican republic": "DO",
    "доминикана": "DO",
    "cuba": "CU",
    "куба": "CU",
    "tanzania": "TZ",
    "танзания": "TZ",
    "zanzibar": "TZ",
    "занзибар": "TZ",
    "seychelles": "SC",
    "сейшелы": "SC",
    "mauritius": "MU",
    "маврикий": "MU",
    "jordan": "JO",
    "иордания": "JO",
    "israel": "IL",
    "израиль": "IL",
    "georgia": "GE",
    "грузия": "GE",
    "armenia": "AM",
    "армения": "AM",
    "azerbaijan": "AZ",
    "азербайджан": "AZ",
    "montenegro": "ME",
    "черногория": "ME",
    "croatia": "HR",
    "хорватия": "HR",
    "albania": "AL",
    "албания": "AL",
    "bulgaria": "BG",
    "болгария": "BG",
    "romania": "RO",
    "румыния": "RO",
    "moldova": "MD",
    "молдова": "MD",
}


def resolve_country_code(term: str) -> str | None:
    key = term.strip().lower()
    if len(key) == 2 and key.isalpha():
        return key.upper()
    return COUNTRY_NAME_TO_ISO2.get(key)


# ISO2 -> canonical English country name, needed to match a destination's row
# inside a Wikipedia visa-requirements table (which lists countries by name).
ISO2_TO_COUNTRY_NAME: dict[str, str] = {
    "MD": "Moldova",
    "RO": "Romania",
    "EG": "Egypt",
    "TR": "Turkey",
    "TH": "Thailand",
    "VN": "Vietnam",
    "GR": "Greece",
    "ES": "Spain",
    "IT": "Italy",
    "PT": "Portugal",
    "CY": "Cyprus",
    "AE": "United Arab Emirates",
    "OM": "Oman",
    "MA": "Morocco",
    "TN": "Tunisia",
    "MV": "Maldives",
    "LK": "Sri Lanka",
    "ID": "Indonesia",
    "MY": "Malaysia",
    "PH": "Philippines",
    "MX": "Mexico",
    "DO": "Dominican Republic",
    "CU": "Cuba",
    "TZ": "Tanzania",
    "SC": "Seychelles",
    "MU": "Mauritius",
    "JO": "Jordan",
    "IL": "Israel",
    "GE": "Georgia",
    "AM": "Armenia",
    "AZ": "Azerbaijan",
    "ME": "Montenegro",
    "HR": "Croatia",
    "AL": "Albania",
    "BG": "Bulgaria",
    "US": "United States",
    "GB": "United Kingdom",
    "DE": "Germany",
    "FR": "France",
    "PL": "Poland",
    "UA": "Ukraine",
    "RU": "Russia",
}

# ISO2 -> demonym, needed to build the Wikipedia page title convention
# "Visa requirements for <Demonym> citizens" (e.g. "Moldovan", not "Moldova").
# Deliberately covers only the passport countries this product realistically
# sees at launch (Moldova/Romania) plus a handful of common others.
ISO2_TO_DEMONYM: dict[str, str] = {
    "MD": "Moldovan",
    "RO": "Romanian",
    "US": "American",
    "GB": "British",
    "DE": "German",
    "FR": "French",
    "IT": "Italian",
    "ES": "Spanish",
    "PT": "Portuguese",
    "PL": "Polish",
    "UA": "Ukrainian",
    "RU": "Russian",
    "TR": "Turkish",
    "GR": "Greek",
    "BG": "Bulgarian",
    "HR": "Croatian",
}


def country_name(code: str) -> str | None:
    return ISO2_TO_COUNTRY_NAME.get(code.strip().upper())


def demonym(code: str) -> str | None:
    return ISO2_TO_DEMONYM.get(code.strip().upper())
