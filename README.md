# Travel Research

AI travel research engine for ordinary travellers.

The product takes a natural-language travel request, converts it into a structured brief, researches suitable destinations, normalizes evidence-backed data, scores options against the traveller's constraints, and returns a personalized shortlist.

## Product hypothesis

Can we produce a travel shortlist useful enough that a normal traveller would seriously consider one or more suggested destinations for booking?

## Core flow

1. User describes a trip in natural language.
2. LLM parses the request into a strict `TripBrief`.
3. User reviews and edits the brief.
4. Research jobs collect destination, flight, weather, visa and hotel data.
5. Deterministic rules evaluate constraints and calculate fit.
6. User receives a personalized shortlist with evidence, trade-offs and estimated trip cost.
7. User can give feedback and trigger a refined research round.

## Important product rules

- Do not invent missing user constraints.
- Unknown values stay `null`.
- Time-sensitive facts must keep source and retrieval timestamp.
- Visa rules are evaluated per traveller and per travel passport.
- Moldova and Romania are priority passport options in the UI, but the data model must support any ISO country code.
- Fit scores are calculated in code, not invented by an LLM.
- V0 is research and decision support only. No booking, payments, CRM or mobile app.

## Initial stack

- Frontend: Next.js + TypeScript
- Backend: Python + FastAPI
- Database: PostgreSQL
- LLM: provider abstraction for GPT / Claude
- Flights later: Duffel
- Weather later: Open-Meteo
- Browser research later: Playwright
- Deploy target: Vercel + Railway

## Development approach

Build vertically and validate each milestone in the browser before moving on.

Current milestone: [Milestone 1](docs/milestone-1.md)
