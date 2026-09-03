# Cherry Head Team Meeting: 2026-08-28

**Attendees:** Eric Helbush, Dan (djras). Carrie joined briefly at the end. Emily mentioned but not present.
**Source:** Zoom meeting "Eric Helbush's Personal Meeting Room", 2026-08-28 10:00-10:32 AM PT (UUID 9D4F8E3E-FAAE-4581-9C20-B4C5B43E2F39). Notes derived from the Zoom AI summary and verified against the full transcript.

## Context / decisions

- Portfolio down ~$18k on the day (about half the 3-month loss). Dan characterized it as summer doldrums; the team agreed to hold positions and watch for direction after Labor Day. SPY strong buy (58%), QQQ solid buy (32%).
- FICS (down 15%, weak buy) and GOOGL (weak sell, position up ~6%) are the two watch positions. If FICS drops to sell, exit and redeploy.
- Concentration risk: AVGO (~50% gain) is the primary delever target; LLY also heavy but low gains, so easier to trim.
- Tax-aware rebalancing: use booked losses (FICS ~$15k, possibly GOOGL) to offset gains, like the earlier GLW exit. Mind the 30-day wash sale rule. Portfolio shows roughly a $9k net realized loss over the last 6 months.
- Trial portfolio approved: put roughly $10,000-$15,000 (or start smaller, ~$1k per position) into picks from the Portfolio Builder / optimizer, starting with BTSG plus one or two other candidates (AAUC and "Anderson" were discussed). Track it by tagging trades inside the existing dashboard rather than opening a separate Schwab account. Long-term goal: migrate funds from underperforming to outperforming portfolios.
- Waitlist / external expansion stays on hold until the track record is stronger. Broader deployment would also require an in-person certification exam.

## Action items

### Dashboard development (executable in this repo)

1. **Realized vs. unrealized gains/losses feature** (requested by Dan)
   - Calendar year-to-date view of realized and unrealized gains/losses, broken down by long-term vs. short-term.
   - Purpose: tax planning visibility, deciding what to delever and what losses to harvest before any post-Labor Day move.
   - Eric confirmed the underlying data is available. Start with a one-off analysis of the current tax position before formalizing recurring visualizations in the dashboard.
2. **Trial portfolio tracking via tagging**
   - Support tagging positions/trades as belonging to a named portfolio (e.g. "trial") within the existing dashboard infrastructure, so the trial portfolio's performance can be tracked alongside the main portfolio without a separate brokerage account.
3. **Asset exploration UX improvements**
   - Today, drilling into an asset (e.g. from the screener or Portfolio Builder results) takes over the view and loses state; there is no way to open an asset in a new tab or preview it.
   - Add tab-open support and/or an asset preview that preserves the current view.
4. **Claude onboarding instructions for Dan**
   - Write step-by-step instructions for Dan to subscribe to Claude and start contributing to the dashboard (workflow: subscribe, describe what you want, paste screenshots when stuck). Eric to send them to Dan next week (week of 2026-08-31).

### Eric (manual / finance, not repo work)

- Fund the trial portfolio (BTSG plus one or two others) and tag the positions once tagging exists.
- Review carry-forward loss position using Chris's work papers to determine remaining short-term losses available; consider gain harvesting.
- Invest the SEP contribution (noted 8/28 was a good entry point given the pullback).
- Monitor FICS and prepare replacement assets in case it drops to a sell signal; watch GOOGL's sell signal.
- Took a screenshot of the optimized portfolio for reference.

### Dan

- Subscribe to Claude and start experimenting with dashboard contributions once Eric sends instructions.
- Monitor FICS and GOOGL; discuss AVGO deleveraging with Eric.

### Emily

- Spend more time in the dashboard to build familiarity and contribute to development discussions.
