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

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --------------------------------
# モデル定義
# --------------------------------
class HarvestData(db.Model):
    __tablename__ = "harvest_data"

    id        = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True, nullable=False)

    mass      = db.Column(db.Float, nullable=True)
    distance  = db.Column(db.Float, nullable=True)
    size      = db.Column(db.String(10), nullable=True)
    temp      = db.Column(db.Float, nullable=True)
    humid     = db.Column(db.Float, nullable=True)


with app.app_context():
    db.create_all()


# --------------------------------
# 共通関数：サイズ分類
# --------------------------------
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


# --------------------------------
# API: ESP からのデータ受信
# --------------------------------
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
        timestamp=datetime.utcnow(),
    )

    db.session.add(row)
    db.session.commit()
    return "OK", 200


# --------------------------------
# UI: ダッシュボード
# --------------------------------
@app.route("/")
def home():
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
# UI: 収穫データ 日別グラフ + 日付リンク
# --------------------------------
@app.route("/harvest")
def harvest_overview():
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

    rows = []
    for r in q.all():
        rows.append({
            "day": r.day,
            "day_str": r.day.isoformat(),
            "max_mass": float(r.max_mass),
            "avg_mass": float(r.avg_mass),
            "min_mass": float(r.min_mass),
        })

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
        table { border-collapse: collapse; margin-top: 16px; }
        th, td { border: 1px solid #333; padding: 4px 8px; font-size: 14px; }
        th { background: #f0f0f0; }
      </style>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
      <a class="back" href="{{ url_for('home') }}">← 前ページ戻る</a>
      <h1>🍓 Harvest Data（日別）</h1>

      <div id="chart-container">
        <canvas id="dayChart"></canvas>
      </div>

      <p>※ 下の表の「日付」をクリックすると、その日のデータ一覧ページに移動します。</p>

      <table>
        <tr>
          <th>日付</th>
          <th>最大 (g)</th>
          <th>平均 (g)</th>
          <th>最小 (g)</th>
        </tr>
        {% for s in stats %}
        <tr>
          <td>
            <a href="{{ url_for('harvest_day_detail', date_str=s.day_str) }}">
              {{ s.day_str }}
            </a>
          </td>
          <td>{{ "%.1f"|format(s.max_mass) }}</td>
          <td>{{ "%.1f"|format(s.avg_mass) }}</td>
          <td>{{ "%.1f"|format(s.min_mass) }}</td>
        </tr>
        {% endfor %}
      </table>

      <script>
        const stats   = {{ stats | tojson }};
        const labels  = stats.map(s => s.day_str);
        const maxData = stats.map(s => s.max_mass);
        const avgData = stats.map(s => s.avg_mass);
        const minData = stats.map(s => s.min_mass);

        const ctx = document.getElementById('dayChart').getContext('2d');

        new Chart(ctx, {
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
            }
          }
        });
      </script>
    </body>
    </html>
    """, stats=rows)


# --------------------------------
# UI: ある1日の収穫データ一覧 + 距離-重量散布図
# --------------------------------
@app.route("/harvest/<date_str>")
def harvest_day_detail(date_str):
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

    # 距離-重量の散布図用データ
    scatter_points = [
        {"x": r.distance, "y": r.mass}
        for r in rows
        if (r.distance is not None) and (r.mass is not None)
    ]

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
        #scatter-container { width: 100%; max-width: 700px; height: 350px; margin-top: 16px; }
      </style>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
      <a href="{{ url_for('harvest_overview') }}">← 日別グラフに戻る</a>
      <h1>🍓 {{ day }} のデータ一覧</h1>

      <h2>距離-重量 グラフ</h2>
      <div id="scatter-container">
        <canvas id="scatterChart"></canvas>
      </div>

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

      <script>
        const scatterData = {{ scatter | tojson }};
        const ctx = document.getElementById('scatterChart').getContext('2d');

        new Chart(ctx, {
          type: 'scatter',
          data: {
            datasets: [{
              label: '距離 vs 重量',
              data: scatterData,
              showLine: false,
              pointRadius: 4,
              borderWidth: 1
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: {
                title: { display: true, text: '距離 (cm)' }
              },
              y: {
                title: { display: true, text: '重量 (g)' },
                beginAtZero: true
              }
            }
          }
        });
      </script>
    </body>
    </html>
    """, day=day, rows=rows, scatter=scatter_points)


# --------------------------------
# UI: 温度グラフ（日 - 平均温度）
# --------------------------------
@app.route("/temp")
def temp_overview():
    q = (
        db.session.query(
            func.date(HarvestData.timestamp).label("day"),
            func.avg(HarvestData.temp).label("avg_temp"),
        )
        .filter(HarvestData.temp != None)
        .group_by(func.date(HarvestData.timestamp))
        .order_by(func.date(HarvestData.timestamp))
    )

    rows = [
        {
            "day_str": r.day.isoformat(),
            "avg_temp": float(r.avg_temp),
        }
        for r in q.all()
    ]

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>温度（日別平均）</title>
      <style>
        body { font-family: sans-serif; padding: 16px; }
        #chart-container { width: 100%; max-width: 900px; height: 400px; }
      </style>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
      <a href="{{ url_for('home') }}">← Dashboard に戻る</a>
      <h1>🌡 温度（日別 平均値）</h1>

      <div id="chart-container">
        <canvas id="tempChart"></canvas>
      </div>

      <script>
        const stats  = {{ stats | tojson }};
        const labels = stats.map(s => s.day_str);
        const data   = stats.map(s => s.avg_temp);

        const ctx = document.getElementById('tempChart').getContext('2d');

        new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: '平均温度 (°C)',
              data: data,
              pointRadius: 4,
              borderWidth: 2
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: '日付' } },
              y: { title: { display: true, text: '温度 (°C)' } }
            }
          }
        });
      </script>
    </body>
    </html>
    """, stats=rows)


# --------------------------------
# UI: 湿度グラフ（日 - 平均湿度）
# --------------------------------
@app.route("/humid")
def humid_overview():
    q = (
        db.session.query(
            func.date(HarvestData.timestamp).label("day"),
            func.avg(HarvestData.humid).label("avg_humid"),
        )
        .filter(HarvestData.humid != None)
        .group_by(func.date(HarvestData.timestamp))
        .order_by(func.date(HarvestData.timestamp))
    )

    rows = [
        {
            "day_str": r.day.isoformat(),
            "avg_humid": float(r.avg_humid),
        }
        for r in q.all()
    ]

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>湿度（日別平均）</title>
      <style>
        body { font-family: sans-serif; padding: 16px; }
        #chart-container { width: 100%; max-width: 900px; height: 400px; }
      </style>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
      <a href="{{ url_for('home') }}">← Dashboard に戻る</a>
      <h1>💧 湿度（日別 平均値）</h1>

      <div id="chart-container">
        <canvas id="humidChart"></canvas>
      </div>

      <script>
        const stats  = {{ stats | tojson }};
        const labels = stats.map(s => s.day_str);
        const data   = stats.map(s => s.avg_humid);

        const ctx = document.getElementById('humidChart').getContext('2d');

        new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: '平均湿度 (%)',
              data: data,
              pointRadius: 4,
              borderWidth: 2
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: '日付' } },
              y: { title: { display: true, text: '湿度 (%)' },
                  suggestedMin: 0, suggestedMax: 100 }
            }
          }
        });
      </script>
    </body>
    </html>
    """, stats=rows)


# --------------------------------
# ローカル実行用
# --------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
