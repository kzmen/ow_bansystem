from __future__ import annotations

import os
import secrets
import string
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit, join_room

from ban_logic import HEROES_BY_ROLE, Vote, calculate_bans, validate_choices
from db import DEFAULT_DB_PATH, connect, init_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("OW_BAN_DB", DEFAULT_DB_PATH))
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(24))
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
init_db(DB_PATH)


def error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def json_body() -> dict:
    return request.get_json(silent=True) or {}


def make_room_code() -> str:
    for _ in range(100):
        code = "".join(secrets.choice(ROOM_ALPHABET) for _ in range(6))
        with connect(DB_PATH) as db:
            exists = db.execute("SELECT 1 FROM rooms WHERE code = ?", (code,)).fetchone()
        if not exists:
            return code
    raise RuntimeError("ルームコードを作成できませんでした。")


def get_room(code: str):
    with connect(DB_PATH) as db:
        return db.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()


def require_host(code: str):
    token = request.headers.get("X-Host-Token", "")
    room = get_room(code)
    if room is None:
        return None, error("ルームが見つかりません。", 404)
    if not token or not secrets.compare_digest(token, room["host_token"]):
        return None, error("主催者権限が必要です。", 403)
    return room, None


def require_player(code: str):
    token = request.headers.get("X-Player-Token", "")
    if not token:
        return None, error("参加者情報がありません。再参加してください。", 401)
    with connect(DB_PATH) as db:
        player = db.execute(
            "SELECT * FROM players WHERE room_code = ? AND token = ?",
            (code, token),
        ).fetchone()
    if player is None:
        return None, error("参加者情報が見つかりません。", 401)
    return player, None


def broadcast(code: str) -> None:
    socketio.emit("room_updated", {"room_code": code}, to=code)


def load_votes(code: str, round_no: int) -> list[Vote]:
    with connect(DB_PATH) as db:
        rows = db.execute(
            """
            SELECT p.id AS player_id, p.team, v.rank_no, v.hero
            FROM players p
            LEFT JOIN votes v
              ON v.player_id = p.id AND v.round_no = ?
            WHERE p.room_code = ? AND p.team IN ('A', 'B')
            ORDER BY p.id, v.rank_no
            """,
            (round_no, code),
        ).fetchall()

    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(
            row["player_id"],
            {"team": row["team"], "choices": []},
        )
        if row["hero"] is not None:
            item["choices"].append(row["hero"])
    return [
        Vote(player_id=player_id, team=data["team"], choices=tuple(data["choices"]))
        for player_id, data in grouped.items()
    ]


def reveal_room(code: str) -> None:
    with connect(DB_PATH) as db:
        db.execute("UPDATE rooms SET status = 'revealed' WHERE code = ?", (code,))
    broadcast(code)


def maybe_auto_reveal(code: str) -> None:
    with connect(DB_PATH) as db:
        room = db.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
        if room is None or not room["auto_reveal"] or room["status"] != "voting":
            return
        team_counts = {
            row["team"]: row["count"]
            for row in db.execute(
                "SELECT team, COUNT(*) AS count FROM players WHERE room_code = ? GROUP BY team",
                (code,),
            ).fetchall()
        }
        ready_count = db.execute(
            "SELECT COUNT(*) AS count FROM players WHERE room_code = ? AND team IN ('A', 'B') AND ready = 1",
            (code,),
        ).fetchone()["count"]
    if team_counts.get("A") == 5 and team_counts.get("B") == 5 and ready_count == 10:
        reveal_room(code)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/room/<code>")
def room_page(code: str):
    return render_template("room.html", room_code=code.upper())


@app.post("/api/rooms")
def create_room():
    code = make_room_code()
    host_token = secrets.token_urlsafe(32)
    round_seed = secrets.token_hex(16)
    with connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO rooms(code, host_token, round_seed) VALUES (?, ?, ?)",
            (code, host_token, round_seed),
        )
    return jsonify({"ok": True, "code": code, "host_token": host_token})


