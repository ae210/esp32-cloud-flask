import os
from datetime import datetime, timedelta, timezone

from flask import Flask, request, render_template_string
from flask_sqlalchemy import SQLAlchemy

# JST(日本時間)へのオフセット
JST_OFFSET = timedelta(hours=9)

# --------------------------------
# Flask & DB 初期化
# --------------------------------
app = Flask(__name__)

db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL が設定されていません")

# Render/Neon でたまに "postgres://" になるので補正
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
    # DB には UTC で保存（default=datetime.utcnow）
    timestamp = db.Column(db.DateTime, default=datetime.utcnow,
                          index=True, nullable=False)

    mass      = db.Column(db.Float, nullable=True)
    distance  = db.Column(db.Float, nullable=True)
    size      = db.Column(db.String(10), nullable=True)
    temp      = db.Column(db.Float, nullable=True)   # 温度（ESP は int でも OK）
    humid     = db.Column(db.Float, nullable=True)   # 湿度


# テーブルが無ければ作成
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
    )
    db.session.add(row)
    db.session.commit()
    return "OK", 200


# --------------------------------
# 日付リスト（JST）を取得
# --------------------------------
def get_available_dates_jst():
    """DB にある全 timestamp から JST の日付リストを作る"""
    rows = db.session.query(HarvestData.timestamp) \
                     .order_by(HarvestData.timestamp).all()
    dates = set()
    for (ts,) in rows:
        if ts is None:
            continue
        d = (ts + JST_OFFSET).date()   # UTC → JST に直して日付だけ
        dates.add(d)
    dates = sorted(dates)

    result = []
    for d in dates:
        result.append({
            "date": d,
            "date_str": d.isoformat(),     # 2025-11-26
            "label": d.strftime("%m/%d"),  # 11/26
        })
    return result


