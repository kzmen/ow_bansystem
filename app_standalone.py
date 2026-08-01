from __future__ import annotations

import json
import mimetypes
import os
import secrets
import string
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from ban_logic import HEROES_BY_ROLE, Vote, calculate_bans, validate_choices
from db import DEFAULT_DB_PATH, connect, init_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("OW_BAN_DB", DEFAULT_DB_PATH))
ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "5000"))

init_db(DB_PATH)


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


def load_votes(code: str, round_no: int) -> list[Vote]:
    with connect(DB_PATH) as db:
        rows = db.execute(
            """
            SELECT p.id AS player_id, p.team, v.rank_no, v.hero
            FROM players p
            LEFT JOIN votes v
              ON v.player_id = p.id AND v.round_no = ?
            WHERE p.room_code = ?
            ORDER BY p.id, v.rank_no
            """,
            (round_no, code),
        ).fetchall()

    grouped: dict[str, dict] = {}
    for row in rows:
        item = grouped.setdefault(row["player_id"], {"team": row["team"], "choices": []})
        if row["hero"] is not None:
            item["choices"].append(row["hero"])
    return [
        Vote(player_id=player_id, team=data["team"], choices=tuple(data["choices"]))
        for player_id, data in grouped.items()
    ]


def reveal_room(code: str) -> None:
    with connect(DB_PATH) as db:
        db.execute("UPDATE rooms SET status = 'revealed' WHERE code = ?", (code,))


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
            "SELECT COUNT(*) AS count FROM players WHERE room_code = ? AND ready = 1",
            (code,),
        ).fetchone()["count"]
    if team_counts.get("A") == 5 and team_counts.get("B") == 5 and ready_count == 10:
        reveal_room(code)


