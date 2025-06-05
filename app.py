from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
sensor_data = []

@app.route('/')
def index():
    return render_template_string("""
    <h1>Sensor Log</h1>
    <table border="1">
    <tr><th>磁気</th><th>距離</th><th>時刻</th></tr>
    {% for entry in data %}
    <tr>
        <td>{{ entry.magnetic }}</td>
        <td>{{ entry.distance }}</td>
        <td>{{ entry.timestamp }}</td>
    </tr>
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
        sensor_data.append(data)
        if len(sensor_data) > 100:
            sensor_data.pop(0)
        return "OK", 200
    return "Invalid", 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