# --------------------------------
# ダッシュボード（今日 or 指定日）
#   /?date=YYYY-MM-DD で日付切り替え
# --------------------------------
@app.route("/")
def dashboard():
    # 左サイドバーの日付リスト（JST）
    all_dates = get_available_dates_jst()

    # 今日（JST）
    today_jst = (datetime.utcnow() + JST_OFFSET).date()

    # クエリ ?date=2025-11-26 があればそれ、無ければ今日
    date_str = request.args.get("date")
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = today_jst
    else:
        selected_date = today_jst

    # 選択日の JST 0:00〜24:00 を UTC に変換して DB から取得
    start_jst = datetime.combine(selected_date, datetime.min.time())
    end_jst   = start_jst + timedelta(days=1)
    start_utc = start_jst - JST_OFFSET
    end_utc   = end_jst - JST_OFFSET

    rows = (
        HarvestData.query
        .filter(HarvestData.timestamp >= start_utc,
                HarvestData.timestamp < end_utc)
        .order_by(HarvestData.timestamp)
        .all()
    )

    # タイムテーブル用（JST 文字列に変換）
    table_rows = []
    # 温度・湿度グラフ用（横軸：時刻）
    time_series = []
    # 距離‐重量散布図用
    scatter_points = []

    for r in rows:
        ts_jst = r.timestamp + JST_OFFSET
        table_rows.append({
            "ts": ts_jst.strftime("%Y-%m-%d %H:%M:%S"),
            "mass": float(r.mass) if r.mass is not None else None,
            "distance": float(r.distance) if r.distance is not None else None,
            "size": r.size or "",
            "temp": float(r.temp) if r.temp is not None else None,
            "humid": float(r.humid) if r.humid is not None else None,
        })
        time_series.append({
            "time_str": ts_jst.strftime("%H:%M"),
            "temp": float(r.temp) if r.temp is not None else None,
            "humid": float(r.humid) if r.humid is not None else None,
        })
        if (r.mass is not None) and (r.distance is not None):
            scatter_points.append({
                "x": float(r.distance),
                "y": float(r.mass),
            })

    selected_date_str = selected_date.isoformat()
    is_today = (selected_date == today_jst)

    # --------------------------------
    # HTML テンプレ（全部ここに書いてます）
    # --------------------------------
    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Harvest Dashboard</title>
      <style>
        body {
          font-family: sans-serif;
          margin: 0;
          padding: 0;
          background: #f5f5f5;
        }
        .layout {
          display: flex;
          min-height: 100vh;
        }
        /* 左の縦型日付リスト */
        .sidebar {
          width: 90px;
          background: #ffffff;
          border-right: 1px solid #ddd;
          padding: 12px 8px;
          box-sizing: border-box;
          display: flex;
          flex-direction: column;
          align-items: stretch;
        }
        .sidebar-title {
          font-size: 14px;
          font-weight: bold;
          margin-bottom: 8px;
          text-align: center;
        }
        .date-list {
          flex: 1;
          overflow-y: auto;  /* マウスホイールでスクロール */
        }
        .date-item {
          display: block;
          text-align: center;
          padding: 6px 8px;
          margin-bottom: 4px;
          border-radius: 8px;
          text-decoration: none;
          color: #333;
          border: 1px solid transparent;
          font-size: 13px;
        }
        .date-item.active {
          background: #1976d2;
          color: #fff;
          border-color: #1976d2;
          font-weight: bold;
        }
        .date-item:hover {
          background: #e3f2fd;
        }

        .main {
          flex: 1;
          padding: 16px 24px;
          box-sizing: border-box;
        }
        h1 {
          margin-top: 0;
          margin-bottom: 12px;
        }
        .date-caption {
          color: #666;
          margin-bottom: 20px;
        }

        /* 上段：左 グラフ / 右 テーブル */
        .top-row {
          display: grid;
          grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
          gap: 16px;
          align-items: flex-start;
        }

        .card {
          background: #fff;
          border-radius: 12px;
          box-shadow: 0 2px 6px rgba(0,0,0,0.08);
          padding: 12px 16px;
          box-sizing: border-box;
        }

        /* グラフ高さ固定＆スクロールしない */
        .chart-box {
          width: 100%;
          height: 260px;
        }
        .chart-box canvas {
          width: 100% !important;
          height: 100% !important;
        }

        /* テーブルだけスクロール */
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
          border: 1px solid #ccc;
          padding: 4px 6px;
          text-align: right;
        }
        th {
          background: #f0f0f0;
          position: sticky;
          top: 0;
          z-index: 1;
        }
        th:first-child, td:first-child {
          text-align: left;
        }

        /* 下段：温度・湿度グラフ */
        .bottom-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
          gap: 16px;
          margin-top: 24px;
        }
        .axis-caption {
          text-align: center;
          margin-top: 8px;
          color: #666;
          font-size: 12px;
        }
      </style>
      <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
      <div class="layout">
        <!-- 左の縦型日付リスト -->
        <aside class="sidebar">
          <div class="sidebar-title">日付</div>
          <div class="date-list">
            {% for d in dates %}
              <a href="{{ url_for('dashboard') }}?date={{ d.date_str }}"
                 class="date-item {% if d.date_str == selected_date_str %}active{% endif %}">
                {{ d.label }}
              </a>
            {% endfor %}
          </div>
        </aside>

        <!-- メイン -->
        <main class="main">
          <h1>{% if is_today %}今日のデータ{% else %}{{ selected_date_str }} のデータ{% endif %}</h1>
          <div class="date-caption">表示日: {{ selected_date_str }} (JST)</div>

          <!-- 上段：距離-重量グラフ ＋ タイムテーブル -->
          <div class="top-row">
            <div class="card">
              <h2>距離-重量 グラフ</h2>
              <div class="chart-box">
                <canvas id="scatterChart"></canvas>
              </div>
            </div>

            <div class="card">
              <h2>タイムテーブル</h2>
              <div class="table-wrapper">
                <table>
                  <tr>
                    <th>時刻 (JST)</th>
                    <th>重量 (g)</th>
                    <th>距離 (cm)</th>
                    <th>サイズ</th>
                    <th>温度 (°C)</th>
                    <th>湿度 (%)</th>
                  </tr>
                  {% for r in table_rows %}
                  <tr>
                    <td>{{ r.ts }}</td>
                    <td>{{ "%.1f"|format(r.mass or 0) }}</td>
                    <td>{{ "%.1f"|format(r.distance or 0) }}</td>
                    <td>{{ r.size }}</td>
                    <td>{% if r.temp is not none %}{{ "%.0f"|format(r.temp) }}{% else %}-{% endif %}</td>
                    <td>{% if r.humid is not none %}{{ "%.0f"|format(r.humid) }}{% else %}-{% endif %}</td>
                  </tr>
                  {% endfor %}
                </table>
              </div>
            </div>
          </div>

          <!-- 下段：温度・湿度グラフ -->
          <div class="bottom-row">
            <div class="card">
              <h2>温度（時間ごと）</h2>
              <div class="chart-box">
                <canvas id="tempChart"></canvas>
              </div>
            </div>

            <div class="card">
              <h2>湿度（時間ごと）</h2>
              <div class="chart-box">
                <canvas id="humidChart"></canvas>
              </div>
            </div>
          </div>

          <div class="axis-caption">横軸：時間 (JST)</div>
        </main>
      </div>

      <script>
        const scatterData = {{ scatter | tojson }};
        const timeSeries  = {{ time_series | tojson }};

        const timeLabels = timeSeries.map(p => p.time_str);
        const tempData   = timeSeries.map(p => p.temp);
        const humidData  = timeSeries.map(p => p.humid);

        // 距離-重量散布図
        const scatterCtx = document.getElementById('scatterChart').getContext('2d');
        new Chart(scatterCtx, {
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

        // 温度グラフ
        const tempCtx = document.getElementById('tempChart').getContext('2d');
        new Chart(tempCtx, {
          type: 'line',
          data: {
            labels: timeLabels,
            datasets: [{
              label: '温度 (°C)',
              data: tempData,
              pointRadius: 3,
              borderWidth: 2,
              spanGaps: true
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: '時間' } },
              y: { title: { display: true, text: '温度 (°C)' } }
            }
          }
        });

        // 湿度グラフ
        const humidCtx = document.getElementById('humidChart').getContext('2d');
        new Chart(humidCtx, {
          type: 'line',
          data: {
            labels: timeLabels,
            datasets: [{
              label: '湿度 (%)',
              data: humidData,
              pointRadius: 3,
              borderWidth: 2,
              spanGaps: true
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              x: { title: { display: true, text: '時間' } },
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
    dates=all_dates,
    selected_date_str=selected_date_str,
    is_today=is_today,
    table_rows=table_rows,
    scatter=scatter_points,
    time_series=time_series
    )


# --------------------------------
# ローカル実行用（Render でもそのまま使える）
# --------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
