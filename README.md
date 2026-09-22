# TypeaRace — Python/Flask Edition

A typing race game powered by Python (Flask) + Gemini AI.

## Setup

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Set your Gemini API key (optional — fallback quotes used if omitted)
export GEMINI_API_KEY=your_key_here

# 3. Run the server
python3 app.py
```

Then open **http://localhost:5000** in your browser.

---

## File layout

```
typeracer_python/
├── app.py              ← Flask server + all API routes
├── requirements.txt    ← pip dependencies
├── templates/
│   └── index.html      ← HTML + vanilla JS client
├── static/
│   └── style.css       ← Original game styles
└── data/               ← Auto-created; stores user accounts, scores, quotes
    ├── accounts.json
    ├── scores.json
    └── community_quotes.json
```

## API routes

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/quote` | Generate AI typing quote |
| POST | `/api/signup` | Create account |
| POST | `/api/login` | Login |
| POST | `/api/logout` | Logout |
| GET  | `/api/me` | Current session user |
| POST | `/api/scores` | Save race score |
| GET  | `/api/scores/personal` | Personal high scores |
| GET  | `/api/scores/global` | Global leaderboard |
| POST | `/api/scores/clear` | Clear personal scores |
| POST | `/api/settings` | Update profile/password/theme/sound |
| GET  | `/api/quotes/community` | List community quotes |
| POST | `/api/quotes/community` | Create community quote |
| POST | `/api/quotes/community/enhance` | AI-enhance a quote |
| POST | `/api/quotes/community/<id>/report` | Report a quote |

## Improvements over original

- **No build step** — just `python3 app.py`
- **Persistent storage** — JSON files in `data/` survive restarts
- **Server-side auth** — passwords and sessions handled by Flask
- **Clean API** — all logic split between `app.py` (server) and `index.html` (client)
- **Easy to extend** — add routes in `app.py`, tweak UI in `templates/index.html`
