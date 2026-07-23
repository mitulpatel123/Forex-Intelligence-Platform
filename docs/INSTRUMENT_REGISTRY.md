# Instrument registry

The canonical source is
`packages/contracts/instrument_specs.json`. Do not hand-edit generated artifacts.

| Symbol | Base | Quote | Pip | Display decimals | Broad bounds | Spread/jump warning |
|---|---|---|---:|---:|---:|---:|
| EURUSD | EUR | USD | 0.0001 | 4–6 | 0.5–2.5 | 5 / 20 pips |
| GBPUSD | GBP | USD | 0.0001 | 4–6 | 0.5–3.5 | 5 / 20 pips |
| USDJPY | USD | JPY | 0.01 | 2–4 | 50–250 | 5 / 20 pips |
| AUDUSD | AUD | USD | 0.0001 | 4–6 | 0.2–2.0 | 5 / 20 pips |

Generate and verify:

```bash
make generate-contracts
make check-generated
```

Outputs:

- `packages/contracts/src/forex_contracts/instruments_generated.py`
- `apps/browser_bridge/src/instruments.generated.ts`

Generation preserves canonical symbol order and is deterministic. Tests compare
symbols, currencies, pip sizes, precision, and bounds across the canonical JSON and
both generated targets. CI fails if either generated file is stale.
