"""
TypeaRace - Python Flask + SocketIO version
Run with: python3 app.py
Then open http://localhost:5000
"""

import os
import json
import uuid
import random
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session
from flask_socketio import SocketIO, emit, join_room
import anthropic

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "typeracer-dev-secret-2024")
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Anthropic AI setup ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# --- Persistent data ---
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SCORES_FILE   = os.path.join(DATA_DIR, "scores.json")
QUOTES_FILE   = os.path.join(DATA_DIR, "community_quotes.json")

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f: return json.load(f)
        except Exception: pass
    return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

accounts         = load_json(ACCOUNTS_FILE, {})
global_scores    = load_json(SCORES_FILE, [])
community_quotes = load_json(QUOTES_FILE, [])

# --- In-memory multiplayer rooms ---
# rooms[code] = { host_sid, players: {sid: {name, progress, finished, wpm, accuracy}}, quote, started }
rooms = {}


# ──────────────────────────────────────────────
# HTTP ROUTES
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/quote", methods=["POST"])
def get_quote():
    data = request.json or {}
    if not anthropic_client:
        return jsonify({"quote": _fallback_quote(), "source": "fallback"})
    try:
        prompt = _build_prompt(data.get("mode","quote"), data.get("difficulty","easy"), int(data.get("custom_wpm",75)))
        resp = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            messages=[{"role":"user","content":prompt}])
        return jsonify({"quote": resp.content[0].text.strip(), "source": "claude"})
    except Exception as e:
        print(f"Claude error: {e}")
        return jsonify({"quote": _fallback_quote(), "source": "fallback"})


@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.json or {}
    name, email, pw = data.get("name","").strip(), data.get("email","").strip().lower(), data.get("password","")
    if not name or not email or not pw: return jsonify({"error":"All fields required"}), 400
    if email in accounts: return jsonify({"error":"Account already exists"}), 400
    accounts[email] = _new_user(name, email, pw)
    save_json(ACCOUNTS_FILE, accounts)
    session["user"] = email
    return jsonify({"user": _public_user(email)})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    email, pw = data.get("email","").strip().lower(), data.get("password","")
    user = accounts.get(email)
    if not user or user.get("password") != pw: return jsonify({"error":"Invalid credentials"}), 401
    session["user"] = email
    return jsonify({"user": _public_user(email)})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    email = session.get("user")
    if email and email in accounts: return jsonify({"user": _public_user(email)})
    return jsonify({"user": None})


@app.route("/api/scores", methods=["POST"])
def save_score():
    data = request.json or {}
    email = session.get("user")
    wpm, accuracy = data.get("wpm",0), data.get("accuracy",100)
    entry = {"wpm":wpm,"accuracy":accuracy,"mode":data.get("mode","quote"),
             "difficulty":data.get("difficulty","easy"),"date":datetime.utcnow().isoformat()}
    new_ach = []
    if email and email in accounts:
        user = accounts[email]
        user["highScores"].insert(0, entry)
        user["highScores"] = user["highScores"][:50]
        s = user["stats"]
        s["totalRacesCompleted"] = s.get("totalRacesCompleted",0) + 1
        s["highestWpm"] = max(s.get("highestWpm",0), wpm)
        if accuracy == 100: s["flawlessRaces"] = s.get("flawlessRaces",0) + 1
        hist = s.get("accuracyHistory",[]); hist.append(accuracy); s["accuracyHistory"] = hist[-10:]
        new_ach = _check_achievements(user, wpm, accuracy)
        save_json(ACCOUNTS_FILE, accounts)
    global_scores.append({**entry,"user":accounts.get(email,{}).get("name","Guest") if email else "Guest"})
    global_scores.sort(key=lambda x:x["wpm"],reverse=True); del global_scores[100:]
    save_json(SCORES_FILE, global_scores)
    return jsonify({"ok":True,"achievements":new_ach})

@app.route("/api/scores/personal")
def personal_scores():
    email = session.get("user")
    return jsonify(accounts[email].get("highScores",[]) if email and email in accounts else [])

