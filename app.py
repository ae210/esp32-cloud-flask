import os
from datetime import datetime, date, timedelta

from flask import Flask, request, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

app = Flask(__name__)

# --- DB 接続設定 ---
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL が設定されていません")

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# --- モデル ---
class HarvestData(db.Model):
    __tablename__ = "harvest_data"

    id        = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow() + timedelta(hours=9),
        index=True,
        nullable=False
    )

    mass      = db.Column(db.Float, nullable=True)
    distance  = db.Column(db.Float, nullable=True)
    size      = db.Column(db.String(10), nullable=True)
    temp      = db.Column(db.Float, nullable=True)   # ← ここ重要
    humid     = db.Column(db.Float, nullable=True)   # ← ここ重要


with app.app_context():
    db.create_all()


# --- サイズ分類 ---
def get_size_class(mass):
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
        return "2L"


# --- ESP からの受信 ---
@app.route("/update", methods=["POST"])
def update():
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
    )
    db.session.add(row)
    db.session.commit()
    return "OK", 200


# --- 日付一覧を取るヘルパ ---
def get_day_list():
    rows = (
        db.session.query(func.date(HarvestData.timestamp).label("day"))
        .group_by(func.date(HarvestData.timestamp))
        .order_by(func.date(HarvestData.timestamp))
        .all()
    )
    return [r.day for r in rows]


# --- ルート：最新日付に飛ばす ---
@app.route("/")
def root():
    days = get_day_list()
    if not days:
        return "まだデータがありません"

    latest = days[-1]   # 一番新しい日
    return redirect(url_for("day_view", date_str=latest.isoformat()))


# --- メインダッシュボード（日付別） ---
@app.route("/day/<date_str>")
def day_view(date_str):
    # クリックされた日付
    try:
        current_day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return "Invalid date", 400

    # サイドバー用の日付一覧
    days = get_day_list()

    # その日のデータ取得
    start = datetime.combine(current_day, datetime.min.time())
    end   = start + timedelta(days=1)

    rows = (
        HarvestData.query
        .filter(HarvestData.timestamp >= start,
                HarvestData.timestamp < end)
        .order_by(HarvestData.timestamp)
        .all()
    )

    # 距離-重量 scatter 用
    scatter_points = [
        {"x": r.distance, "y": r.mass}
        for r in rows
        if (r.distance is not None) and (r.mass is not None)
    ]

    # 温度グラフ用（時間ごと）
    temp_labels = [r.timestamp.strftime("%H:%M")
                   for r in rows if r.temp is not None]
    temp_values = [r.temp for r in rows if r.temp is not None]

    # 湿度グラフ用（時間ごと）
    humid_labels = [r.timestamp.strftime("%H:%M")
                    for r in rows if r.humid is not None]
    humid_values = [r.humid for r in rows if r.humid is not None]

    # タイトル（今日かどうかで変える）
    title = "今日のデータ" if current_day == date.today() else f"{current_day} のデータ表示"

    return render_template_string("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Harvest Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body {
      margin: 0;
      font-family: sans-serif;
      background: #f5f5f5;
    }
    .layout {
      display: flex;
      height: 100vh;
    }
    .sidebar {
      width: 90px;
      background: #fafafa;
      border-right: 1px solid #ddd;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 8px 4px;
    }
    .arrow {
      font-size: 20px;
      margin: 4px 0;
      color: #555;
    }
    .day-list {
      flex: 1;
      overflow-y: auto;
      width: 100%;
      padding: 4px 0;
    }
    .day-link {
      display: block;
      text-align: center;
      padding: 6px 4px;
      margin: 4px 8px;
      border-radius: 8px;
      text-decoration: none;
      color: #333;
      font-size: 14px;
      background: #fff;
    }
    .day-link.active {
      background: #1976d2;
      color: #fff;
      font-weight: bold;
    }
    .main {
      flex: 1;
      padding: 16px 20px;
      box-sizing: border-box;
      overflow: auto;
    }
    h1 {
      margin-top: 0;
      margin-bottom: 12px;
    }
    .top-row, .bottom-row {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      grid-gap: 16px;
      margin-bottom: 16px;
    }
    .panel {
      background: #fff;
      border-radius: 10px;
      padding: 10px 12px;
      box-shadow: 0 2px 4px rgba(0,0,0,0.06);
      height: 100%;
      box-sizing: border-box;
    }
    .panel h2 {
      margin: 0 0 4px 0;
      font-size: 16px;
    }
    #scatterChart, #tempChart, #humidChart {
      width: 100%;
      height: 260px;
    }
    .table-wrapper {
      max-height: 260px;
      overflow-y: auto;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      font-size: 12px;
    }
    th, td {
      border: 1px solid #999;
      padding: 2px 4px;
      white-space: nowrap;
    }
    th {
      background: #f0f0f0;
    }
  </style>
