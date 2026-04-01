---
name: Param optimization approach
description: Decisions and open questions about CHC model parameter optimization
type: project
---

Optimization uses buy_threshold = sell_threshold (symmetric) for now. Need to follow up with Dan (Emily's dad) on whether asymmetric thresholds are worth exploring.

**Why:** Dan manually tuned all 25 Excel models with symmetric thresholds. Unclear if this was intentional design or just simplification.

**How to apply:** Keep thresholds coupled in the optimizer. If Dan says asymmetric is worth trying, double the search space for thresholds.
