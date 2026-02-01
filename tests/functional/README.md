# Functionality & Implementation Tests

This directory contains tests that verify the basic implementation of features.
These tests act as "smoke tests" or "integration integrity checks".

**Purpose:**

- Ensure components (Widgets, Classes) initialize and run correctly.
- Verify state transitions (e.g. valid -> invalid, run -> stop).
- Check for crashes or obvious errors (e.g. NoneType exceptions).
- Verify basic data flow (buffer updates).

**contrast with `logic_verification`:**
These tests do NOT typically verify the numerical precision of DSP algorithms.
For rigorous checking of math/analysis logic (RMSE, THD accuracy, etc.), see `../logic_verification`.
