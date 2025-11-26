import os
from datetime import datetime, timedelta

from flask import (
    Flask,
    request,
    render_template_string,
    redirect,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

# --------------------------------
# Flask & DB 初期化
# --------------------------------
app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL が設定されていません")

# （もし postgres:// 形式の場合は補正したいとき用）
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --------------------------------
# モデル定義
# --------------------------------
class HarvestData(db.Model):
    """
    1レコード = 1回の計測データ
      - timestamp: サーバーが受信した時刻（UTC）
      - mass: 重量[g]
      - distance: 距離[cm]
      - size: S/M/L/2L のサイズ判定
      - temp: 温度[°C]
      - humid: 湿度[%]
    """
    __tablename__ = "harvest_data"

    id        = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True, nullable=False)

    mass      = db.Column(db.Float, nullable=True)
    distance  = db.Column(db.Float, nullable=True)
    size      = db.Column(db.String(10), nullable=True)
    temp      = db.Column(db.Float, nullable=True)
    humid     = db.Column(db.Float, nullable=True)


with app.app_context():
    # テーブルがなければ作成
    db.create_all()


# --------------------------------
# 共通関数：サイズ分類
# --------------------------------
def get_size_class(mass):
    """
    質量[g]から S/M/L/2L を決める簡易ルール
    """
    if mass is None:
        return None
    if mass < 8:
        return "S"
    elif mass < 10:
        return "M"
    elif mass < 14:
        return "L"
    elif mass < 21:
        return "2L"
    else:
        return "2L"  # 一旦 2L 上限


# --------------------------------
# API: ESP からのデータ受信
# --------------------------------
@app.route("/update", methods=["POST"])
def update():
    """
    ESP から JSON を受け取って DB に保存するエンドポイント。

    期待するJSON例:
      {
        "mass": 12.34,
        "distance": 5.67,
        "temp": 23,
        "humid": 48
      }

    timestamp は送ってこなくてOK。サーバー受信時刻を入れる。
    """
    data = request.get_json()
    if not data:
        return "Invalid", 400

    mass     = data.get("mass")
    distance = data.get("distance")
    temp     = data.get("temp")
    humid    = data.get("humid")

    row = HarvestData(
        mass=mass,
        distance=distance,
        size=get_size_class(mass),
        temp=temp,
        humid=humid,
        timestamp=datetime.utcnow(),
    )

    db.session.add(row)
    db.session.commit()
    return "OK", 200


# --------------------------------
# UI: ダッシュボード（トップページ）
# --------------------------------
@app.route("/")
def home():
    """
    パワポ2枚目イメージの「メニュー画面」。
    収穫データ / 温度 / 湿度 への3つのボタン。
    """
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Harvest Dashboard</title>
      <style>
        body { font-family: sans-serif; padding: 16px; background: #f5f5f5; }
        h1 { margin-bottom: 24px; }
        .card-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 16px;
        }
        .card {
          background: white;
          border-radius: 12px;
          padding: 20px;
          text-align: center;
          box-shadow: 0 2px 6px rgba(0,0,0,0.1);
          text-decoration: none;
          color: inherit;
          font-size: 18px;
        }
        .card:hover {
          box-shadow: 0 4px 10px rgba(0,0,0,0.15);
        }
      </style>
    </head>
    <body>
      <h1>📊 Dashboard</h1>
      <div class="card-grid">
        <a class="card" href="{{ url_for('harvest_overview') }}">🍓 収穫データ</a>
        <a class="card" href="{{ url_for('temp_overview') }}">🌡 温度</a>
        <a class="card" href="{{ url_for('humid_overview') }}">💧 湿度</a>
      </div>
    </body>
    </html>
    """)


# --------------------------------
# UI: 収穫データ 日別グラフ
# --------------------------------
@app.route("/harvest")
def harvest_overview():
    """
    日ごとの max / avg / min mass を集計して折れ線グラフ表示。
    グラフのプロットをクリック → /harvest/<date> へ遷移。
    """
    q = (
        db.session.query(
            func.date(HarvestData.timestamp).label("day"),
            func.max(HarvestData.mass).label("max_mass"),
            func.avg(HarvestData.mass).label("avg_mass"),
            func.min(HarvestData.mass).label("min_mass"),
        )
        .filter(HarvestData.mass != None)
        .group_by(func.date(HarvestData.timestamp))
        .order_by(func.date(HarvestData.timestamp))
    )

    rows = [
        {
            "day": r.day.isoformat(),          # "2025-11-26"
            "max_mass": float(r.max_mass),
            "avg_mass": float(r.avg_mass),
            "min_mass": float(r.min_mass),
        }
        for r in q.all()
    ]

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Harvest Data（日別）</title>
      <style>
        body { font-family: sans-serif; padding: 16px; }
        a.back { display: inline-block; margin-bottom: 8px; text-decoration: none; }
        #chart-container { width: 100%; max-width: 900px; height: 400px; }
      </style>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
      <a class="back" href="{{ url_for('home') }}">← 前ページ戻る</a>
      <h1>🍓 Harvest Data（日別）</h1>

      <div id="chart-container">
        <canvas id="dayChart"></canvas>
      </div>

      <p>※ 点をクリックすると、その日のデータ一覧ページに移動します。</p>

      <script>
        const stats   = {{ stats | tojson }};
        const labels  = stats.map(s => s.day);
        const maxData = stats.map(s => s.max_mass);
        const avgData = stats.map(s => s.avg_mass);
        const minData = stats.map(s => s.min_mass);

        const ctx = document.getElementById('dayChart').getContext('2d');

        const chart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [
              { label: '最大', data: maxData, pointRadius: 4, borderWidth: 2 },
              { label: '平均', data: avgData, pointRadius: 4, borderWidth: 2 },
              { label: '最小', data: minData, pointRadius: 4, borderWidth: 2 },
            ]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: '日付' } },
              y: { title: { display: true, text: '重量 (g)' }, beginAtZero: true }
            },
            interaction: { mode: 'nearest', intersect: true }
          }
        });

        // プロットをクリックしたら、その日の詳細ページへ遷移
        document.getElementById('dayChart').onclick = (evt) => {
          const points = chart.getElementsAtEventForMode(
            evt, 'nearest', { intersect: true }, true
          );
          if (!points.length) return;
          const idx = points[0].index;
          const day = labels[idx];   // "2025-11-26"
          window.location.href = "/harvest/" + encodeURIComponent(day);
        };
      </script>
    </body>
    </html>
    """, stats=rows)


