# Home-services lead agent

Internship take-home prototype: a homeowner describes a problem, the app gathers just enough detail, looks up **real** local businesses via Google Places, and produces a **dispatchable lead plus a draft email**. Nothing is sent to a provider.

This is a 10-hour vertical slice, not a production marketplace.

## Demo

[Screen recording](demo/demo.mp4) (about 3.5 minutes): a basement water lead, an HVAC lead, and a gas-smell chat that starts with a 911 warning and later becomes an appliance-repair draft after the homeowner says the gas is shut off and the leak is in the stove. The ZIP shown is 78705. Nothing is sent.

## What it does

1. Interprets a home problem with **Gemini 3.8 Flash** when `GEMINI_API_KEY` is set. DeepSeek (`deepseek-flash`) is the fallback if Gemini is not configured. A keyword classifier runs only if neither key is set, or the model returns unusable JSON.
2. Asks **one** follow-up at a time (up to eight) while a dispatcher still could not brief a contractor. `intake_catalog.py` is optional hints for the model, not a keyword matcher and not a script. It does not ask brand, model, shutoff, or "have you tried…" unless the answer would change the trade, urgency, or safety. Unreadable text is asked about; it is not silently corrected. City/ZIP is a header field, not a chat question.
3. Holds on gas / fire / CO **this turn** (`safety.detect_hazards`: phrase match, then MiniLM embeddings at cosine 0.67) and stops the lead funnel. Release is this-turn model judgment (`safety_confirmed`), not a stored list of "I'm safe" phrases.
4. Searches Google Places (New) Text Search only after the model has named a trade, then ranks with explainable scores. An `unknown` trade is not searched, and it is not rewritten to handyman.
5. Lets the user pick a listing (chat + filterable provider panel).
6. Collects name, phone or email, and street address **only with an explicit consent checkbox**. The Lead form has an editable Problem field; blank means write it from the chat. A typed problem summary wins.
7. Validates a structured lead. The model writes the problem paragraph from the chat; Python wraps the greeting, timing, address, contact line, and signature. "Open in email client" pre-fills it via `mailto:`. The draft exists only when the lead is complete. Nothing is sent by the app.
8. Keeps state across refreshes (session id in `localStorage`, sessions in `backend/data/sessions.json`); **New lead** starts over without reloading.

Python owns stage, the 911 hold, Places search, ranking, consent, and email wrapping. The model judges meaning.

## Quick start

You need Python 3.12+ and Node 20+. On Windows PowerShell, if `npm` is blocked, use `npm.cmd` or run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 1. Keys (backend only)

```bash
cd backend
copy .env.example .env   # Windows
```

Edit `backend/.env`:

```
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GEMINI_MODEL=gemini-3.8-flash
GOOGLE_PLACES_API_KEY=
# auto = MiniLM for safety paraphrases/typos; off = phrase lists only
SAFETY_EMBED_BACKEND=auto
```

Never put keys in the frontend or commit `.env`.

With `GEMINI_API_KEY` set, intake uses Gemini through that OpenAI-compatible endpoint (`gemini-3.8-flash` by default). Otherwise it uses DeepSeek. Without either key, the agent still runs using a deterministic keyword classifier. Without `GOOGLE_PLACES_API_KEY` and with an empty fallback fixture, provider search returns no listings (it will **not** invent businesses).

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000 --host 127.0.0.1
```

Health check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health). The JSON field is still named `deepseek_configured`; it is true when **either** Gemini or DeepSeek is configured. `model` is the active model id. The UI chip says **LLM:**.

### 3. Frontend

```bash
cd frontend
npm.cmd install
npm.cmd run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/api` to port 8000.

### 4. Tests and eval

```bash
cd backend
python -m pytest -q
python eval/run_eval.py
python scripts/smoke_llm.py
```

`python eval/run_eval.py --record-fixture` saves a **live** Places response into `fixtures/fallback_providers.json` for offline demos. That file starts empty on purpose. Places terms restrict caching; treat this as **dev-only**.

## Architecture

Probabilistic AI reasoning is isolated from deterministic orchestration.

```mermaid
flowchart LR
  user[Homeowner] --> ui[React UI]
  ui --> api[FastAPI]
  api --> agent[agent.py orchestrator]
  agent --> safety[safety.py phrases plus MiniLM]
  agent --> catalog[intake_catalog.py hints]
  agent --> llm[llm.py Gemini or DeepSeek JSON]
  agent --> places[places.py Google Places]
  agent --> rank[ranking.py scores]
  agent --> lead[lead.py validate plus email wrap]
  catalog -.->|optional hints after a trade| llm
  llm -.->|validated LLMAnalysis| agent
  places -.->|Provider listings| rank
