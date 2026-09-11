# Cherry Head Team Meeting: 2026-09-11

**Attendees:** Eric Helbush, Dan (djras).
**Source:** Zoom, "Eric Helbush's Personal Meeting Room", 2026-09-11 9:57-10:33 AM PT (UUID A27AA2BD-4C5D-4C58-A807-B75E3AAAED52).

## Context / decisions

- **Hold everything.** ANET is the big winner (up ~120%). Pilot portfolio reviewed on the new dashboard tab: INFQ doing well, the rest in the red but all six still at Buy signals; agreed to give them time. FIX (the kept ~$20K stub) has moved from weak buy to strong buy; glad it was held. AVGO remains a weak sell in both models; still holding.
- **STOCKHISTORY outage confirmed as Microsoft-side.** Dan's Excel feed stopped after 9/4; the dashboard (Yahoo/Schwab) is unaffected. Dan monitors over the weekend; if it persists, move Dan's workbooks to a Python-driven data pull instead of Microsoft's feed.
- **Election positioning discussion.** Polymarket odds: ~50% Democratic sweep, 37% split (R Senate / D House), 13% R sweep. Pharma and renewables seen as beneficiaries of a Dem sweep (already positioned via LLY). No repositioning yet; revisit ahead of November.
- Dan is starting the Claude Code setup from Eric's instructions.
- Next week's regular Friday meeting will likely be cancelled or moved to Wednesday (Dan in Big Timber, MT Thursday-Saturday); Dan to confirm. Dan has a biopsy 9/21.

## Action items

### Dashboard development (executable in this repo)

1. **Buy/Sell signal column on the Performance tab Holdings table** ("if it's a buy or sell, that would be helpful on the holdings page"). Source from the daily screener like the Pilot tab does, with the in-browser fallback for uncovered tickers.
2. **Add the pilot tickers to the normal asset set** ("I'll add this to the normal assets"): ANDG, INFQ, LBRX, NAVN, GENB, VIA into Select Assets / ticker_params / tickers.json (via add_ticker.py) so they get daily signal coverage and optimizable params like the other 25.
3. **Time period toggle on the Analysis charts** ("when did we sell it... I need a toggle on here for the time period"): range selector (e.g. 3M/6M/1Y/ALL) on the Analysis growth/signal/drawdown charts, and same for the Pilot tab chart as it ages.
4. **Python-based Excel data feed (contingent).** If Microsoft's feed is still down after the weekend, build a script that writes Date/Close/Volume per ticker (Yahoo adjusted closes) into the Dropbox location Dan's Stock_Analyzer workbooks read, replacing STOCKHISTORY.

### Dan

- Monitor the Microsoft stock data feed over the weekend; send an update if it recovers.
- Continue Claude Code setup.
- Use Claude/ChatGPT to research sector winners under a Democratic sweep vs. a split-government scenario.
- Confirm next week's meeting (cancel or move to Wednesday).

### Eric (non-dashboard)

- Track the Microsoft outage (Community Hub thread) in case it self-resolves like the January incident.
