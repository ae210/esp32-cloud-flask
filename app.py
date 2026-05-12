# app.py
#
# Required packages:
#   pip install flask flask_sqlalchemy psycopg2-binary python-dotenv
#
# Environment variable:
#   DATABASE_URL="postgresql://......neon.tech/neondb?sslmode=require&channel_binding=require"
# Set this in .env for local development or in Render Environment Variables.

from flask import Flask, request, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from dotenv import load_dotenv
from collections import OrderedDict
import os
import json

# Load .env file for local development
load_dotenv()

app = Flask(__name__)

# --- Neon PostgreSQL connection setting ---
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL is not set")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --- Size classification logic ---
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
        return "2L"


# --- Database table definition ---
class HarvestData(db.Model):
    __tablename__ = "harvest_data"

    id = db.Column(db.Integer, primary_key=True)

    # Timestamp sent from the device
    # Existing Neon table is likely "timestamp without time zone"
    timestamp = db.Column(db.DateTime, index=True)

    # Device power-on event flag
    device_on = db.Column(db.Boolean, default=False)

    # Measurement data
    mass = db.Column(db.Float, nullable=True)
    distance = db.Column(db.Float, nullable=True)
    size = db.Column(db.String(8), nullable=True)

    # Optional temperature data
    temp = db.Column(db.Float, nullable=True)

    # Server-side registration time
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


with app.app_context():
    db.create_all()


# --- Utility functions ---
def parse_datetime(value):
    """Convert timestamp value to datetime if possible."""
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    s = str(value).strip()
    s = s.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    return None


def get_record_datetime(row):
    """Use device timestamp first, then server created_at."""
    dt = parse_datetime(row.timestamp)
    if dt is not None:
        return dt

    dt = parse_datetime(row.created_at)
    if dt is not None:
        return dt

    return None


def format_date_label(dt):
    if dt is None:
        return "Unknown Date"
    return dt.strftime("%Y-%m-%d")


def format_time_label(dt, raw_timestamp):
    if dt is not None:
        return dt.strftime("%H:%M:%S")
    if raw_timestamp is None:
        return "-"
    return str(raw_timestamp)