def render_template(name: str, room_code: str | None = None) -> bytes:
    path = BASE_DIR / "templates" / name
    text = path.read_text(encoding="utf-8")
    text = text.replace("{{ url_for('static', filename='style.css') }}", "/static/style.css")
    text = text.replace("{{ url_for('static', filename='room.js') }}", "/static/room.js")
    text = text.replace('<script src="/socket.io/socket.io.js"></script>', "")
    if room_code is not None:
        text = text.replace("{{ room_code|tojson }}", json.dumps(room_code, ensure_ascii=False))
        text = text.replace("{{ room_code }}", room_code)
    return text.encode("utf-8")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "OWBanRoom/1.1"

    def log_message(self, fmt: str, *args) -> None:
        # Keep console readable; only show errors.
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def _headers(self) -> dict[str, str]:
        return {key.lower(): value for key, value in self.headers.items()}

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _require_host(self, code: str):
        token = self.headers.get("X-Host-Token", "")
        room = get_room(code)
        if room is None:
            self._error("ルームが見つかりません。", 404)
            return None
        if not token or not secrets.compare_digest(token, room["host_token"]):
            self._error("主催者権限が必要です。", 403)
            return None
        return room

    def _require_player(self, code: str):
        token = self.headers.get("X-Player-Token", "")
        if not token:
            self._error("参加者情報がありません。再参加してください。", 401)
            return None
        with connect(DB_PATH) as db:
            player = db.execute(
                "SELECT * FROM players WHERE room_code = ? AND token = ?",
                (code, token),
            ).fetchone()
        if player is None:
            self._error("参加者情報が見つかりません。", 401)
            return None
        return player

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            return self._send_bytes(render_template("index.html"), "text/html; charset=utf-8")

        if path.startswith("/room/"):
            code = path.removeprefix("/room/").upper()
            if len(code) != 6 or any(c not in string.ascii_uppercase + string.digits for c in code):
                return self._error("ルームコードが正しくありません。", 404)
            return self._send_bytes(render_template("room.html", code), "text/html; charset=utf-8")

        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            target = (BASE_DIR / "static" / relative).resolve()
            static_root = (BASE_DIR / "static").resolve()
            if static_root not in target.parents or not target.is_file():
                return self._error("ファイルが見つかりません。", 404)
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if mime.startswith("text/") or mime in {"application/javascript", "application/json"}:
                mime += "; charset=utf-8"
            return self._send_bytes(target.read_bytes(), mime)

        parts = [p for p in path.split("/") if p]
        if len(parts) == 4 and parts[:2] == ["api", "rooms"] and parts[3] == "state":
            return self._state(parts[2].upper())

        return self._error("ページが見つかりません。", 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/rooms":
            return self._create_room()

        parts = [p for p in path.split("/") if p]
        if len(parts) != 4 or parts[:2] != ["api", "rooms"]:
            return self._error("APIが見つかりません。", 404)

        code = parts[2].upper()
        action = parts[3]
        actions = {
            "join": self._join,
            "vote": self._vote,
            "unready": self._unready,
            "reveal": self._reveal,
            "settings": self._settings,
            "reset": self._reset,
            "leave": self._leave,
            "kick": self._kick,
        }
        func = actions.get(action)
        if func is None:
            return self._error("APIが見つかりません。", 404)
        return func(code)

    def _create_room(self) -> None:
        code = make_room_code()
        host_token = secrets.token_urlsafe(32)
        round_seed = secrets.token_hex(16)
        with connect(DB_PATH) as db:
            db.execute(
                "INSERT INTO rooms(code, host_token, round_seed) VALUES (?, ?, ?)",
                (code, host_token, round_seed),
            )
        self._json({"ok": True, "code": code, "host_token": host_token})

    def _join(self, code: str) -> None:
        body = self._read_json()
        name = str(body.get("name", "")).strip()
        team = str(body.get("team", "")).upper()
        if not name or len(name) > 24:
            return self._error("名前は1〜24文字で入力してください。")
        if team not in {"A", "B"}:
            return self._error("チームを選択してください。")

        with connect(DB_PATH) as db:
            room = db.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
            if room is None:
                return self._error("ルームが見つかりません。", 404)
            if room["status"] != "voting":
                return self._error("結果公開中は新しく参加できません。")
            duplicate = db.execute(
                "SELECT 1 FROM players WHERE room_code = ? AND lower(name) = lower(?)",
                (code, name),
            ).fetchone()
            if duplicate:
                return self._error("同じ名前の参加者がいます。別の名前にしてください。")
            count = db.execute(
                "SELECT COUNT(*) AS count FROM players WHERE room_code = ? AND team = ?",
                (code, team),
            ).fetchone()["count"]
            if count >= 5:
                return self._error(f"TEAM {team} は満員です。")

            player_id = str(uuid.uuid4())
            player_token = secrets.token_urlsafe(32)
            db.execute(
                "INSERT INTO players(id, room_code, name, team, token) VALUES (?, ?, ?, ?, ?)",
                (player_id, code, name, team, player_token),
            )
        self._json({"ok": True, "player_token": player_token, "player_id": player_id})

    def _state(self, code: str) -> None:
        host_token = self.headers.get("X-Host-Token", "")
        player_token = self.headers.get("X-Player-Token", "")
        with connect(DB_PATH) as db:
            room = db.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
            if room is None:
                return self._error("ルームが見つかりません。", 404)
            players = db.execute(
                "SELECT id, name, team, ready FROM players WHERE room_code = ? ORDER BY team, created_at",
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

        self._json({
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
        })

    def _vote(self, code: str) -> None:
        player = self._require_player(code)
        if player is None:
            return
        room = get_room(code)
        if room is None:
            return self._error("ルームが見つかりません。", 404)
        if room["status"] != "voting":
            return self._error("結果公開後は投票を変更できません。")
        try:
            choices = validate_choices(self._read_json().get("choices", []))
        except ValueError as exc:
            return self._error(str(exc))
        with connect(DB_PATH) as db:
            db.execute("DELETE FROM votes WHERE player_id = ? AND round_no = ?", (player["id"], room["round_no"]))
            for rank_no, hero in enumerate(choices, start=1):
                db.execute(
                    "INSERT INTO votes(player_id, round_no, rank_no, hero) VALUES (?, ?, ?, ?)",
                    (player["id"], room["round_no"], rank_no, hero),
                )
            db.execute("UPDATE players SET ready = 1 WHERE id = ?", (player["id"],))
        maybe_auto_reveal(code)
        self._json({"ok": True})

    def _unready(self, code: str) -> None:
        player = self._require_player(code)
        if player is None:
            return
        room = get_room(code)
        if room is None:
            return self._error("ルームが見つかりません。", 404)
        if room["status"] != "voting":
            return self._error("結果公開後は変更できません。")
        with connect(DB_PATH) as db:
            db.execute("DELETE FROM votes WHERE player_id = ? AND round_no = ?", (player["id"], room["round_no"]))
            db.execute("UPDATE players SET ready = 0 WHERE id = ?", (player["id"],))
        self._json({"ok": True})

    def _reveal(self, code: str) -> None:
        if self._require_host(code) is None:
            return
        with connect(DB_PATH) as db:
            ready_count = db.execute(
                "SELECT COUNT(*) AS count FROM players WHERE room_code = ? AND ready = 1", (code,)
            ).fetchone()["count"]
        if ready_count == 0:
            return self._error("まだ誰も投票していません。")
        reveal_room(code)
        self._json({"ok": True})

    def _settings(self, code: str) -> None:
        if self._require_host(code) is None:
            return
        body = self._read_json()
        with connect(DB_PATH) as db:
            db.execute(
                "UPDATE rooms SET auto_reveal = ?, lobby_ban = ? WHERE code = ?",
                (1 if body.get("auto_reveal") else 0, 1 if body.get("lobby_ban") else 0, code),
            )
        self._json({"ok": True})

    def _reset(self, code: str) -> None:
        room = self._require_host(code)
        if room is None:
            return
        with connect(DB_PATH) as db:
            db.execute("UPDATE players SET ready = 0 WHERE room_code = ?", (code,))
            db.execute(
                "UPDATE rooms SET status = 'voting', round_no = ?, round_seed = ? WHERE code = ?",
                (room["round_no"] + 1, secrets.token_hex(16), code),
            )
        self._json({"ok": True})

    def _leave(self, code: str) -> None:
        player = self._require_player(code)
        if player is None:
            return
        with connect(DB_PATH) as db:
            db.execute("DELETE FROM players WHERE id = ?", (player["id"],))
        self._json({"ok": True})

    def _kick(self, code: str) -> None:
        if self._require_host(code) is None:
            return
        player_id = str(self._read_json().get("player_id", ""))
        with connect(DB_PATH) as db:
            cursor = db.execute("DELETE FROM players WHERE id = ? AND room_code = ?", (player_id, code))
        if cursor.rowcount == 0:
            return self._error("参加者が見つかりません。", 404)
        self._json({"ok": True})


def main() -> None:
    try:
        server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    except OSError as exc:
        print("\n[ERROR] サーバーを起動できませんでした。")
        print(f"ポート {PORT} が他のアプリで使われている可能性があります。")
        print(f"詳細: {exc}")
        input("Enterキーで終了します...")
        raise SystemExit(1)

    url = f"http://127.0.0.1:{PORT}"
    print("=" * 48)
    print(" OW BAN ROOM を起動しました")
    print(f" URL: {url}")
    print(" この黒い画面は閉じないでください")
    print(" 終了: Ctrl+C")
    print("=" * 48)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nサーバーを終了します。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
