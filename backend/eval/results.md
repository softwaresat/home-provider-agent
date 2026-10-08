# Prototype evaluation results

20 scripted scenarios (obvious catalog jobs and edge cases), measured live against this prototype.

- **Funnel completion** = the scenario reached a `complete` lead. The script answers
  follow-ups from a fixed list, auto-selects the top-ranked listing, and submits
  contact + address + consent. It is **not** a human conversion rate.
- **Quality-checked lead** = funnel completed **and** the chosen provider's trade is
  confirmed **and** it is not flagged as a likely national call center.
- **Edge OK** = caution vs 911-hold, 911 copy on emergencies, no search during a hold,
  and completed-lead lock all matched the scenario.

- DeepSeek configured: `True` (model `deepseek-flash`)
- Places search mode: `live`
- Scenarios: 20
- Category match: 100% (20/20)
- Urgency in expected set: 95% (19/20)
- Escalation correctness: 100% (20/20)
- Edge-case checks: 100% (20/20)
- Funnel completion (all scenarios): 17/20
- Funnel completion (non-emergency scenarios): 17/17
- Quality-checked leads (non-emergency scenarios): 17/17
- Non-emergency scenarios that reached provider search: 17/17

Fallback fixture was not updated.

| Scenario | Category | Cat OK | Urgency | Esc | Edge | Qs | Turns | Providers | Source | Lead | Chosen provider | Trade | Quality |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Kitchen sink leaking | plumbing | True | same_day | False | True | 1 | 3 | 10 | google_places | complete | BenjaminBL Plumbing | True | True |
| Clogged downstairs toilet | plumbing | True | same_day | False | True | 0 | 2 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |
| No hot water | plumbing | True | same_day | False | True | 1 | 3 | 10 | google_places | complete | Beyond Wow Plumbing & Drains | True | True |
| AC not cooling | hvac | True | same_day | False | True | 1 | 3 | 10 | google_places | complete | RedHome HVAC Services | True | True |
| Garbage disposal jammed | plumbing | True | flexible | False | True | 0 | 2 | 10 | google_places | complete | BenjaminBL Plumbing | True | True |
| Garage door opener stuck | handyman | True | flexible | False | True | 0 | 2 | 10 | google_places | complete | Mr. Handyman of South Austin/Lakeway | True | True |
| Dishwasher will not start | appliance_repair | True | same_day | False | True | 0 | 2 | 10 | google_places | complete | VZ Tech PRO Appliance repair & Handyman services | True | True |
| Bed bugs | pest_control | True | flexible | False | True | 0 | 2 | 10 | google_places | complete | The Bug Master | True | True |
| Gutter after hail | roofing | True | same_day | False | True | 1 | 3 | 10 | google_places | complete | LOA Construction and Austin Roofing | True | True |
| Lights flickering | electrical | True | flexible | False | True | 1 | 3 | 10 | google_places | complete | DC Electric | True | True |
| I want help with a leaking sink | plumbing | True | same_day | False | True | 1 | 3 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |
| Ants on the kitchen counters | pest_control | True | flexible | False | True | 0 | 2 | 10 | google_places | complete | The Bug Master | True | True |
| Gas smell in the kitchen | unknown | True | n/a | True | True | 0 | 1 | 0 | none | safety_escalated |  | False | False |
| No longer smell gas, sink still leaking | plumbing | True | emergency | False | True | 2 | 4 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |
| Gas smell, then not everyone is safe | unknown | True | emergency | True | True | 0 | 2 | 0 | none | safety_escalated |  | False | False |
| Sparking outlet, no fire | electrical | True | emergency | False | True | 1 | 3 | 10 | google_places | complete | DC Electric | True | True |
| Basement water around outlets | water_damage | True | emergency | False | True | 1 | 3 | 10 | google_places | complete | ATEX Emergency Water Damage Restoration | True | True |
| Carbon monoxide alarm | unknown | True | n/a | True | True | 0 | 1 | 0 | none | safety_escalated |  | False | False |
| Completed leak, then a new roof problem | plumbing | True | same_day | False | True | 1 | 4 | 10 | google_places | complete | Austin's Greatest Plumbing | True | True |
| Smart lock, no catalog entry | handyman | True | flexible | False | True | 2 | 4 | 10 | google_places | complete | Heritage Handyman LLC | True | True |

## Per-scenario notes

- **Kitchen sink leaking**: Obvious plumbing leak; catalog slots mostly in the opening. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Clogged downstairs toilet**: Obvious clog / toilet. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **No hot water**: Obvious water heater. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **AC not cooling**: Obvious HVAC. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Garbage disposal jammed**: Obvious disposal. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Garage door opener stuck**: Obvious handyman / garage door. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Dishwasher will not start**: Obvious appliance. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Bed bugs**: Obvious pest; bed bugs plural. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Gutter after hail**: Obvious roofing / gutter. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Lights flickering**: Obvious electrical / power issue. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **I want help with a leaking sink**: Edge: want must not classify as pest (ant). Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Ants on the kitchen counters**: Edge: ant as a whole word. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Gas smell in the kitchen**: Edge: 911 hold, no search. Stage `safety_escalated`; missing `problem_summary,service_category,customer_name,customer_phone_or_email,selected_provider,consent_to_share,service_address`; fallback `True`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: If you smell gas, leave the home immediately. Do not use lights, appliances, or phones inside. From a safe place, call 911 and your gas utility. I will not look up contractors until you confirm everyone is safe. If you h
- **No longer smell gas, sink still leaking**: Edge: negated gas must not hold. Stage `lead_ready`; missing `none`; fallback `True`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Gas smell, then not everyone is safe**: Edge: not everyone is safe must not clear the hold. Stage `safety_escalated`; missing `service_category,customer_name,customer_phone_or_email,selected_provider,consent_to_share,service_address`; fallback `True`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: If you smell gas, leave the home immediately. Do not use lights, appliances, or phones inside. From a safe place, call 911 and your gas utility. I will not look up contractors until you confirm everyone is safe. If you h
- **Sparking outlet, no fire**: Edge: caution, not a 911 hold. Stage `lead_ready`; missing `none`; fallback `True`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Basement water around outlets**: Edge: flood-electrical caution, still search. Stage `lead_ready`; missing `none`; fallback `True`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
- **Carbon monoxide alarm**: Edge: CO hard stop. Stage `safety_escalated`; missing `problem_summary,service_category,customer_name,customer_phone_or_email,selected_provider,consent_to_share,service_address`; fallback `True`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: A carbon monoxide alarm is an emergency. Get everyone outside into fresh air and call 911. Do not re-enter until emergency services say it is safe. I will not look up contractors until you confirm everyone is safe. If yo
- **Completed leak, then a new roof problem**: Edge: completed lead must not rewrite analysis. Stage `lead_ready`; missing `none`; fallback `False`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: The lead is already complete. You can copy the draft email from the Lead tab. Start a new lead if the problem changed. Nothing has been sent.
- **Smart lock, no catalog entry**: Edge: niche job with no catalog type; model must still intake and search. Stage `lead_ready`; missing `none`; fallback `True`; caution `True`; 911 `True`; no-search `True`; lock `True`.
  Last assistant: Lead is complete. Review the structured lead and draft email on the Lead tab. Nothing has been sent to the provider.
