"""Rule modules consumed by the deterministic risk engine.

Each `evaluate(...)` function returns a list of RiskFinding objects. Modules
are independent and order-insensitive — the risk_engine fans them out in
parallel and arbitration collapses results by max-severity.
"""