@app.route("/api/scores/global")
def global_scores_route():
    return jsonify(global_scores[:100])

@app.route("/api/scores/clear", methods=["POST"])
def clear_scores():
    email = session.get("user")
    if email and email in accounts:
        accounts[email]["highScores"] = []; save_json(ACCOUNTS_FILE, accounts)
    return jsonify({"ok":True})


@app.route("/api/settings", methods=["POST"])
def update_settings():
    email = session.get("user")
    if not email or email not in accounts: return jsonify({"error":"Not logged in"}), 401
    data, user = request.json or {}, accounts[email]
    for f in ("name","bio","profilePicture","theme"):
        if f in data: user[f] = data[f][:100] if isinstance(data[f],str) else data[f]
    if "isSoundOn" in data: user["isSoundOn"] = bool(data["isSoundOn"])
    if "currentPassword" in data:
        if user["password"] != data["currentPassword"]: return jsonify({"error":"Current password is incorrect"}), 400
        if data.get("newPassword"): user["password"] = data["newPassword"]
    save_json(ACCOUNTS_FILE, accounts)
    return jsonify({"user": _public_user(email)})


@app.route("/api/quotes/community")
def list_community_quotes():
    sort, search = request.args.get("sort","newest"), request.args.get("search","").lower()
    valid = [q for q in community_quotes if not q.get("isReported")]
    if search: valid = [q for q in valid if search in q["text"].lower() or search in q["authorName"].lower()]
    valid.sort(key=lambda q: q.get("raceCount",0) if sort=="popular" else q.get("createdAt",""), reverse=True)
    return jsonify(valid)

@app.route("/api/quotes/community", methods=["POST"])
def create_community_quote():
    email = session.get("user")
    if not email or email not in accounts: return jsonify({"error":"Login required"}), 401
    text = (request.json or {}).get("text","").strip()
    if len(text) < 100 or len(text) > 400: return jsonify({"error":"Quote must be 100-400 characters"}), 400
    q = {"id":str(uuid.uuid4()),"text":text,"authorEmail":email,"authorName":accounts[email]["name"],
         "createdAt":datetime.utcnow().isoformat(),"raceCount":0,"isReported":False}
    community_quotes.append(q); save_json(QUOTES_FILE, community_quotes)
    return jsonify(q)

@app.route("/api/quotes/community/<quote_id>/report", methods=["POST"])
def report_quote(quote_id):
    for q in community_quotes:
        if q["id"] == quote_id:
            q["isReported"] = True; save_json(QUOTES_FILE, community_quotes)
            return jsonify({"ok":True})
    return jsonify({"error":"Not found"}), 404

@app.route("/api/quotes/community/enhance", methods=["POST"])
def enhance_quote():
    original = (request.json or {}).get("text","")
    if not anthropic_client or not original: return jsonify({"enhanced":original})
    try:
        resp = anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=300,
            messages=[{"role":"user","content":f'Refine this typing practice quote for style and clarity. Return ONLY the improved text:\n\n"{original}"'}])
        return jsonify({"enhanced": resp.content[0].text.strip().strip('"')})
    except Exception as e:
        return jsonify({"enhanced":original,"error":str(e)})


# ──────────────────────────────────────────────
# SOCKET.IO — MULTIPLAYER
# ──────────────────────────────────────────────

def _snapshot(code):
    r = rooms[code]
    return {
        "code": code,
        "host": r["host_sid"],
        "players": [{"sid":sid,"name":p["name"],"progress":p["progress"],"finished":p["finished"]}
                    for sid,p in r["players"].items()],
        "started": r["started"],
        "quote": r["quote"] if r["started"] else None,
    }

@socketio.on("create_room")
def on_create_room(data):
    name = data.get("name","Player")[:20]
    code = _gen_code()
    rooms[code] = {"host_sid":request.sid,
                   "players":{request.sid:{"name":name,"progress":0,"finished":False,"wpm":0,"accuracy":100}},
                   "quote":"","started":False}
    join_room(code)
    emit("room_created", {"code":code})
    emit("room_update", _snapshot(code), to=code)