@app.post("/api/rooms/<code>/join")
def join(code: str):
    code = code.upper()
    body = json_body()
    name = str(body.get("name", "")).strip()
    team = str(body.get("team", "")).upper()
    if not name or len(name) > 24:
        return error("名前は1〜24文字で入力してください。")
    if team not in {"U", "A", "B"}:
        return error("所属先を選択してください。")

    with connect(DB_PATH) as db:
        room = db.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
        if room is None:
            return error("ルームが見つかりません。", 404)
        if room["status"] != "voting":
            return error("結果公開中は新しく参加できません。")
        duplicate = db.execute(
            "SELECT 1 FROM players WHERE room_code = ? AND lower(name) = lower(?)",
            (code, name),
        ).fetchone()
        if duplicate:
            return error("同じ名前の参加者がいます。別の名前にしてください。")
        if team in {"A", "B"}:
            count = db.execute(
                "SELECT COUNT(*) AS count FROM players WHERE room_code = ? AND team = ?",
                (code, team),
            ).fetchone()["count"]
            if count >= 5:
                return error(f"TEAM {team} は満員です。")

        player_id = str(uuid.uuid4())
        player_token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO players(id, room_code, name, team, token) VALUES (?, ?, ?, ?, ?)",
            (player_id, code, name, team, player_token),
        )
    broadcast(code)
    return jsonify({"ok": True, "player_token": player_token, "player_id": player_id})


@app.get("/api/rooms/<code>/state")
def state(code: str):
    code = code.upper()
    host_token = request.headers.get("X-Host-Token", "")
    player_token = request.headers.get("X-Player-Token", "")

    with connect(DB_PATH) as db:
        room = db.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
        if room is None:
            return error("ルームが見つかりません。", 404)
        players = db.execute(
            "SELECT id, name, team, ready FROM players WHERE room_code = ? ORDER BY CASE team WHEN 'U' THEN 0 WHEN 'A' THEN 1 ELSE 2 END, created_at",
            (code,),
        ).fetchall()
        me = None
        if player_token:
            me = db.execute(
                "SELECT id, name, team, ready FROM players WHERE room_code = ? AND token = ?",
                (code, player_token),
            ).fetchone()

        my_choices: list[str] = []
        if me is not None:
            my_choices = [
                row["hero"]
                for row in db.execute(
                    "SELECT hero FROM votes WHERE player_id = ? AND round_no = ? ORDER BY rank_no",
                    (me["id"], room["round_no"]),
                ).fetchall()
            ]

    is_host = bool(host_token and secrets.compare_digest(host_token, room["host_token"]))
    result = None
    if room["status"] == "revealed":
        votes = load_votes(code, room["round_no"])
        result = calculate_bans(
            votes,
            seed=room["round_seed"],
            enable_lobby_ban=bool(room["lobby_ban"]),
        ).to_dict()

    return jsonify(
        {
            "ok": True,
            "room": {
                "code": room["code"],
                "status": room["status"],
                "auto_reveal": bool(room["auto_reveal"]),
                "lobby_ban": bool(room["lobby_ban"]),
                "round_no": room["round_no"],
            },
            "is_host": is_host,
            "me": dict(me) if me is not None else None,
            "my_choices": my_choices,
            "players": [dict(player) for player in players],
            "heroes": HEROES_BY_ROLE,
            "result": result,
        }
    )


@app.post("/api/rooms/<code>/vote")
def submit_vote(code: str):
    code = code.upper()
    player, response = require_player(code)
    if response:
        return response
    room = get_room(code)
    if room is None:
        return error("ルームが見つかりません。", 404)
    if room["status"] != "voting":
        return error("結果公開後は投票を変更できません。")
    if player["team"] not in {"A", "B"}:
        return error("未所属の間は投票できません。TEAM AまたはTEAM Bへ移動してください。")

    try:
        choices = validate_choices(json_body().get("choices", []))
    except ValueError as exc:
        return error(str(exc))

    with connect(DB_PATH) as db:
        db.execute(
            "DELETE FROM votes WHERE player_id = ? AND round_no = ?",
            (player["id"], room["round_no"]),
        )
        for rank_no, hero in enumerate(choices, start=1):
            db.execute(
                "INSERT INTO votes(player_id, round_no, rank_no, hero) VALUES (?, ?, ?, ?)",
                (player["id"], room["round_no"], rank_no, hero),
            )
        db.execute("UPDATE players SET ready = 1 WHERE id = ?", (player["id"],))
    broadcast(code)
    maybe_auto_reveal(code)
    return jsonify({"ok": True})


