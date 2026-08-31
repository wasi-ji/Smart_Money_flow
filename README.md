# Smart Money Flow Terminal Pro

A production-grade real-time crypto capital rotation dashboard.
Identifies where smart money is flowing inside the crypto market.

---

## Features

- **Capital Flow Score** — multi-factor 0–100 score per asset
- **Smart Money Leaderboard** — top 10 inflows / outflows, updated every second
- **Whale Detector** — volume spikes, OI changes, funding extremes, liquidations
- **Sector Rotation Heatmap** — Layer 1, DeFi, AI, Gaming, Meme
- **Market Dominance** — BTC / ETH / USDT / Alts with live donut chart
- **Risk-On / Risk-Off Gauge** — aggregate regime detection
- **Funding Rate Panel** — all tracked perpetuals with sentiment bias
- **Open Interest Panel** — live OI with change tracking
- **TradingView Lightweight Charts** — multi-line flow chart with toggles
- **Live Alert Bar** — streaming alerts for all significant events

---

## Project Structure

```
project/
├── frontend/
│   ├── index.html       — Dashboard HTML
│   ├── style.css        — Dark terminal styling
│   └── app.js           — WebSocket client + all UI logic
│
├── backend/
│   ├── main.py              — FastAPI app + WebSocket endpoint
│   ├── config.py            — Settings (env-configurable)
│   ├── websocket_manager.py — Multi-client WS broadcast
│   ├── capital_flow_engine.py — Flow score computation
│   ├── market_scanner.py    — Binance REST data fetcher
│   ├── dominance_engine.py  — BTC/ETH/USDT dominance
│   ├── whale_detector.py    — Large trade detection
│   ├── funding_engine.py    — Perpetual funding rates
│   ├── ranking_engine.py    — Top-10 inflow/outflow rankings
│   ├── sector_rotation.py   — Sector performance grouping
│   ├── database.py          — SQLite async persistence
│   └── requirements.txt     — Python dependencies
│
└── data/
    └── market.db            — SQLite database (auto-created)
```

---

## Quick Start

### 1. Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Start the backend

```bash
cd backend
python main.py
```

The backend starts on `http://localhost:8000`.  
WebSocket endpoint: `ws://localhost:8000/ws`

### 3. Open the frontend

Open `frontend/index.html` in your browser.

> **Tip:** For best results, serve via a local HTTP server:
> ```bash
> cd frontend
> python -m http.server 3000
> # Then open http://localhost:3000
> ```

### 4. Optional: Environment variables

Create a `.env` file in the `backend/` directory:

```env
HOST=0.0.0.0
PORT=8000
DEBUG=false
DB_PATH=../data/market.db

# Optional Binance API keys (not required for public market data)
BINANCE_API_KEY=your_key_here
BINANCE_SECRET=your_secret_here
```

---

## Capital Flow Score Formula

```
FlowScore = 0.20 × Price Strength
          + 0.20 × Volume Score
          + 0.20 × Relative Volume
          + 0.15 × Momentum (12h)
          + 0.15 × OI Change
          + 0.10 × Funding Rate (inverted)

Normalized to 0–100 across all tracked assets.
```

**Signal thresholds:**
| Score | Signal |
|-------|--------|
| ≥ 68  | STRONG INFLOW ▲ |
| ≥ 55  | INFLOW ▲ |
| 45–55 | NEUTRAL |
| ≤ 45  | OUTFLOW ▼ |
| ≤ 32  | STRONG OUTFLOW ▼ |

---

## Data Sources

| Data | Source |
|------|--------|
| Spot prices & 24h stats | Binance `/api/v3/ticker/24hr` |
| Klines (momentum/trend) | Binance `/api/v3/klines` |
| Open Interest | Binance Futures `/fapi/v1/openInterest` |
| Funding Rates | Binance Futures `/fapi/v1/premiumIndex` |
| Liquidations | Binance Futures `/fapi/v1/allForceOrders` |
| Market Dominance | CoinGecko `/api/v3/global` (with volume fallback) |

---

## Demo Mode

If the backend is not running, the frontend automatically enters **DEMO MODE** after 3 seconds, simulating all data locally so the UI remains fully interactive and explorable.

---

## Tracked Assets

`BTCUSDT` `ETHUSDT` `BNBUSDT` `SOLUSDT` `XRPUSDT`  
`DOGEUSDT` `ADAUSDT` `LINKUSDT` `AVAXUSDT` `TRXUSDT`

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/health` | Health check + client count |
| `GET`  | `/api/flow-scores` | Latest capital flow scores |
| `GET`  | `/api/dominance` | Market dominance data |
| `GET`  | `/api/funding` | Funding rates |
| `GET`  | `/api/whale-alerts` | Recent whale alerts |
| `GET`  | `/api/sectors` | Sector rotation data |
| `WS`   | `/ws` | Real-time data stream |

---

## WebSocket Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `full_snapshot` | Server → Client | Complete state on connect |
| `market_update` | Server → Client | Price/volume tick |
| `flow_scores` | Server → Client | Updated flow scores |
| `dominance` | Server → Client | Dominance update |
| `funding_update` | Server → Client | Funding rates |
| `oi_update` | Server → Client | Open interest |
| `sector_update` | Server → Client | Sector rotation |
| `risk_regime` | Server → Client | Risk-On/Off regime |
| `whale_alert` | Server → Client | Whale activity detected |
| `alert` | Server → Client | System alert |
| `ping` / `pong` | Both | Heartbeat |

---

## License

MIT — built for educational and research purposes.  
Always do your own research before making financial decisions.
