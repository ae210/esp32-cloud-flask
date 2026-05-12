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

    # Timestamp sent from the ESP/T-SIM device
    timestamp = db.Column(db.String(64), index=True)

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

    # Remove Z if ISO format uses UTC suffix
    s = s.replace("Z", "+00:00")

    # Try ISO format first
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass

    # Try common formats
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
    return str(raw_timestamp)


def avg(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


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
                "records": [],
                "labels": [],
                "mass_values": [],
                "distance_values": [],
                "temp_values": [],
                "summary": {},
            }

        # Measurement records only for graphs
        if not row.device_on:
            time_label = format_time_label(dt, row.timestamp)

            grouped[date_label]["labels"].append(time_label)
            grouped[date_label]["mass_values"].append(row.mass)
            grouped[date_label]["distance_values"].append(row.distance)
            grouped[date_label]["temp_values"].append(row.temp)

        grouped[date_label]["records"].append(row)

    # Reverse each day's graph data so time flows from old to new
    for group in grouped.values():
        group["labels"] = list(reversed(group["labels"]))
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

    chart_data = []
    for group in grouped_list:
        chart_data.append({
            "date": group["date"],
            "labels": group["labels"],
            "mass": group["mass_values"],
            "distance": group["distance_values"],
            "temp": group["temp_values"],
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
        body {
            font-family: Arial, Helvetica, sans-serif;
            color: #000000;
            font-size: 20px;
            margin: 24px;
            background-color: #ffffff;
        }

        h1 {
            color: #000000;
            font-size: 40px;
            margin-bottom: 20px;
        }

        h2 {
            color: #000000;
            font-size: 30px;
            margin-top: 36px;
            margin-bottom: 12px;
            border-left: 8px solid #000000;
            padding-left: 12px;
        }

        .delete-all {
            margin-bottom: 20px;
        }

        button {
            font-size: 18px;
            padding: 8px 14px;
            color: #000000;
            background-color: #ffffff;
            border: 1.5px solid #000000;
            border-radius: 4px;
            cursor: pointer;
        }

        button:hover {
            background-color: #eeeeee;
        }

        .summary {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-bottom: 16px;
        }

        .summary-card {
            border: 1.5px solid #000000;
            border-radius: 8px;
            padding: 10px 14px;
            min-width: 180px;
            background-color: #f8f8f8;
            color: #000000;
            font-size: 20px;
        }

        .summary-card strong {
            font-size: 22px;
            color: #000000;
        }

        .charts {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 18px;
            margin-bottom: 18px;
        }

        .chart-box {
            border: 1.5px solid #000000;
            border-radius: 8px;
            padding: 12px;
            background-color: #ffffff;
        }

        .chart-title {
            font-size: 22px;
            font-weight: bold;
            color: #000000;
            margin-bottom: 8px;
        }

        canvas {
            width: 100%;
            height: 280px;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            font-size: 22px;
            color: #000000;
            margin-bottom: 32px;
        }

        th, td {
            border: 1.5px solid #000000;
            padding: 10px 14px;
            text-align: center;
            color: #000000;
        }

        th {
            background-color: #f0f0f0;
            font-weight: bold;
            font-size: 22px;
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

        @media (max-width: 900px) {
            .charts {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>

<body>
    <h1>🍓 Strawberry Harvest Data</h1>

    <form method="post" action="/clear" class="delete-all">
        <button type="submit">Delete All</button>
    </form>

    {% if grouped_data|length == 0 %}
        <div class="no-data">No data available.</div>
    {% endif %}

    {% for group in grouped_data %}
        <section>
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
                    <div class="chart-title">Weight Trend</div>
                    <canvas id="massChart{{ loop.index0 }}"></canvas>
                </div>

                <div class="chart-box">
                    <div class="chart-title">Distance Trend</div>
                    <canvas id="distanceChart{{ loop.index0 }}"></canvas>
                </div>

                <div class="chart-box">
                    <div class="chart-title">Temperature Trend</div>
                    <canvas id="tempChart{{ loop.index0 }}"></canvas>
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
                            <td>{{ entry.timestamp }}</td>

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
                    ticks: {
                        color: "#000000",
                        font: {
                            size: 15
                        }
                    },
                    title: {
                        display: true,
                        text: "Time",
                        color: "#000000",
                        font: {
                            size: 17,
                            weight: "bold"
                        }
                    },
                    grid: {
                        color: "#dddddd"
                    }
                },
                y: {
                    ticks: {
                        color: "#000000",
                        font: {
                            size: 15
                        }
                    },
                    title: {
                        display: true,
                        color: "#000000",
                        font: {
                            size: 17,
                            weight: "bold"
                        }
                    },
                    grid: {
                        color: "#dddddd"
                    }
                }
            }
        };

        function createLineChart(canvasId, labels, values, label, yTitle, lineColor) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;

            new Chart(canvas, {
                type: "line",
                data: {
                    labels: labels,
                    datasets: [{
                        label: label,
                        data: values,
                        borderColor: lineColor,
                        backgroundColor: lineColor,
                        borderWidth: 2,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        tension: 0.2,
                        spanGaps: true
                    }]
                },
                options: {
                    ...commonOptions,
                    scales: {
                        ...commonOptions.scales,
                        y: {
                            ...commonOptions.scales.y,
                            title: {
                                ...commonOptions.scales.y.title,
                                text: yTitle
                            }
                        }
                    }
                }
            });
        }

        chartData.forEach((group, index) => {
            createLineChart(
                "massChart" + index,
                group.labels,
                group.mass,
                "Weight",
                "Weight (g)",
                "#000000"
            );

            createLineChart(
                "distanceChart" + index,
                group.labels,
                group.distance,
                "Distance",
                "Distance (cm)",
                "#000000"
            );

            createLineChart(
                "tempChart" + index,
                group.labels,
                group.temp,
                "Temperature",
                "Temperature (°C)",
                "#000000"
            );
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
    ts = str(data.get("timestamp", datetime.utcnow().isoformat()))

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
        )

    # Device power-on event record
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
