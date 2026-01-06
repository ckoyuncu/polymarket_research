# Polymarket Bot Dashboard

Real-time monitoring dashboard for the Tokyo-deployed arbitrage bot.

## Quick Start

### Local Development
```bash
cd streamlit_dashboard
pip install -r requirements.txt
BOT_API_URL=http://18.183.215.121:8502 streamlit run dashboard.py
```

### Streamlit Cloud Deployment
1. Push to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your repo, set main file to `streamlit_dashboard/dashboard.py`
4. Add secret: `BOT_API_URL = "http://18.183.215.121:8502"`

## Architecture

```
Dashboard (Streamlit Cloud) --HTTP--> Status API (Tokyo:8502) --> Bot State
```

## Endpoints (Status API)

| Endpoint | Description |
|----------|-------------|
| `/status` | Full bot status (health, trading, circuit breakers, market) |
| `/health` | Bot process health only |
| `/trading` | Trading metrics only |
| `/trades` | Recent trades list |
| `/errors` | Error log entries |

## Dashboard Tabs

1. **Overview**: Trading status, circuit breakers, market connections, bot health
2. **Performance**: Win rate vs Account88888 pattern, deviation alerts
3. **Errors**: Filterable error/warning log
4. **Logs**: Raw log viewer
