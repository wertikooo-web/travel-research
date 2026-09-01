# Milestone 1 — Natural-language trip brief

## Goal

Implement only the first user flow:

```text
Home page
↓
User describes a trip in natural language
↓
LLM converts it into a structured TripBrief
↓
User reviews how the system understood the request
↓
User can edit the parsed data
↓
User confirms the brief
```

Do not start destination research in this milestone.

## Scope

Build:

- a simple home page with one large natural-language input;
- optional quick fields for origin, approximate dates, travellers and budget;
- backend endpoint that parses the request with an LLM into a validated schema;
- a confirmation screen showing the interpreted trip brief;
- editable fields;
- confirm/save action;
- error handling for LLM/API/schema failures;
- automated tests for the main parsing scenarios;
- manual browser verification of the full flow.

## Explicit non-goals

Do not build yet:

- destination search;
- flights;
- hotels;
- weather research;
- visa research/crawler;
- scoring;
- destination cards;
- booking;
- payments;
- agent frameworks;
- speculative infrastructure for later milestones.

## UX principle

The main experience must stay conversational. The user should be able to write naturally instead of filling a long form first.

Example input:

> Мы вдвоём из Кишинёва в конце октября. У меня молдавский биометрический паспорт, у девушки румынский. Хотим на море на 8–10 дней, до €3500, минимум 4★, желательно прямой рейс.

The system should extract as much as it can, then let the user review and correct it.

## TripBrief requirements

Use a strict schema. Unknown values must be `null`. Do not infer facts that the user did not provide.

Suggested shape:

```json
{
  "origin": {
    "text": "Chisinau",
    "iata": "RMO"
  },
  "travellers": [
    {
      "id": "traveller_1",
      "type": "adult",
      "citizenships": ["MD"],
      "travel_passport": "MD",
      "passport_type": "biometric"
    },
    {
      "id": "traveller_2",
      "type": "adult",
      "citizenships": ["RO"],
      "travel_passport": "RO",
      "passport_type": "ordinary"
    }
  ],
  "dates": {
    "start": null,
    "end": null,
    "flex_days": null
  },
  "nights": {
    "min": 8,
    "max": 10,
    "preferred": null
  },
  "budget": {
    "currency": "EUR",
    "max_total": 3500,
    "hard_constraint": true
  },
  "flight": {
    "direct_preferred": true,
    "max_connections": null,
    "max_duration_hours": null,
    "preferred_cabin": null
  },
  "hotel": {
    "stars_min": 4,
    "beachfront": null,
    "sea_view": null,
    "meal_min": null
  },
  "weather": {
    "day_temp_min": null,
    "sea_temp_min": null,
    "rain_tolerance": null
  },
  "visa": {
    "easy_required": null
  },
  "preferences": {
    "avoid": [],
    "prefer": []
  }
}
```

This is a starting schema. Keep it simple and do not add fields without a concrete need in Milestone 1.

## Passport model

Passport handling is mandatory from the first milestone.

Moldova is the launch market, and many users may travel with Moldovan passports, Romanian passports, or both.

For each traveller store passport information separately.

Use ISO country codes and support any country in the backend.

In the UI, show quick options first:

- 🇲🇩 Moldova
- 🇷🇴 Romania
- Other
- Several passports

Never infer citizenship from origin, location or language.

If a traveller has multiple passports, keep all available citizenship/passport options. Later visa research will compare entry conditions by passport.

Do not build visa research yet, but the schema must already support it correctly.

## Confirmation screen

After parsing, show a clear screen such as:

**Правильно ли я понял вашу поездку?**

The user must be able to review and edit:

- origin;
- dates and flexibility;
- nights;
- travellers;
- passport(s) for each traveller;
- budget;
- flight preferences;
- hotel preferences;
- beach/sea preferences;
- weather preferences;
- visa convenience preference;
- excluded destinations;
- other stated preferences.

Then provide a confirm action.

Store the confirmed brief separately from the raw user request.

## Required test cases

### Case 1 — mixed MD/RO passports

Input:

> Мы вдвоём из Кишинёва в конце октября. У меня молдавский биометрический паспорт, у девушки румынский. Хотим на море на 8–10 дней, до €3500, минимум 4★, желательно прямой рейс.

Expected:

- two separate travellers;
- traveller 1 has MD passport, biometric;
- traveller 2 has RO passport;
- origin Chisinau/RMO;
- nights 8–10;
- budget EUR 3500;
- minimum hotel 4★;
- direct flight preferred;
- no invented exact dates.

### Case 2 — family

Input:

> Хочу с женой и ребёнком 8 лет куда-нибудь тепло в ноябре. Вылет из Бухареста. У всех румынские паспорта. До €4000.

Expected:

- 2 adults + 1 child aged 8;
- all travellers use RO passports;
- Bucharest origin;
- November represented without invented exact dates;
- EUR 4000 budget.

### Case 3 — sparse request

Input:

> Хочу в Азию примерно на две недели в феврале.

Expected:

- Asia preference/destination region captured;
- duration approximately two weeks if schema supports it;
- February captured;
- budget `null`;
- passports `null`;
- hotel stars `null`;
- exact dates `null`;
- no invented flight or visa preferences.

### Case 4 — dual citizenship

Input:

> У меня молдавский и румынский паспорта.

Expected:

- one traveller;
- both MD and RO retained;
- no citizenship discarded;
- active travel passport can remain `null` if the user did not choose one.

## Technical direction

Preferred V0 stack:

- Next.js + TypeScript frontend;
- Python + FastAPI backend;
- PostgreSQL if persistence is introduced now;
- LLM provider behind a small abstraction, not spread through the app;
- schema validation on both API boundary and LLM structured output.

Keep implementation boring and easy to debug.

Do not introduce LangChain, LangGraph, queues, microservices or autonomous agents for this milestone.

## Suggested API surface for Milestone 1

Keep it minimal. For example:

```text
POST /api/trips
POST /api/trips/{id}/parse
PUT  /api/trips/{id}/brief
POST /api/trips/{id}/confirm
GET  /api/trips/{id}
```

You may simplify this if fewer endpoints are cleaner.

## Development workflow

Before coding:

1. Inspect the current repository state.
2. Propose a short file/change plan.
3. Implement only this milestone.

During implementation:

- keep tasks small;
- do not refactor unrelated code;
- do not add speculative dependencies;
- validate every LLM response against schema;
- preserve raw request and parsed brief separately.

Before declaring completion:

1. Run tests.
2. Run the application.
3. Complete the full user flow manually in the browser.
4. Check error handling.
5. Inspect `git status` and `git diff`.
6. Commit the working state as a dedicated milestone commit.

## Definition of Done

Milestone 1 is complete only when:

1. The project starts successfully.
2. The home page works in a browser.
3. A natural-language request reaches the backend.
4. The LLM returns a schema-valid TripBrief.
5. Multiple travellers are parsed independently.
6. MD / RO / multiple passports work.
7. Missing values remain null instead of being invented.
8. The parsed brief is editable.
9. Edited values are saved.
10. Confirm works.
11. LLM/API errors have a usable UI state.
12. Main scenarios have tests.
13. The complete flow has been manually verified in the browser.
14. `git status` / `git diff` have been inspected.
15. A clean working commit exists.

Do not continue to Milestone 2 automatically.

## Final report expected from the coding agent

When finished, report:

- what was implemented;
- key architecture choices;
- tests run and results;
- browser scenario verified;
- known limitations;
- git status/diff summary;
- commit hash.
