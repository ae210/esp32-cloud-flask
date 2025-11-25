# app.py
#
# 必要なパッケージ:
#   pip install flask flask_sqlalchemy psycopg2-binary python-dotenv
#
# 環境変数:
#   DATABASE_URL="postgresql://......neon.tech/neondb?sslmode=require&channel_binding=require"
# を .env または Render の Environment に設定しておく。

from flask import Flask, request, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
import os

# .env を使う場合（ローカル開発用）
load_dotenv()

app = Flask(__name__)

# --- Neon(PostgreSQL) 接続設定 ---
# DATABASE_URL は環境変数に設定しておく
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL が設定されていません")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --- サイズ分類ロジック（今まで通り） ---
def get_size_class(mass: float) -> str:
    if mass < 8:
        return "S"
    elif mass < 10:
        return "M"
    elif mass < 14:
        return "L"
    elif mass < 21:
        return "2L"
    else:
        return "2L"  # 上限を2Lに固定


# --- DBテーブル定義 ---
class HarvestData(db.Model):
    __tablename__ = "harvest_data"

    id = db.Column(db.Integer, primary_key=True)

    # ESP側から送られてくる timestamp を文字列のまま保存
    timestamp = db.Column(db.String(64), index=True)

    # デバイスONイベントかどうか
    device_on = db.Column(db.Boolean, default=False)

    # 測定値（通常レコードのときに使用）
    mass = db.Column(db.Float, nullable=True)
    distance = db.Column(db.Float, nullable=True)
    size = db.Column(db.String(8), nullable=True)

    # サーバー側での登録時刻（並び替え用）
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

with app.app_context():
    db.create_all()


# --- 一覧画面（ブラウザ表示） ---
@app.route("/")
def index():
    # 新しい順に200件まで表示（必要なら制限は調整）
    rows = (
        HarvestData.query
        .order_by(HarvestData.created_at.desc())
        .limit(200)
        .all()
    )

    return render_template_string(
        """
    <h1>🍓Harvest Data</h1>

    <form method="post" action="/clear" style="margin-bottom:10px;">
        <button type="submit">Delete All</button>
    </form>

    <table border="1">
      <tr>
        <th>Weight (g)</th>
        <th>Distance (cm)</th>
        <th>Size</th>
        <th>Time</th>
        <th>option</th>
      </tr>
      {% for entry in data %}
        {% if entry.device_on %}
          <tr><td colspan="5">📡 Device On {{ entry.timestamp }}</td></tr>
        {% else %}
          <tr>
            <td>
              {% if entry.mass is not none %}
                {{ "%.1f"|format(entry.mass) }}
              {% else %}
                -
              {% endif %}
            </td>
            <td>
              {% if entry.distance is not none %}
                {{ "%.1f"|format(entry.distance) }}
              {% else %}
                -
              {% endif %}
            </td>
            <td>{{ entry.size or "-" }}</td>
            <td>{{ entry.timestamp }}</td>
            <td>
              <form method="post" action="/delete" style="display:inline;">
                <input type="hidden" name="id" value="{{ entry.id }}">
                <button type="submit">🗑️</button>
              </form>
            </td>
          </tr>
        {% endif %}
      {% endfor %}
    </table>

    <script>
      // 5秒ごとに自動リロード（必要なら変更OK）
      setTimeout(() => location.reload(), 5000);
    </script>
    """,
        data=rows,
    )


# --- ESP32 からの更新用エンドポイント ---
@app.route("/update", methods=["POST"])
def update():
    """
    期待するJSON例:
      { "timestamp": "2025-11-25T10:00:00",
        "mass": 12.3,
        "distance": 4.5 }

    または:
      { "timestamp": "2025-11-25T10:05:00",
        "device_on": true }
    """
    data = request.get_json()
    if not data:
        return "Invalid", 400

    # timestamp が来なかった場合はサーバー時刻を使う
    ts = str(data.get("timestamp", datetime.utcnow().isoformat()))

    # 通常データ（mass + distance）
    if "mass" in data and "distance" in data:
        try:
            mass = float(data["mass"])
            distance = float(data["distance"])
        except (TypeError, ValueError):
            return "Invalid mass or distance", 400

        size = get_size_class(mass)

        row = HarvestData(
            timestamp=ts,
            device_on=False,
            mass=mass,
            distance=distance,
            size=size,
        )

    # デバイスONイベント
    elif "device_on" in data:
        row = HarvestData(
            timestamp=ts,
            device_on=True,
        )

    else:
        return "Invalid structure", 400

    db.session.add(row)
    db.session.commit()
    return "OK", 200


# --- 全削除ボタン ---
@app.route("/clear", methods=["POST"])
def clear():
    HarvestData.query.delete()
    db.session.commit()
    return redirect(url_for("index"))


# --- 個別削除ボタン ---
@app.route("/delete", methods=["POST"])
def delete():
    entry_id = request.form.get("id")
    if entry_id is not None:
        try:
            entry_id_int = int(entry_id)
        except ValueError:
            return redirect(url_for("index"))

        row = HarvestData.query.get(entry_id_int)
        if row:
            db.session.delete(row)
            db.session.commit()

    return redirect(url_for("index"))


if __name__ == "__main__":
    # ローカル実行用。Render では gunicorn などから呼ばれる想定。
    app.run(host="0.0.0.0", port=10000, debug=True)

