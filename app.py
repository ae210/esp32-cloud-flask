from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from datetime import datetime, timezone, timedelta
import os

app = Flask(__name__)
sensor_data = []

JST = timezone(timedelta(hours=9))

def get_size_class(mass):
    # 入力が不正でも落ちないようにガード
    try:
        m = float(mass)
    except (TypeError, ValueError):
        return "—"

    if m < 6:
        return "—"                 # S未満
    elif m < 10:
        return "S"
    elif m < 15:
        return "M"
    elif m < 20:
        return "L"
    elif m < 28:
        return "2L"
    elif m < 37:
        return "3L"
    else:
        return "3L"                # 上限を3Lに固定

def expected_distance_cm(size):
    # 目安距離（不明は空欄）
    return {
        "S": 2.3,
        "M": 3.0,
        "L": 3.4,
        "2L": None,
        "3L": None,
    }.get(size, None)

def now_ts():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

@app.route('/')
def index():
    return render_template_string("""
    <h1>🍓Harvest Data</h1>

    <form method="post" action="/clear" style="margin-bottom:10px;">
        <button type="submit">Delete All</button>
    </form>

    <fieldset style="margin-bottom:12px;">
      <legend>手入力で追加</legend>
      <form method="post" action="/add" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        <label>Weight (g):
          <input type="number" step="0.1" name="mass" required>
        </label>
        <label>Distance (cm):
          <input type="number" step="0.1" name="distance" required>
        </label>
        <button type="submit">Add</button>
      </form>
      <small>サイズ基準：S=6–10, M=10–15, L=15–20, 2L=20–28, 3L=28–37 (g)</small>
    </fieldset>

    <table border="1" cellpadding="6" cellspacing="0">
      <tr>
        <th>#</th>
        <th>Weight (g)</th>
        <th>Distance (cm)</th>
        <th>Size</th>
        <th>Expected Dist (cm)</th>
        <th>Time</th>
        <th>Option</th>
      </tr>
      {% for i, entry in enumerate(data) %}
        {% if entry.device_on %}
          <tr><td colspan="7">📡 Device On {{ entry.timestamp }}</td></tr>
        {% else %}
          <tr>
            <td style="text-align:right;">{{ i+1 }}</td>
            <td style="text-align:right;">{{ "%.1f"|format(entry.mass) if entry.mass is not none else "" }}</td>
            <td style="text-align:right;">{{ "%.1f"|format(entry.distance) if entry.distance is not none else "" }}</td>
            <td>{{ entry.size }}</td>
            <td style="text-align:right;">
              {% if entry.expected is not none %}{{ "%.1f"|format(entry.expected) }}{% endif %}
            </td>
            <td>{{ entry.timestamp }}</td>
            <td>
              <form method="post" action="/delete" style="display:inline;">
                <input type="hidden" name="timestamp" value="{{ entry.timestamp }}">
                <button type="submit">🗑️</button>
              </form>
            </td>
          </tr>
        {% endif %}
      {% endfor %}
    </table>

    <script>
      // 5秒ごとに自動更新
      setTimeout(() => location.reload(), 5000);
    </script>
    """, data=sensor_data)

@app.route('/add', methods=['POST'])
def add():
    mass = request.form.get("mass")
    distance = request.form.get("distance")
    try:
        mass = float(mass)
        distance = float(distance)
    except (TypeError, ValueError):
        return "Invalid input", 400

    size = get_size_class(mass)
    sensor_data.append({
        "mass": mass,
        "distance": distance,
        "size": size,
        "expected": expected_distance_cm(size),
        "timestamp": now_ts()
    })
    if len(sensor_data) > 100:
        sensor_data.pop(0)
    return redirect(url_for('index'))

@app.route('/update', methods=['POST'])
def update():
    data = request.get_json(silent=True)
    if not data:
        return "Invalid", 400

    # device_on イベントか、計測データかを判定
    if "device_on" in data:
        item = {
            "device_on": bool(data.get("device_on")),
            "timestamp": data.get("timestamp") or now_ts()
        }
        sensor_data.append(item)
    elif "mass" in data and "distance" in data:
        try:
            mass = float(data.get("mass"))
            distance = float(data.get("distance"))
        except (TypeError, ValueError):
            return "Invalid numbers", 400

        size = get_size_class(mass)
        item = {
            "mass": mass,
            "distance": distance,
            "size": size,
            "expected": expected_distance_cm(size),
            "timestamp": data.get("timestamp") or now_ts()
        }
        sensor_data.append(item)
    else:
        return "Invalid structure", 400

    if len(sensor_data) > 100:
        sensor_data.pop(0)
    return "OK", 200

@app.route('/clear', methods=['POST'])
def clear():
    sensor_data.clear()
    return redirect(url_for('index'))

@app.route('/delete', methods=['POST'])
def delete():
    timestamp = request.form.get("timestamp")
    global sensor_data
    sensor_data = [entry for entry in sensor_data if str(entry.get("timestamp")) != str(timestamp)]
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", "10000"))  # Render 対応
    app.run(host='0.0.0.0', port=port)