# --------------------------------
# UI: ある1日の収穫データ一覧
# --------------------------------
@app.route("/harvest/<date_str>")
def harvest_day_detail(date_str):
    """
    例: /harvest/2025-11-26

    指定日の 00:00〜24:00 のデータをテーブルで一覧表示。
    （今は削除ボタンなどは未実装。あとで追加可能）
    """
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return "Invalid date", 400

    start = datetime.combine(day, datetime.min.time())
    end   = start + timedelta(days=1)

    rows = (
        HarvestData.query
        .filter(HarvestData.timestamp >= start,
                HarvestData.timestamp < end)
        .order_by(HarvestData.timestamp)
        .all()
    )

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Harvest {{ day }}</title>
      <style>
        body { font-family: sans-serif; padding: 16px; }
        table { border-collapse: collapse; margin-top: 12px; }
        th, td { border: 1px solid #333; padding: 4px 8px; font-size: 14px; }
        th { background: #f0f0f0; }
      </style>
    </head>
    <body>
      <a href="{{ url_for('harvest_overview') }}">← 日別グラフに戻る</a>
      <h1>🍓 {{ day }} のデータ一覧</h1>
      <table>
        <tr>
          <th>時刻(UTC)</th>
          <th>重量 (g)</th>
          <th>距離 (cm)</th>
          <th>サイズ</th>
          <th>温度 (°C)</th>
          <th>湿度 (%)</th>
        </tr>
        {% for r in rows %}
        <tr>
          <td>{{ r.timestamp }}</td>
          <td>{{ "%.1f"|format(r.mass or 0) }}</td>
          <td>{{ "%.1f"|format(r.distance or 0) }}</td>
          <td>{{ r.size or "" }}</td>
          <td>{{ "%.1f"|format(r.temp or 0) }}</td>
          <td>{{ "%.1f"|format(r.humid or 0) }}</td>
        </tr>
        {% endfor %}
      </table>
    </body>
    </html>
    """, day=day, rows=rows)


# --------------------------------
# UI: 温度 / 湿度 ページ（ひとまずダミー）
# --------------------------------
@app.route("/temp")
def temp_overview():
    return "🌡 温度グラフページ（あとで実装）"


@app.route("/humid")
def humid_overview():
    return "💧 湿度グラフページ（あとで実装）"


# --------------------------------
# ローカル実行用
# --------------------------------
if __name__ == "__main__":
    # Render では Procfile/コマンドで起動される想定
    app.run(host="0.0.0.0", port=10000, debug=True)
