# Cherry Head Team Meeting: 2026-09-04

**Attendees:** Eric Helbush, Dan (djras).
**Source:** Zoom, "Eric Helbush's Personal Meeting Room", 2026-09-04 10:01-10:31 AM PT (UUID 625450E4-D623-49BB-881C-F73FC4E836D9).

## Decisions

- **FIX: partial liquidation.** Sell enough FIX to fund the new basket, keep ~$20K of the position. Books a short-term loss against the year's ~$12K of realized short-term gains. Do not repurchase FIX before 10/5/26 (wash sale).
- **AVGO: hold.** Weak sell signal (~9th percentile in Eric's model, comparable in Dan's), and the tax analysis showed no losses available to shelter its ~$84K long-term gain. No delevering for now.
- **Pilot portfolio: approved.** Six Portfolio Builder candidates at ~$10K each. Approved: ANDG (Anderson Group), INFQ (Atom Solutions, quantum computing), LBRX (LB Pharma, LB-102 phase 3), NAVN (Navan), GENB (generative biology / monoclonal antibody), VIA (German transportation/logistics platform). Rejected: PER (crypto exposure), SanDisk (up ~2,000%, overvalued, weak model fit), Sezzle and one other recent-spike name (unsustainable pops, poor timing-model fit). Emily to review the six and confirm.
- Models compared (Eric's dashboard vs Dan's Excel) on APCO/APCA: within 10 percentile points, considered aligned.
- Eric to send Dan Claude setup instructions after the call.

## Execution (same day, 2026-09-04)

| Order | Qty | Amount |
|---|---:|---:|
| SELL FIX | 38 | +$60,937.05 |
| BUY ANDG | 177 | -$9,967.76 |
| BUY INFQ | 780 | -$9,972.30 |
| BUY LBRX | 202 | -$9,958.58 |
| BUY NAVN | 358 | -$9,982.83 |
| BUY GENB | 604 | -$9,966.00 |
| BUY VIA | 400.2864 | -$11,152.00 |

Total deployed $60,999.47; FIX position retained: 13.7794 sh. Basket definition pinned in `data/pilot_portfolio.json`; tracked on the dashboard's Pilot Portfolio tab (v5.7.0).