def avg(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def safe_date_id(date_label):
    return "date-" + str(date_label).replace("-", "").replace("/", "").replace(" ", "-")


# --- Data list page ---
@app.route("/")
def index():
    # Display latest 500 records
    rows = (
        HarvestData.query
        .order_by(HarvestData.created_at.desc())
        .limit(500)
        .all()
    )

    grouped = OrderedDict()

    for row in rows:
        dt = get_record_datetime(row)
        date_label = format_date_label(dt)

        if date_label not in grouped:
            grouped[date_label] = {
                "date": date_label,
                "date_id": safe_date_id(date_label),
                "records": [],
                "time_labels": [],
                "mass_values": [],
                "distance_values": [],
                "temp_values": [],
                "summary": {},
            }

        # Measurement records only
        if not row.device_on:
            time_label = format_time_label(dt, row.timestamp)

            grouped[date_label]["time_labels"].append(time_label)
            grouped[date_label]["mass_values"].append(row.mass)
            grouped[date_label]["distance_values"].append(row.distance)
            grouped[date_label]["temp_values"].append(row.temp)

        grouped[date_label]["records"].append(row)

    # Reverse each day's data so the table and graph flow from old to new
    for group in grouped.values():
        group["records"] = list(reversed(group["records"]))
        group["time_labels"] = list(reversed(group["time_labels"]))
        group["mass_values"] = list(reversed(group["mass_values"]))
        group["distance_values"] = list(reversed(group["distance_values"]))
        group["temp_values"] = list(reversed(group["temp_values"]))

        group["summary"] = {
            "count": len([r for r in group["records"] if not r.device_on]),
            "avg_mass": avg(group["mass_values"]),
            "avg_distance": avg(group["distance_values"]),
            "avg_temp": avg(group["temp_values"]),
        }

    grouped_list = list(grouped.values())

    # Scatter chart data: x = distance, y = weight
    chart_data = []
    for group in grouped_list:
        scatter_points = []

        for distance, mass in zip(group["distance_values"], group["mass_values"]):
            if distance is not None and mass is not None:
                scatter_points.append({
                    "x": distance,
                    "y": mass
                })

        chart_data.append({
            "date": group["date"],
            "points": scatter_points,
        })

    chart_data_json = json.dumps(chart_data, ensure_ascii=False)

    return render_template_string(
        """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Strawberry Harvest Data</title>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <style>
        html {
            scroll-behavior: smooth;
        }

        body {
            font-family: Arial, Helvetica, sans-serif;
            color: #000000;
            font-size: 20px;
            margin: 20px;
            background-color: #ffffff;
        }

        h1 {
            color: #000000;
            font-size: 38px;
            margin-top: 0;
            margin-bottom: 16px;
        }

        h2 {
            color: #000000;
            font-size: 28px;
            margin-top: 0;
            margin-bottom: 12px;
            border-left: 8px solid #000000;
            padding-left: 12px;
        }

        .delete-all {
            margin-bottom: 16px;
        }

        button {
            font-size: 18px;
            padding: 7px 12px;
            color: #000000;
            background-color: #ffffff;
            border: 1.5px solid #000000;
            border-radius: 4px;
            cursor: pointer;
        }

        button:hover {
            background-color: #eeeeee;
        }

        .layout {
            display: flex;
            gap: 20px;
            align-items: flex-start;
        }

        .sidebar {
            width: 220px;
            min-width: 220px;
            position: sticky;
            top: 16px;
            border: 1.5px solid #000000;
            border-radius: 8px;
            padding: 12px;
            background-color: #ffffff;
            box-sizing: border-box;
        }

        .sidebar-title {
            font-size: 24px;
            font-weight: bold;
            margin-bottom: 10px;
            color: #000000;
        }

        .sidebar a {
            display: block;
            color: #000000;
            text-decoration: none;
            font-size: 18px;
            padding: 8px 4px;
            border-bottom: 1px solid #dddddd;
        }

        .sidebar a:hover {
            background-color: #eeeeee;
        }

        .main-content {
            flex: 1;
            min-width: 0;
        }

        section {
            margin-bottom: 44px;
            scroll-margin-top: 20px;
        }

        .summary {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 12px;
        }

        .summary-card {
            border: 1.5px solid #000000;
            border-radius: 7px;
            padding: 9px 12px;
            min-width: 165px;
            background-color: #f8f8f8;
            color: #000000;
            font-size: 18px;
            box-sizing: border-box;
        }

        .summary-card strong {
            font-size: 20px;
            color: #000000;
        }

        .charts {
            display: block;
            margin-bottom: 14px;
        }

        .chart-box {
            border: 1.5px solid #000000;
            border-radius: 8px;
            padding: 10px;
            background-color: #ffffff;
            height: 360px;
            box-sizing: border-box;
        }

        .chart-title {
            font-size: 21px;
            font-weight: bold;
            color: #000000;
            margin-bottom: 6px;
        }

        .chart-box canvas {
            display: block;
            width: 100% !important;
            height: 300px !important;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            font-size: 20px;
            color: #000000;
            margin-bottom: 28px;
        }

        th, td {
            border: 1.5px solid #000000;
            padding: 9px 12px;
            text-align: center;
            color: #000000;
        }

        th {
            background-color: #f0f0f0;
            font-weight: bold;
            font-size: 20px;
        }

        .device-on {
            font-weight: bold;
            color: #000000;
            background-color: #f8f8f8;
        }

        .no-data {
            font-size: 22px;
            color: #000000;
            margin-top: 24px;
        }

        @media (max-width: 1000px) {
            .layout {
                flex-direction: column;
            }

            .sidebar {
                width: 100%;
                min-width: 0;
                position: static;
            }

            .chart-box {
                height: 320px;
            }

            .chart-box canvas {
                height: 260px !important;
            }
        }
    </style>
</head>

<body>
    <h1>🍓 Strawberry Harvest Data</h1>

    <form method="post" action="/clear" class="delete-all">
        <button type="submit">Delete All</button>
    </form>

    <div class="layout">
        <aside class="sidebar">
            <div class="sidebar-title">Date</div>

            {% if grouped_data|length == 0 %}
                <div>No date available</div>
            {% endif %}

            {% for group in grouped_data %}
                <a href="#{{ group.date_id }}">{{ group.date }}</a>
            {% endfor %}
        </aside>

        <main class="main-content">
            {% if grouped_data|length == 0 %}
                <div class="no-data">No data available.</div>
            {% endif %}

            {% for group in grouped_data %}
                <section id="{{ group.date_id }}">
                    <h2>{{ group.date }}</h2>

                    <div class="summary">
                        <div class="summary-card">
                            Records<br>
                            <strong>{{ group.summary.count }}</strong>
                        </div>

                        <div class="summary-card">
                            Avg. Weight<br>
                            <strong>
                                {% if group.summary.avg_mass is not none %}
                                    {{ "%.1f"|format(group.summary.avg_mass) }} g
                                {% else %}
                                    -
                                {% endif %}
                            </strong>
                        </div>

                        <div class="summary-card">
                            Avg. Distance<br>
                            <strong>
                                {% if group.summary.avg_distance is not none %}
                                    {{ "%.1f"|format(group.summary.avg_distance) }} cm
                                {% else %}
                                    -
                                {% endif %}
                            </strong>
                        </div>

                        <div class="summary-card">
                            Avg. Temperature<br>
                            <strong>
                                {% if group.summary.avg_temp is not none %}
                                    {{ "%.1f"|format(group.summary.avg_temp) }} °C
                                {% else %}
                                    -
                                {% endif %}
                            </strong>
                        </div>
                    </div>

                    <div class="charts">
                        <div class="chart-box">
                            <div class="chart-title">Distance–Weight Relationship</div>
                            <canvas id="scatterChart{{ loop.index0 }}"></canvas>
                        </div>
                    </div>

                    <table>
                        <tr>
                            <th>Weight (g)</th>
                            <th>Distance (cm)</th>
                            <th>Temperature (°C)</th>
                            <th>Size</th>
                            <th>Time</th>
                            <th>Action</th>
                        </tr>

                        {% for entry in group.records %}
                            {% if entry.device_on %}
                                <tr class="device-on">
                                    <td colspan="6">📡 Device turned on at {{ entry.timestamp }}</td>
                                </tr>
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

                                    <td>
                                        {% if entry.temp is not none %}
                                            {{ "%.1f"|format(entry.temp) }}
                                        {% else %}
                                            -
                                        {% endif %}
                                    </td>

                                    <td>{{ entry.size or "-" }}</td>

                                    <td>
                                        {% if entry.timestamp %}
                                            {{ entry.timestamp.strftime("%H:%M:%S") if entry.timestamp.__class__.__name__ == "datetime" else entry.timestamp }}
                                        {% else %}
                                            -
                                        {% endif %}
                                    </td>

                                    <td>
                                        <form method="post" action="/delete" style="display:inline;">
                                            <input type="hidden" name="id" value="{{ entry.id }}">
                                            <button type="submit">Delete</button>
                                        </form>
                                    </td>
                                </tr>
                            {% endif %}
                        {% endfor %}
                    </table>
                </section>
            {% endfor %}
        </main>
    </div>

    <script>
        const chartData = {{ chart_data_json|safe }};

        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: "#000000",
                        font: {
                            size: 16
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: "linear",
                    title: {
                        display: true,
                        text: "Distance (cm)",
                        color: "#000000",
                        font: {
                            size: 18,
                            weight: "bold"
                        }
                    },
                    ticks: {
                        color: "#000000",
                        font: {
                            size: 16
                        }
                    },
                    grid: {
                        color: "#dddddd"
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: "Weight (g)",
                        color: "#000000",
                        font: {
                            size: 18,
                            weight: "bold"
                        }
                    },
                    ticks: {
                        color: "#000000",
                        font: {
                            size: 16
                        }
                    },
                    grid: {
                        color: "#dddddd"
                    }
                }
            }
        };

        function createScatterChart(canvasId, points) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;

            new Chart(canvas, {
                type: "scatter",
                data: {
                    datasets: [{
                        label: "Distance–Weight",
                        data: points,
                        backgroundColor: "#000000",
                        borderColor: "#000000",
                        pointRadius: 5,
                        pointHoverRadius: 7
                    }]
                },
                options: commonOptions
            });
        }

        chartData.forEach((group, index) => {
            createScatterChart("scatterChart" + index, group.points);
        });

        // Auto refresh every 5 seconds
        setTimeout(() => location.reload(), 5000);
    </script>
</body>
</html>
""",
        grouped_data=grouped_list,
        chart_data_json=chart_data_json,
    )


# --- Endpoint for ESP/T-SIM data update ---
@app.route("/update", methods=["POST"])
def update():
    """
    Expected JSON examples:

    Measurement data:
      {
        "timestamp": "2026-05-12T10:00:00",
        "mass": 12.3,
        "distance": 4.5,
        "temp": 24.8
      }

    Device power-on event:
      {
        "timestamp": "2026-05-12T10:05:00",
        "device_on": true
      }
    """
    data = request.get_json()
    if not data:
        return "Invalid", 400

    # Use server time if timestamp is not provided
    ts = parse_datetime(data.get("timestamp"))
    if ts is None:
        ts = datetime.utcnow()

    # Measurement data record
    if "mass" in data and "distance" in data:
        try:
            mass = float(data["mass"])
            distance = float(data["distance"])

            temp = None
            if "temp" in data and data["temp"] is not None:
                temp = float(data["temp"])

        except (TypeError, ValueError):
            return "Invalid mass, distance, or temperature", 400

        size = get_size_class(mass)

        row = HarvestData(
            timestamp=ts,
            device_on=False,
            mass=mass,
            distance=distance,
            temp=temp,
            size=size,
            created_at=datetime.utcnow(),
        )

    # Device power-on event record
    elif "device_on" in data:
        row = HarvestData(
            timestamp=ts,
            device_on=True,
            created_at=datetime.utcnow(),
        )

    else:
        return "Invalid structure", 400

    db.session.add(row)
    db.session.commit()

    return "OK", 200


# --- Delete all records ---
@app.route("/clear", methods=["POST"])
def clear():
    HarvestData.query.delete()
    db.session.commit()
    return redirect(url_for("index"))


# --- Delete selected record ---
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
    # For local execution. On Render, this is usually run by gunicorn.
    app.run(host="0.0.0.0", port=10000, debug=True)
