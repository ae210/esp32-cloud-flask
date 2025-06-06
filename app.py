from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
sensor_data = []

def get_size_class(mass):
    if mass < 8:
        return "S"
    if mass < 10:
        return "M"
            if mass < 14:
        return "L"
            if mass < 21:
        return "2L"
    else:
        return "2L"
@app.route('/')
def index():
    return render_template_string("""
    <h1>よつぼし収穫データ</h1>
    <table border="1">
    <tr><th>推定重量 (g)</th><th>距離 (cm)</th><th>規格</th><th>時刻</th></tr>
    {% for entry in data %}
    {% if entry.device_on %}
    <tr><td clospan="4">📡 Device On {{ entry.timestamp }}</td></tr>
    {% else %}
    <tr>
        <td>{{ "%.1f"|format(entry.mass) }}</td>
        <td>{{"%.1f"|format(entry.distance)}}</td>
        <td>{{ entry.size }}</td>
        <td>{{ entry.timestamp }}</td>
    </tr>
    {% endif %}
    {% endfor %}
    </table>
    <script>
      setTimeout(() => location.reload(), 5000);
    </script>
    """, data=sensor_data)

@app.route('/update', methods=['POST'])
def update():
    data = request.get_json()
    if data:
        # 規格判定をサーバー側で行う
        if "mass" in data and "distance" in data:
            data["size"] = get_size_class(data["mass"])
        elif "device_on" in data:
            pass  # 起動メッセージ用
        else:
            return "Invalid structure", 400

        sensor_data.append(data)
        if len(sensor_data) > 100:
            sensor_data.pop(0)
        return "OK", 200
    return "Invalid", 400

@app.route('/clear', methods=['POST'])
def clear():
    sensor_data.clear()
    return "Cleared", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
