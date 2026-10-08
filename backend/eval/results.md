# Prototype evaluation results

These numbers are **measured on this prototype**, from scripted scenarios.

- **Funnel completion** = the scenario reached a `complete` lead. The script answers
  follow-ups from a fixed list, auto-selects the top-ranked listing, and submits
  contact + address + consent. It shows the agent never gets stuck; it is **not** a
  human conversion rate (real users can drop off at any step).
- **Quality-checked lead** = funnel completed **and** the chosen provider's trade is
  confirmed (Google type or business name) **and** it is not flagged as a likely
  national call center. This is a proxy for "would a provider act on it", not
  provider acceptance.

- DeepSeek configured: `True` (model `deepseek-flash`)
- Places search mode: `live`
- Scenarios: 10
- Category match: 100% (10/10)
- Urgency in expected set: 100% (10/10)
- Escalation correctness: 100% (10/10)
- Funnel completion (all scenarios): 9/10
- Funnel completion (non-emergency scenarios): 9/9
- Quality-checked leads (non-emergency scenarios): 9/9
- Non-emergency scenarios that reached provider search: 9/9

Fallback fixture was not updated.

| Scenario | Category | Cat OK | Urgency | Esc | Qs | Turns | Providers | Source | Lead | Chosen provider | Trade confirmed | Quality OK |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Basement flooding | water_damage | True | same_day | False | 2 | 4 | 10 | google_places | complete | ATEX Emergency Water Damage Restoration | True | True |
| Leaking sink | plumbing | True | same_day | False | 2 | 4 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |
| AC not cooling | hvac | True | same_day | False | 1 | 3 | 10 | google_places | complete | RedHome HVAC Services | True | True |
| Roof leak | roofing | True | same_day | False | 3 | 5 | 10 | google_places | complete | LOA Construction and Austin Roofing | True | True |
| Sparking outlet | electrical | True | emergency | False | 3 | 5 | 10 | google_places | complete | DC Electric | True | True |
| Clogged toilet | plumbing | True | same_day | False | 2 | 4 | 10 | google_places | complete | Magic Plumbing ATX | True | True |
| Broken water heater | plumbing | True | same_day | False | 4 | 6 | 10 | google_places | complete | Beyond Wow Plumbing & Drains | True | True |
| Pest infestation | pest_control | True | within_week | False | 3 | 5 | 10 | google_places | complete | X Out Pest Services | True | True |
| Vague home problem | electrical | True | emergency | False | 3 | 5 | 10 | google_places | complete | DC Electric | True | True |
| Emergency gas smell | plumbing | True | emergency | True | 0 | 1 | 0 | none | safety_escalated |  | False | False |

## Per-scenario notes

- **Basement flooding**: stage `lead_ready`; missing required: `none`; LLM fallback used: `True`
- **Leaking sink**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **AC not cooling**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **Roof leak**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **Sparking outlet**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **Clogged toilet**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **Broken water heater**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **Pest infestation**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **Vague home problem**: stage `lead_ready`; missing required: `none`; LLM fallback used: `False`
- **Emergency gas smell**: stage `safety_escalated`; missing required: `customer_name,customer_phone_or_email,selected_provider,consent_to_share,service_address`; LLM fallback used: `False`
