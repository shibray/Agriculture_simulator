from __future__ import annotations

import json
import random
from pathlib import Path

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import db, User, FundCampaign
from ai_crop import predict_crop


BASE_DIR = Path(__file__).resolve().parent


# --------------------------------------------------
# Utility Functions
# --------------------------------------------------

def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def parse_temp_range(s: str) -> tuple[float, float]:
    cleaned = s.replace("°C", "").replace("C", "").replace(" ", "").replace("–", "-")
    parts = cleaned.split("-")
    if len(parts) != 2:
        return (0.0, 50.0)
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return (0.0, 50.0)


def temp_score(temp_c: float, ideal_min: float, ideal_max: float) -> int:
    if ideal_min <= temp_c <= ideal_max:
        return 100
    d = (ideal_min - temp_c) if temp_c < ideal_min else (temp_c - ideal_max)
    score = 100 - (d * 8)
    return int(clamp(score, 0, 100))


def risk_from_score(total: int) -> tuple[str, str]:
    if total >= 75:
        return ("Good", "success")
    if total >= 50:
        return ("Moderate", "warning")
    return ("Risk", "danger")


def fetch_weather(city: str, api_key: str) -> dict:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": f"{city},NP", "appid": api_key, "units": "metric"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------
# Flask App Factory
# --------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "agrovision_secret_key"

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'agrovision.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    upload_dir = BASE_DIR / "static" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024

    # ----------------------------------------------
    # Helper
    # ----------------------------------------------

    def is_logged_in():
        return bool(session.get("user_id"))

    def load_crop_data():
        with open(BASE_DIR / "data" / "crop_data.json", "r", encoding="utf-8") as f:
            return json.load(f)

    # ----------------------------------------------
    # Authentication
    # ----------------------------------------------

    @app.get("/")
    def index():
        if is_logged_in():
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.post("/signup")
    def signup():
        username = request.form.get("username")
        password = request.form.get("password")

        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "warning")
            return redirect(url_for("index"))

        user = User(username=username,
                    password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        flash("Account created. Please login.", "success")
        return redirect(url_for("index"))

    @app.post("/login")
    def login():
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid credentials.", "danger")
            return redirect(url_for("index"))

        session["user_id"] = user.id
        session["username"] = user.username

        return redirect(url_for("dashboard"))

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    # ----------------------------------------------
    # Dashboard
    # ----------------------------------------------

    @app.get("/dashboard")
    def dashboard():
        if not is_logged_in():
            return redirect(url_for("index"))
        return render_template("dashboard.html")

    # ----------------------------------------------
    # Upload + AI Identify
    # ----------------------------------------------

    @app.get("/upload")
    def upload_page():
        return render_template("upload.html", result=None)

    @app.post("/identify")
    def identify_crop():
        file = request.files.get("image")
        if not file:
            return redirect(url_for("upload_page"))

        filename = secure_filename(file.filename)
        save_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        file.save(save_path)

        res = predict_crop(str(save_path))

        result = {
            "crop": res.crop,
            "scientific": res.scientific,
            "confidence": res.confidence,
            "raw_label": res.raw_label,
            "image_url": url_for("static", filename=f"uploads/{filename}")
        }

        return render_template("upload.html", result=result)

    # ----------------------------------------------
    # Growth Simulator
    # ----------------------------------------------

    @app.get("/growth/<crop_name>")
    def growth(crop_name):
        crops = load_crop_data()
        crop = crops.get(crop_name)

        return render_template(
            "growth.html",
            crop_name=crop_name,
            crop=crop,
            recommendation=None,
            weather_result=None
        )

    # ----------------------------------------------
    # Soil Check
    # ----------------------------------------------

    @app.post("/soil-check/<crop_name>")
    def soil_check(crop_name):
        crops = load_crop_data()
        crop = crops.get(crop_name)

        soil = request.form.get("soil_type")
        nutrient = request.form.get("nutrient_level")

        soil_match = soil in crop["soil"]
        nutrient_match = nutrient == crop["nutrients"]["Nitrogen"]

        score = (50 if soil_match else 0) + (50 if nutrient_match else 0)

        if score == 100:
            rec = {"status": "Highly Suitable", "color": "success",
                   "message": "Perfect soil and nutrient match."}
        elif score >= 50:
            rec = {"status": "Moderate", "color": "warning",
                   "message": "Partial match. Improve soil or nutrients."}
        else:
            rec = {"status": "Low Suitability", "color": "danger",
                   "message": "Conditions not suitable."}

        return render_template(
            "growth.html",
            crop_name=crop_name,
            crop=crop,
            recommendation=rec,
            weather_result=None
        )

    # ----------------------------------------------
    # Weather Check
    # ----------------------------------------------

    @app.post("/weather-check/<crop_name>")
    def weather_check(crop_name):
        api_key = "994a5e490ede765c1dd0e9abda4d6a6a"

        crops = load_crop_data()
        crop = crops.get(crop_name)

        region = request.form.get("region")
        city = request.form.get("city")
        soil = request.form.get("soil_type")
        nutrient = request.form.get("nutrient_level")

        w = fetch_weather(city, api_key)

        temp_c = w["main"]["temp"]
        condition = w["weather"][0]["main"]

        ideal_min, ideal_max = parse_temp_range(crop["optimal_temp"])
        weather_component = temp_score(temp_c, ideal_min, ideal_max)

        soil_component = 100 if soil in crop["soil"] else 30
        nutrient_component = 100 if nutrient == crop["nutrients"]["Nitrogen"] else 40
        water_component = 80

        total = int(round(
            0.40 * weather_component +
            0.30 * soil_component +
            0.20 * nutrient_component +
            0.10 * water_component
        ))

        label, color = risk_from_score(total)

        weather_result = {
            "region": region,
            "city": city,
            "temp_c": temp_c,
            "condition": condition,
            "total_score": total,
            "risk_label": label,
            "risk_color": color,
            "breakdown": {
                "weather": int(0.40 * weather_component),
                "soil": int(0.30 * soil_component),
                "nutrient": int(0.20 * nutrient_component),
                "water": int(0.10 * water_component)
            }
        }

        return render_template(
            "growth.html",
            crop_name=crop_name,
            crop=crop,
            recommendation=None,
            weather_result=weather_result
        )

    # ----------------------------------------------
    # Fund System
    # ----------------------------------------------

    @app.get("/fund")
    def fund_page():
        campaigns = FundCampaign.query.all()
        return render_template("fund.html", campaigns=campaigns)

    @app.post("/create-fund")
    def create_fund():
        title = request.form.get("title")
        description = request.form.get("description")
        target = float(request.form.get("target_amount"))
        duration = int(request.form.get("duration_days"))

        raised = round(target * random.uniform(0.3, 0.8), 2)

        suspicious = ["guaranteed", "risk free", "100% profit", "double money"]
        risk_score = sum(25 for word in suspicious if word in description.lower())

        if risk_score == 0:
            trust = "High Trust"
        elif risk_score <= 25:
            trust = "Moderate Risk"
        else:
            trust = "High Risk"

        campaign = FundCampaign(
            user_id=session.get("user_id"),
            title=title,
            description=description,
            target_amount=target,
            raised_amount=raised,
            duration_days=duration,
            risk_score=risk_score,
            trust_label=trust
        )

        db.session.add(campaign)
        db.session.commit()

        return redirect(url_for("fund_page"))

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
