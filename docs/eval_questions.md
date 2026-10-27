# Retrieval evaluation questions

These questions are held-out evaluation material, not policy corpus content.
Only ingest `docs/policies/`. All policies describe a fictional demo operator.

## Topics not covered

- Vehicle height limits
- Motorcycle parking
- Bicycle parking

## Questions and expected sources

| ID | Category | Driver question | Expected document(s) | Expected answer facts |
|---|---|---|---|---|
| 1 | Single document | Where can I pay cash for parking? | [01 Lot information](policies/01-lot-information.md) | Lot A kiosk only; Lot B accepts cards/app. Also duplicated in 02, which is an acceptable alternative. |
| 2 | Single document | How much is the weekday early-bird rate at Lot B, and what arrival and departure times qualify? | [02 Pricing](policies/02-pricing-and-rates.md) | $9; enter before 09:00 and leave 15:30–19:00, Monday–Friday. |
| 3 | Single document | Can two cars use my monthly permit at the same time? | [03 Permits](policies/03-permits.md) | Two plates may be listed, but only one registered vehicle may park on the permit at a time. |
| 4 | Single document | How long after my paid time expires do I get an overstay fine, and how much is it? | [04 Enforcement](policies/04-enforcement-and-fines.md) | More than 30 minutes; $25; distinct from entry grace period. |
| 5 | Single document | What does charging cost, and when does the idle fee start? | [05 Accessible and EV](policies/05-accessible-and-ev-parking.md) | $0.35/kWh plus parking; $0.50/min after 15 minutes from session end, capped at $20/session. |
| 6 | Two documents | I have a placard and park for one hour on a weekday in Lot B, outside early-bird eligibility. What do I pay? | [02 Pricing](policies/02-pricing-and-rates.md), [05 Accessible and EV](policies/05-accessible-and-ev-parking.md) | $2.50 hourly base × 50% = $1.25. |
| 7 | Two documents | I got a no-payment fine. How much is it if I pay promptly, and how long do I have to appeal? | [04 Enforcement](policies/04-enforcement-and-fines.md), [06 Disputes](policies/06-lost-tickets-refunds-and-disputes.md) | $45, reduced to $30 within 7 days; appeal within 14 days. |
| 8 | Hybrid | Is A-19 free according to the latest reading, and may I park my petrol car there? | `list_free_slots("A")` and [05 Accessible and EV](policies/05-accessible-and-ev-parking.md) | Determine availability from tool output, report its timestamp; petrol vehicles cannot use charging bays even when free. Do not hardcode occupancy or imply stale readings are real-time. |
| 9 | Unanswerable | What is the maximum vehicle height allowed at Lot B? | None | State that the policies do not specify a height limit; do not invent one. |
| 10 | Different words | The machine billed me twice for the same visit. When should the extra money be back on my card? | [06 Disputes](policies/06-lost-tickets-refunds-and-disputes.md) | Maps to “duplicate charges”; original payment method within 5 business days. |

Score two-document questions for retrieval of both sources, and the hybrid for
both the correct policy and a live tool call. Preserve this set before tuning retrieval.
