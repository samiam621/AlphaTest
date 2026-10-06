# AlphaTest

AlphaTest is a website for **backtesting trading strategies**: pick a stock (or ETF, index, crypto…), pick a strategy, and see how much money that strategy would have made or lost on real historical prices.

> **Note:** The backend runs on Render's free plan, so if nobody has used the site in a while, the first load can take up to a minute while the server wakes up. After that it's fast.

## What you can do

- **Test any ticker** that Yahoo Finance has (e.g. `AAPL`, `SPY`, `BTC-USD`, `^TNX`).
- **Compare two tickers** side by side on the same chart.
- **Choose a strategy** and tweak its settings:
  - Moving Average Crossover
  - MACD Crossover
  - ROC Momentum
  - Donchian Channel Breakout
  - RSI Threshold
  - Bollinger Band Mean Reversion
  - Stochastic Oscillator
  - Buy and Hold (the baseline to beat)
- **Set trading conditions:** starting cash, trading fees, and whether trades fill at the close or the next day's open.
- **See the results:** an equity curve, a drawdown chart, a trade log, and stats like total return, CAGR, volatility, Sharpe, Sortino, max drawdown, Calmar, and win rate.

## How it works

```
React website  ──►  FastAPI server  ──►  Yahoo Finance (price data)
  (frontend/)         (backend/)
                         │
                         ├─ strategy turns prices into buy/sell signals
                         └─ engine simulates the trades and computes stats
```

| Folder | What's inside |
| --- | --- |
| `frontend/` | The website (React, TypeScript, Vite, Tailwind, Recharts) |
| `backend/app/main.py` | The API the website talks to |
| `backend/app/strategies/` | One file per strategy, plus `registry.py` that lists them |
| `backend/app/backtest/` | The simulator: trade execution, fees, and performance stats |
| `backend/app/ingestion/` | Downloads price data from Yahoo Finance |

## Run it on your computer

You need **Python 3.10+** and **Node.js 20+**.

**1. Start the backend** (from the project's root folder):

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt
```

```bash
uvicorn backend.app.main:app --reload
```

The API is now running at http://127.0.0.1:8000 (interactive docs at http://127.0.0.1:8000/docs).

**2. Start the website** (in a second terminal):

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 and run a backtest.

## Adding a new strategy

1. Create a new file in `backend/app/strategies/` with a `NAME`, a settings dataclass, and a `generate_signals()` function (copy an existing strategy as a starting point).
2. Add one `_register(...)` line for it in `backend/app/strategies/registry.py`.

The website picks it up automatically, including a form for its settings.

## Deployment

- **Backend:** Render, configured in `render.yaml`.
- **Frontend:** Vercel, configured in `frontend/vercel.json` (it forwards `/api` calls to the Render backend).

## Disclaimer

This is a learning project. Past performance doesn't predict future results, and nothing here is financial advice.