@socketio.on("join_room_mp")
def on_join_room(data):
    code = data.get("code","").upper().strip()
    name = data.get("name","Player")[:20]
    if code not in rooms:
        emit("mp_error", {"message":"Room not found. Double-check the code."})
        return
    if rooms[code]["started"]:
        emit("mp_error", {"message":"That race has already started!"})
        return
    rooms[code]["players"][request.sid] = {"name":name,"progress":0,"finished":False,"wpm":0,"accuracy":100}
    join_room(code)
    emit("room_joined", {"code":code})
    emit("room_update", _snapshot(code), to=code)

@socketio.on("start_race_mp")
def on_start_race(data):
    code = data.get("code","")
    if code not in rooms or rooms[code]["host_sid"] != request.sid: return
    room = rooms[code]
    if anthropic_client:
        try:
            prompt = _build_prompt("quote", data.get("difficulty","easy"), 75)
            resp = anthropic_client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=300,
                messages=[{"role":"user","content":prompt}])
            room["quote"] = resp.content[0].text.strip()
        except Exception:
            room["quote"] = _fallback_quote()
    else:
        room["quote"] = _fallback_quote()
    room["started"] = True
    for p in room["players"].values(): p["progress"] = 0; p["finished"] = False
    emit("race_started", {"quote":room["quote"]}, to=code)

@socketio.on("progress_update")
def on_progress(data):
    code, progress = data.get("code",""), data.get("progress",0)
    if code not in rooms or request.sid not in rooms[code]["players"]: return
    rooms[code]["players"][request.sid]["progress"] = progress
    emit("room_update", _snapshot(code), to=code)

@socketio.on("player_finished")
def on_finished(data):
    code = data.get("code","")
    if code not in rooms or request.sid not in rooms[code]["players"]: return
    p = rooms[code]["players"][request.sid]
    if not p["finished"]:
        p["finished"] = True; p["wpm"] = data.get("wpm",0); p["accuracy"] = data.get("accuracy",100)
        emit("room_update", _snapshot(code), to=code)
        if all(pl["finished"] for pl in rooms[code]["players"].values()):
            winner = max(rooms[code]["players"].values(), key=lambda x: x["wpm"])
            results = sorted([{"name":pl["name"],"wpm":pl["wpm"],"accuracy":pl["accuracy"]}
                               for pl in rooms[code]["players"].values()], key=lambda x:-x["wpm"])
            emit("race_over", {"winner":winner["name"],"results":results}, to=code)
            rooms[code]["started"] = False
            for pl in rooms[code]["players"].values(): pl["progress"]=0; pl["finished"]=False

@socketio.on("chat_message")
def on_chat(data):
    code, msg = data.get("code",""), data.get("message","").strip()[:200]
    if not msg or code not in rooms: return
    name = rooms[code]["players"].get(request.sid,{}).get("name","?")
    emit("chat_message", {"name":name,"message":msg}, to=code)

@socketio.on("disconnect")
def on_disconnect():
    for code, room in list(rooms.items()):
        if request.sid in room["players"]:
            del room["players"][request.sid]
            if not room["players"]:
                del rooms[code]
            else:
                if room["host_sid"] == request.sid:
                    room["host_sid"] = next(iter(room["players"]))
                emit("room_update", _snapshot(code), to=code)
            break


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def _gen_code():
    while True:
        code = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=5))
        if code not in rooms: return code

def _fallback_quote():
    return random.choice([
        "The quick brown fox jumps over the lazy dog. Practice makes perfect.",
        "Speed comes from consistency. Accuracy comes from practice. Master both.",
        "Every keystroke brings you closer to mastery. Keep your eyes on the screen.",
    ])

