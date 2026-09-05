# Integrated Delivery Scenarios

The reproducible manual audit is
`manual_phase4_7_9_digital_twin_test.py`. It covers:

1. normal exterior growth;
2. drought followed by irrigation;
3. nutrient deficit followed by fertilization;
4. heatwave and frost damage;
5. passive/controlled greenhouse moderation;
6. HVAC and shade effects;
7. deterministic clock execution.

Unit integration tests additionally cover scheduler execution, hourly loops,
one-day steps, month-scale steps, persistence, and explicit harvest state.
Scenarios use fixed weather providers and timezone-aware simulation timestamps,
so repeated runs produce identical snapshots without network or wall-clock
dependencies.