@app.post("/api/rooms/<code>/unready")
def unready(code: str):
    code = code.upper()
    player, response = require_player(code)
    if response:
        return response
    room = get_room(code)
    if room is None:
        return error("ルームが見つかりません。", 404)
    if room["status"] != "voting":
        return error("結果公開後は変更できません。")
    with connect(DB_PATH) as db:
        db.execute(
            "DELETE FROM votes WHERE player_id = ? AND round_no = ?",
            (player["id"], room["round_no"]),
        )
        db.execute("UPDATE players SET ready = 0 WHERE id = ?", (player["id"],))
    broadcast(code)
    return jsonify({"ok": True})


@app.post("/api/rooms/<code>/reveal")
def reveal(code: str):
    code = code.upper()
    room, response = require_host(code)
    if response:
        return response
    with connect(DB_PATH) as db:
        ready_count = db.execute(
            "SELECT COUNT(*) AS count FROM players WHERE room_code = ? AND team IN ('A', 'B') AND ready = 1",
            (code,),
        ).fetchone()["count"]
    if ready_count == 0:
        return error("まだ誰も投票していません。")
    reveal_room(code)
    return jsonify({"ok": True})


@app.post("/api/rooms/<code>/settings")
def settings(code: str):
    code = code.upper()
    _, response = require_host(code)
    if response:
        return response
    body = json_body()
    auto_reveal = 1 if body.get("auto_reveal") else 0
    lobby_ban = 1 if body.get("lobby_ban") else 0
    with connect(DB_PATH) as db:
        db.execute(
            "UPDATE rooms SET auto_reveal = ?, lobby_ban = ? WHERE code = ?",
            (auto_reveal, lobby_ban, code),
        )
    broadcast(code)
    return jsonify({"ok": True})


@app.post("/api/rooms/<code>/reset")
def reset(code: str):
    code = code.upper()
    room, response = require_host(code)
    if response:
        return response
    new_round = room["round_no"] + 1
    new_seed = secrets.token_hex(16)
    with connect(DB_PATH) as db:
        db.execute("UPDATE players SET ready = 0 WHERE room_code = ?", (code,))
        db.execute(
            "UPDATE rooms SET status = 'voting', round_no = ?, round_seed = ? WHERE code = ?",
            (new_round, new_seed, code),
        )
    broadcast(code)
    return jsonify({"ok": True})


@app.post("/api/rooms/<code>/move")
def move_player(code: str):
    code = code.upper()
    _, response = require_host(code)
    if response:
        return response
    body = json_body()
    player_id = str(body.get("player_id", ""))
    team = str(body.get("team", "")).upper()
    if team not in {"U", "A", "B"}:
        return error("移動先が正しくありません。")

    with connect(DB_PATH) as db:
        player = db.execute(
            "SELECT id, team FROM players WHERE id = ? AND room_code = ?",
            (player_id, code),
        ).fetchone()
        if player is None:
            return error("参加者が見つかりません。", 404)
        if team in {"A", "B"}:
            count = db.execute(
                "SELECT COUNT(*) AS count FROM players WHERE room_code = ? AND team = ? AND id <> ?",
                (code, team, player_id),
            ).fetchone()["count"]
            if count >= 5:
                return error(f"TEAM {team} は満員です。")
        db.execute("DELETE FROM votes WHERE player_id = ?", (player_id,))
        db.execute("UPDATE players SET team = ?, ready = 0 WHERE id = ?", (team, player_id))
    broadcast(code)
    return jsonify({"ok": True})


@app.post("/api/rooms/<code>/leave")
def leave(code: str):
    code = code.upper()
    player, response = require_player(code)
    if response:
        return response
    with connect(DB_PATH) as db:
        db.execute("DELETE FROM players WHERE id = ?", (player["id"],))
    broadcast(code)
    return jsonify({"ok": True})


@app.post("/api/rooms/<code>/kick")
def kick(code: str):
    code = code.upper()
    _, response = require_host(code)
    if response:
        return response
    player_id = str(json_body().get("player_id", ""))
    with connect(DB_PATH) as db:
        cursor = db.execute(
            "DELETE FROM players WHERE id = ? AND room_code = ?",
            (player_id, code),
        )
    if cursor.rowcount == 0:
        return error("参加者が見つかりません。", 404)
    broadcast(code)
    return jsonify({"ok": True})


@socketio.on("join_room")
def socket_join(data):
    code = str((data or {}).get("room_code", "")).upper()
    if code:
        join_room(code)
        emit("joined_room", {"room_code": code})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=os.environ.get("FLASK_DEBUG") == "1",
        allow_unsafe_werkzeug=True,
    )
