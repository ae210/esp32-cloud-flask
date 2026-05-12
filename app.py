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
import os

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

    # Timestamp sent from the ESP/T-SIM device
    timestamp = db.Column(db.String(64), index=True)

    # Device power-on event flag
    device_on = db.Column(db.Boolean, default=False)

    # Measurement data
    mass = db.Column(db.Float, nullable=True)
    distance = db.Column(db.Float, nullable=True)
    size = db.Column(db.String(8), nullable=True)

    # Server-side registration time
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


with app.app_context():
    db.create_all()


# --- Data list page ---
@app.route("/")
def index():
    # Display latest 200 records
    rows = (
        HarvestData.query
        .order_by(HarvestData.created_at.desc())
        .limit(200)
        .all()
    )

    return render_template_string(
        """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Strawberry Harvest Data</title>

    <style>
        body {
            font-family: Arial, Helvetica, sans-serif;
            color: #000000;
            font-size: 22px;
            margin: 24px;
            background-color: #ffffff;
        }

        h1 {
            color: #000000;
            font-size: 40px;
            margin-bottom: 20px;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            font-size: 24px;
            color: #000000;
        }

        th, td {
            border: 1.5px solid #000000;
            padding: 12px 16px;
            text-align: center;
            color: #000000;
        }

        th {
            background-color: #f0f0f0;
            font-weight: bold;
            font-size: 24px;
        }

        td {
            font-weight: normal;
        }

        button {
            font-size: 20px;
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

        .delete-all {
            margin-bottom: 16px;
        }

        .device-on {
            font-weight: bold;
            color: #000000;
            background-color: #f8f8f8;
        }
    </style>
</head>

<body>
    <h1> Strawberry Harvest Data</h1>

    <form method="post" action="/clear" class="delete-all">
        <button type="submit">Delete All</button>
    </form>

    <table>
      <tr>
        <th>Weight (g)</th>
        <th>Distance (cm)</th>
        <th>Size</th>
        <th>Time</th>
        <th>Action</th>
      </tr>

      {% for entry in data %}
        {% if entry.device_on %}
          <tr class="device-on">
            <td colspan="5">📡 Device turned on at {{ entry.timestamp }}</td>
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

    <script>
      // Auto refresh every 5 seconds
      setTimeout(() => location.reload(), 1000);
    </script>
</body>
</html>
""",
        data=rows,
    )


# --- Endpoint for ESP/T-SIM data update ---
@app.route("/update", methods=["POST"])
def update():
    """
    Expected JSON examples:

    Measurement data:
      {
        "timestamp": "2026-05-11T10:00:00",
        "mass": 12.3,
        "distance": 4.5
      }

    Device power-on event:
      {
        "timestamp": "2026-05-11T10:05:00",
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
