# Prototype evaluation results

Ten **real-life edge cases**, measured live against this prototype.

- **Funnel completion** = the scenario reached a `complete` lead. The script answers
  follow-ups from a fixed list, auto-selects the top-ranked listing, and submits
  contact + address + consent. It is **not** a human conversion rate.
- **Quality-checked lead** = funnel completed **and** the chosen provider's trade is
  confirmed **and** it is not flagged as a likely national call center.
- **Edge OK** = caution vs 911-hold, 911 copy on emergencies, no search during a hold,
  and completed-lead lock all matched the scenario.

- DeepSeek configured: `True` (model `deepseek-flash`)
- Places search mode: `live`
- Scenarios: 10
- Category match: 100% (10/10)
- Urgency in expected set: 100% (10/10)
- Escalation correctness: 100% (10/10)
- Edge-case checks: 100% (10/10)
- Funnel completion (all scenarios): 7/10
- Funnel completion (non-emergency scenarios): 7/7
- Quality-checked leads (non-emergency scenarios): 7/7
- Non-emergency scenarios that reached provider search: 7/7

Fallback fixture was not updated.

| Scenario | Category | Cat OK | Urgency | Esc | Edge | Qs | Turns | Providers | Source | Lead | Chosen provider | Trade | Quality |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| I want help with a leaking sink | plumbing | True | same_day | False | True | 3 | 5 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |
| Ants on the kitchen counters | pest_control | True | within_week | False | True | 3 | 5 | 10 | google_places | complete | X Out Pest Services | True | True |
| Gas smell in the kitchen | unknown | True | n/a | True | True | 0 | 1 | 0 | none | safety_escalated |  | False | False |
| No longer smell gas, sink still leaking | plumbing | True | same_day | False | True | 4 | 6 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |
| Gas smell, then not everyone is safe | plumbing | True | emergency | True | True | 0 | 2 | 0 | none | safety_escalated |  | False | False |
| Sparking outlet, no fire | electrical | True | emergency | False | True | 2 | 4 | 10 | google_places | complete | DC Electric | True | True |
| Basement water around outlets | water_damage | True | emergency | False | True | 3 | 5 | 10 | google_places | complete | ATEX Emergency Water Damage Restoration | True | True |
| Carbon monoxide alarm | unknown | True | n/a | True | True | 0 | 1 | 0 | none | safety_escalated |  | False | False |
| Ceiling stain after a storm | roofing | True | within_week | False | True | 3 | 5 | 10 | google_places | complete | LOA Construction and Austin Roofing | True | True |
| Completed leak, then a new roof problem | plumbing | True | same_day | False | True | 3 | 6 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |

## Per-scenario notes

- **I want help with a leaking sink**: Substring trap: want must not classify as pest (ant). Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Ants on the kitchen counters**: Real pest intent; ant as a whole word. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Gas smell in the kitchen**: Hard stop. Reply may be model-written; must still tell them to call 911. Stage `safety_escalated`; missing `problem_summary,service_category,customer_name,customer_phone_or_email,selected_provider,consent_to_share,service_address`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: You said you smell gas in the kitchen near the stove, so treat this as an emergency. Get yourself and anyone else in the home outside to fresh air and a safe place away from the building now. Once you are safely away, ca
- **No longer smell gas, sink still leaking**: Negation: do not treat as an active gas emergency. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Gas smell, then not everyone is safe**: Negated safe-phrase must not clear the hold. Stage `safety_escalated`; missing `customer_name,customer_phone_or_email,selected_provider,consent_to_share,service_address`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: You told us there is a gas smell and that not everyone is safe yet, so please treat this as an emergency right now. Get yourself and everyone with you outside and well away from the home immediately, without stopping to 
- **Sparking outlet, no fire**: Caution, not a 911 hold. Should still find an electrician. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Basement water around outlets**: Flood-electrical caution; still allow a restoration/electrical search. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Carbon monoxide alarm**: CO is a hard stop even if the model would rather talk HVAC. Stage `safety_escalated`; missing `problem_summary,service_category,customer_name,customer_phone_or_email,selected_provider,consent_to_share,service_address`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Because your carbon monoxide alarm is going off and everyone is still inside, get everyone to safety now. Move outside into fresh air and away from the home, then call 911 from a safe place. Do not go back inside for any
- **Ceiling stain after a storm**: Ambiguous roof vs interior water. Either trade is acceptable. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Completed leak, then a new roof problem**: After lead_ready, a new problem must not rewrite category or reopen analysis. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: The lead is already complete. You can copy the draft email from the Lead tab. Start a new lead if the problem changed. Nothing has been sent.