</head>
<body>
  <div class="layout">
    <!-- サイドバー：日付リスト -->
    <div class="sidebar">
      <div class="arrow">▲</div>
      <div class="day-list">
        {% for d in days %}
          <a class="day-link {% if d == current_day %}active{% endif %}"
             href="{{ url_for('day_view', date_str=d.isoformat()) }}">
            {{ d.strftime('%m/%d') }}
          </a>
        {% endfor %}
      </div>
      <div class="arrow">▼</div>
    </div>

    <!-- メイン部分 -->
    <div class="main">
      <h1>{{ title }}</h1>

      <div class="top-row">
        <div class="panel">
          <h2>距離-重量 グラフ</h2>
          <canvas id="scatterChart"></canvas>
        </div>
        <div class="panel">
          <h2>タイムテーブル</h2>
          <div class="table-wrapper">
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
                <td>{{ "%.0f"|format(r.temp or 0) }}</td>
                <td>{{ "%.0f"|format(r.humid or 0) }}</td>
              </tr>
              {% endfor %}
            </table>
          </div>
        </div>
      </div>

      <div class="bottom-row">
        <div class="panel">
          <h2>温度（時間別）</h2>
          <canvas id="tempChart"></canvas>
        </div>
        <div class="panel">
          <h2>湿度（時間別）</h2>
          <canvas id="humidChart"></canvas>
        </div>
      </div>
    </div>
  </div>

  <script>
    const scatterData  = {{ scatter | tojson }};
    const tempLabels   = {{ temp_labels | tojson }};
    const tempData     = {{ temp_values | tojson }};
    const humidLabels  = {{ humid_labels | tojson }};
    const humidData    = {{ humid_values | tojson }};

    // 距離-重量 scatter
    const scCtx = document.getElementById('scatterChart').getContext('2d');
    new Chart(scCtx, {
      type: 'scatter',
      data: {
        datasets: [{
          label: '距離 vs 重量',
          data: scatterData,
          pointRadius: 4,
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: '距離 (cm)' } },
          y: { title: { display: true, text: '重量 (g)' }, beginAtZero: true }
        }
      }
    });

    // 温度（時間）
    const tCtx = document.getElementById('tempChart').getContext('2d');
    new Chart(tCtx, {
      type: 'line',
      data: {
        labels: tempLabels,
        datasets: [{
          label: '温度 (°C)',
          data: tempData,
          pointRadius: 3,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: '時間 (h)' } },
          y: { title: { display: true, text: '温度 (°C)' } }
        }
      }
    });

    // 湿度（時間）
    const hCtx = document.getElementById('humidChart').getContext('2d');
    new Chart(hCtx, {
      type: 'line',
      data: {
        labels: humidLabels,
        datasets: [{
          label: '湿度 (%)',
          data: humidData,
          pointRadius: 3,
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { title: { display: true, text: '時間 (h)' } },
          y: {
            title: { display: true, text: '湿度 (%)' },
            suggestedMin: 0,
            suggestedMax: 100
          }
        }
      }
    });
  </script>
</body>
</html>
    """,
    title=title,
    current_day=current_day,
    days=days,
    rows=rows,
    scatter=scatter_points,
    temp_labels=temp_labels,
    temp_values=temp_values,
    humid_labels=humid_labels,
    humid_values=humid_values,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