def _build_prompt(mode, difficulty, custom_wpm=75):
    topics = ["the history of the rubber duck","the strangest deep sea creatures",
              "a recipe from a fantasy novel","a fun fact about computer programming",
              "the daily routine of a cat who is also a king","a travel guide to a fictional city",
              "the science behind a perfect cup of coffee","a conspiracy theory about garden gnomes",
              "why cats knock things off tables","the secret life of office supplies"]
    topic = random.choice(topics)
    dmap = {"beginner":"using extremely simple words and no punctuation",
            "easy":"using simple vocabulary and basic punctuation",
            "medium":"with varied vocabulary and standard punctuation like commas",
            "hard":"using advanced vocabulary and complex punctuation like semicolons",
            "proficient":"using sophisticated vocabulary and varied punctuation",
            "expert":"using very advanced vocabulary and a wide array of punctuation",
            "master":"that is exceptionally challenging with technical jargon",
            "grandmaster":"that is extremely difficult with rare words and convoluted sentences"}
    if difficulty == "custom":
        w = custom_wpm
        dt = ("very simple words" if w<30 else "short sentences" if w<50 else "standard structure" if w<70
              else "varied vocabulary" if w<100 else "sophisticated vocabulary" if w<130 else "extremely difficult structures")
    else:
        dt = dmap.get(difficulty, dmap["easy"])

    if mode == "time":
        return f'Generate a {random.randint(30,50)}-word paragraph for a typing game on "{topic}", {dt}. Return only the text.'
    elif mode == "sudden-death":
        return f'Generate a 30-50 word paragraph for a typing game on "{topic}", using advanced vocabulary and complex punctuation. Return only the text.'
    elif mode == "code-breaker":
        lang = random.choice(["JavaScript","Python","HTML","CSS"])
        cx = {"easy":"beginner-level","medium":"intermediate-level","hard":"more complex"}.get(difficulty,"beginner-level")
        return f'Generate a short {lang} code snippet ({cx} concept). No markdown, no explanations. Raw code only, 100-250 chars.'
    elif mode == "zen":
        return f'Generate a calm, 60-100 word inspirational paragraph for a typing game, {dt}. Return only the text.'
    else:
        return f'Generate a 40-60 word paragraph for a typing game on "{topic}", {dt}. Return only the text.'

def _check_achievements(user, wpm, accuracy):
    new, earned = [], user.get("achievements",[])
    races = user["stats"]["totalRacesCompleted"]
    for key, cond, name, icon in [
        ("speedster_50",  wpm>=50,       "Speedster (50 WPM)",    "⚡"),
        ("speedster_100", wpm>=100,      "Speed Demon (100 WPM)", "🚀"),
        ("speed_150",     wpm>=150,      "Lightning (150 WPM)",   "⚡⚡"),
        ("perfectionist", accuracy==100, "Perfectionist",          "🎯"),
        ("dedicated",     races>=10,     "Dedicated (10 Races)",   "🏃"),
        ("centurion",     races>=100,    "Centurion (100 Races)",  "💯"),
    ]:
        if cond and key not in earned: earned.append(key); new.append({"name":name,"icon":icon})
    user["achievements"] = earned
    return new

def _new_user(name, email, pw):
    return {"name":name,"password":pw,"email":email,"profilePicture":"","bio":"",
            "joinDate":datetime.utcnow().isoformat(),"highScores":[],"theme":"default","isSoundOn":True,
            "friends":[],"friendRequestsSent":[],"friendRequestsReceived":[],
            "stats":{"totalRacesCompleted":0,"highestWpm":0,"flawlessRaces":0,"accuracyHistory":[]},"achievements":[]}

def _public_user(email):
    u = accounts.get(email,{})
    return {"email":email,"name":u.get("name","User"),"profilePicture":u.get("profilePicture",""),
            "bio":u.get("bio",""),"joinDate":u.get("joinDate",""),"theme":u.get("theme","default"),
            "isSoundOn":u.get("isSoundOn",True),"stats":u.get("stats",{}),"achievements":u.get("achievements",[])}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("─" * 50)
    print("  TypeaRace  (Flask + Multiplayer)")
    print(f"  Open: http://localhost:{port}")
    if not ANTHROPIC_API_KEY:
        print("\n  ⚠️  No ANTHROPIC_API_KEY — using fallback quotes.")
        print("  Set it: export ANTHROPIC_API_KEY=sk-ant-...")
    print("─" * 50)
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