```

| The LLM may | Application code must |
|---|---|
| Interpret the problem | Own conversation `Stage` |
| Guess category/urgency with confidence | Validate with Pydantic |
| Extract facts and **one** next question | Cap questions at 8; drop redundant, contact, and location questions; merge facts |
| Use catalog hints for the current trade | Inject example jobs after a category is known. Never skip the model because of a catalog hint |
| Leave the trade `unknown` when several could fit | Refuse to search, and do not substitute handyman |
| Judge whether this message clears a 911 hold | Hold on this-turn `detect_hazards` (phrases, then MiniLM). Never skip 911 copy |
| Write the email's problem paragraph from the chat | Wrap greeting, timing, address, contact, and signature. Draft only when the lead is complete |
| | Call Places; never let the model name businesses |
| | Rank with points + reason strings |
| | Gate the lead on required fields + consent |

### API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | `deepseek_configured` (any LLM key), active `model`, and `live` vs `fallback` search |
| `POST` | `/api/sessions` | Create a session + greeting |
| `GET` | `/api/sessions/{id}` | Full state for the UI (used to restore after refresh) |
| `POST` | `/api/sessions/{id}/messages` | One user turn |
| `POST` | `/api/sessions/{id}/location` | Set city/ZIP from the header field |
| `POST` | `/api/sessions/{id}/providers/search` | Manual panel search |
| `POST` | `/api/sessions/{id}/select` | Choose a listing |
| `POST` | `/api/sessions/{id}/contact` | Contact + address + consent → lead/email |

Sessions live in a process dict and are written to `backend/data/sessions.json` after every turn (gitignored, contains PII). A per-session lock serializes concurrent requests. This is single-process demo persistence, not multi-worker safe.

## Conversation stages

`gathering` → (optional) `need_location` → `searching` → `showing_providers` or `no_results` → `collecting_contact` → `lead_ready`

`safety_escalated` is a hard stop for gas leak, active fire/smoke, or carbon monoxide. The hold is this turn's `safety.detect_hazards`: affirmed phrases first (light typo tolerance, so `gass` can match), then MiniLM cosine against those phrases when `SAFETY_EMBED_BACKEND` is not `off` (`MIN_COSINE` 0.67). Negation is applied first, so `I no longer smell gas` does not hold. `The gas stove will not light` stays below the hazard threshold. Sparking outlets and floodwater near electrical equipment add caution text and force **emergency** urgency but still allow finding an electrician / water-damage provider.

Release is a separate this-turn call, `confirm_household_safe`. The model sets `safety_confirmed` from the meaning of the latest message. There is no stored list of acceptable wording. If no LLM is configured, or that call fails, the hold stays.

Follow-ups: the configured model classifies the job whenever a key is set. The catalog is injected as optional hints — not a keyword match, not an embedding retrieval, and not a questionnaire. The model writes the one question and decides what is already answered. It asks about an unreadable stretch instead of guessing a correction. Niche or mixed-trade work should stay `unknown` (or ignore the hint list) rather than being forced into handyman.

## Provider matching

Search runs only after the model has named a trade. While the category is `unknown`, the conversation stays in gathering and does not call Places.

Deterministic score, then top listings:

- +3 category `primaryType` match, **or** +2 if the business name confirms the trade (Google types most restoration, roofing, and HVAC shops as `general_contractor`, so the name is often the only signal)
- +2 phone on the listing
- +1 website
- +0–2 Bayesian Google rating (prior 3.5 / 10 reviews) — **listing signal, not a quality claim**
- +1 address contains the requested city or ZIP
- −2 for a no-address listing whose phone area code matches none of the locally addressed results (likely a national lead-gen call center)

Service-area businesses are kept (`includePureServiceAreaBusinesses: true`) and labeled **service area not confirmed**.

Field mask (cost control): `id, displayName, formattedAddress, nationalPhoneNumber, websiteUri, googleMapsUri, rating, userRatingCount, primaryType, primaryTypeDisplayName, businessStatus, pureServiceAreaBusiness`.

Phone and website fields are a higher Places SKU. Only `OPERATIONAL` listings are shown.

**Attribution:** listings are Google data. The panel includes a “Powered by Google” note. Opening Maps uses the listing’s `googleMapsUri`.

## Lead completeness

Required: known category (not `unknown`), urgency, city or ZIP, service address, a selected provider whose listing matches the trade and has a phone, website, or Maps link, customer name, phone **or** email, `consent_to_share=true`, and a problem summary.

An empty stored summary is filled from the chat when a provider is selected or contact exists (`lead.py` calls `draft_problem_paragraph`). On the Lead form, a typed Problem wins; leaving it blank means write from the chat. A blank summary does not by itself block the lead when the chat can supply one.

Optional: extra fact dictionary.

Statuses: `complete` | `incomplete` | `safety_escalated`.

The email draft is written only for a complete lead. The model writes the problem paragraph from the transcript. Python adds the greeting, the timing sentence, the service address, the contact line, and the signature. Nothing is sent.

## Assumptions and tradeoffs

- Default demo geography is **Austin, TX**, but any city/ZIP the user (or panel) supplies is used in the text query.
- “Nearby” is **query-scoped**, not haversine distance. There is no geocoding step in this slice.
- A Google listing is **not** proof of license, insurance, availability, or service area.
- JSON mode is requested on the active model (Gemini or DeepSeek). If the model rejects `response_format`, the client retries without it, then validates, then falls back to keywords.
- A JSON file is enough persistence for a local demo; it is not a database.
- The fallback fixture is empty until you record a live response. Empty results are preferred over fictional plumbers.
- Email is a draft only. Google Places has **no business email field**, so "Open in email client" leaves To blank unless an address can be read off the listing; the user sends it themselves, or calls.
- Service address is required: a contractor cannot act on a lead without knowing where to go.
- 911 release depends on the model. With no key, a hazard hold cannot be cleared by wording alone.

## Evaluation (measured on this machine)

Command: `python eval/run_eval.py`. Full table: [backend/eval/results.md](backend/eval/results.md).

The numbers below are a historical funnel run: **live DeepSeek (`deepseek-flash`) + live Google Places**, **20 scenarios**, recorded before catalog embeddings were removed. The live default is now Gemini when `GEMINI_API_KEY` is set. Re-run `python eval/run_eval.py` for a current table.

| Proxy | Result | Meaning |
|---|---|---|
| Category match | **20/20** | Including want≠pest, ants→pest, garage door→handyman, smart lock→handyman |
| Urgency in expected set | **19/20** | Flickering lights came back `flexible` on a path that skipped the model; that skip is gone |
| Escalation correctness | **20/20** | Gas and CO held; “not everyone is safe” did not clear; negated gas did not trigger |
| Edge-case checks | **20/20** | 911 copy, no search on hold, caution vs hold, lead lock |
| Funnel completion (non-emergency) | **17/17** | The three emergencies correctly never completed |
| Quality-checked leads (non-emergency) | **17/17** | Chosen provider's trade confirmed and not flagged as a call center |

How to read these honestly:

- **Funnel completion is not conversion.** The script answers follow-ups from a fixed list, auto-selects the top listing, and submits contact details. It proves the agent never gets stuck; real users can still drop off at any step.
- **Quality-checked is not acceptance.** It checks that the lead went to a business that plausibly does this work. Whether a provider would take the job needs a provider-side accept/decline loop.
- The model occasionally fails a turn (network or invalid JSON). The keyword fallback kept those scenarios moving, which is the point of the fallback.

Sample **success path** (the brief's example, ZIP 78717): "Water started coming into my basement last night after the storm" → at most one follow-up if it would change safety or dispatch (for example whether water is near electrical) → live water-restoration listings → select → contact + address + consent → JSON lead + first-person draft email. The catalog does not script a second question such as sump-pump detail.

Sample **safety path** (gas smell): first message → this-turn phrase/MiniLM hold + model-written 911 copy → `safety_escalated` → no provider search. A later message clears the hold only if this turn's model sets `safety_confirmed`.

## What to build next for production

- Persist sessions and leads in Postgres instead of a JSON file; encrypt PII at rest.
- Geocode ZIP → lat/lng and rank by distance / service radius.
- License, insurance, and “accepts this job type” checks with a provider network, not Places alone.
- Provider-side accept/decline loop and true conversion analytics.
- Streaming tokens, observability, rate limits, and abuse controls.
- Human review for safety-escalated transcripts.
- Proper PII retention, consent logging, and Places caching policy review.
- Auth so a homeowner can return to a draft from another device.
- Instrument the real funnel (message → search → select → contact) to measure human drop-off, not scripted completion.

## Project layout

```
backend/app/     FastAPI, models, agent, llm, intake_catalog, safety, safety_embed, places, ranking, lead
backend/eval/    scenarios.json, run_eval.py, results.md
backend/tests/
frontend/src/  React + Vite + Tailwind
```

Dependencies are only those in `backend/requirements.txt` and `frontend/package.json`.
