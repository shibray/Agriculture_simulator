from __future__ import annotations

import json
import random
from pathlib import Path

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# models.py must contain: db, User (with farmer fields), FundCampaign, Investment
from models import db, User, FundCampaign, Investment
from ai_crop import predict_crop

BASE_DIR = Path(__file__).resolve().parent


# -----------------------------
# Utility helpers
# -----------------------------
def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def parse_temp_range(s: str) -> tuple[float, float]:
    if not s:
        return (0.0, 50.0)
    cleaned = s.replace("°C", "").replace("C", "").replace(" ", "").replace("–", "-")
    parts = cleaned.split("-")
    if len(parts) != 2:
        return (0.0, 50.0)
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return (0.0, 50.0)


def temp_score(temp_c: float, ideal_min: float, ideal_max: float) -> int:
    if ideal_min <= temp_c <= ideal_max:
        return 100
    d = (ideal_min - temp_c) if temp_c < ideal_min else (temp_c - ideal_max)
    return int(clamp(100 - (d * 8), 0, 100))


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


# -----------------------------
# App Factory
# -----------------------------
def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "agrovision_dev_secret_change_me"

    # --- DB ---
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'agrovision.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- Uploads ---
    upload_dir = BASE_DIR / "static" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # 6MB

    db.init_app(app)
    with app.app_context():
        db.create_all()

    # -----------------------------
    # Helpers (app-scoped)
    # -----------------------------
    def is_logged_in() -> bool:
        return bool(session.get("user_id"))

    def current_user() -> User | None:
        uid = session.get("user_id")
        if not uid:
            return None
        return User.query.get(uid)

    def load_crop_data() -> dict:
        path = BASE_DIR / "data" / "crop_data.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # -----------------------------
    # Auth
    # -----------------------------
    @app.get("/")
    def index():
        if is_logged_in():
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.post("/signup")
    def signup():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        province = request.form.get("province", "").strip()
        district = request.form.get("district", "").strip()
        municipality = request.form.get("municipality", "").strip()

        farm_size_ropani = request.form.get("farm_size_ropani", "").strip()
        experience_years = request.form.get("experience_years", "").strip()
        primary_crops = request.form.get("primary_crops", "").strip()

        if len(username) < 3:
            flash("Username must be at least 3 characters.", "danger")
            return redirect(url_for("index"))
        if len(password) < 4:
            flash("Password must be at least 4 characters.", "danger")
            return redirect(url_for("index"))
        if not full_name or not phone:
            flash("Full name and phone are required.", "danger")
            return redirect(url_for("index"))
        if not province or not district or not municipality:
            flash("Please complete your location details.", "danger")
            return redirect(url_for("index"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "warning")
            return redirect(url_for("index"))

        farm_size_val = None
        if farm_size_ropani:
            try:
                farm_size_val = float(farm_size_ropani)
            except ValueError:
                farm_size_val = None

        exp_val = None
        if experience_years:
            try:
                exp_val = int(experience_years)
            except ValueError:
                exp_val = None

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            full_name=full_name,
            phone=phone,
            province=province,
            district=district,
            municipality=municipality,
            farm_size_ropani=farm_size_val,
            experience_years=exp_val,
            primary_crops=primary_crops or None,
        )

        db.session.add(user)
        db.session.commit()

        flash("Farmer account created ✅ Please login.", "success")
        return redirect(url_for("index"))

    @app.post("/login")
    def login():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username).first()
        if not user:
            flash("User not found. Please sign up.", "danger")
            return redirect(url_for("index"))

        if not check_password_hash(user.password_hash, password):
            flash("Wrong password.", "danger")
            return redirect(url_for("index"))

        session["user_id"] = user.id
        session["username"] = user.username

        flash("Logged in ✅", "success")
        return redirect(url_for("dashboard"))

    @app.get("/logout")
    def logout():
        session.clear()
        flash("Logged out.", "info")
        return redirect(url_for("index"))

    # -----------------------------
    # Dashboard
    # -----------------------------
    @app.get("/dashboard")
    def dashboard():
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        u = current_user()
        display_name = u.full_name if u else session.get("username", "Farmer")
        return render_template("dashboard.html", user=display_name)

    # -----------------------------
    # Upload + Identify
    # -----------------------------
    @app.get("/upload")
    def upload_page():
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))
        return render_template("upload.html", result=None)

    @app.post("/identify")
    def identify_crop():
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        f = request.files.get("image")
        if not f or not f.filename:
            flash("Please choose an image file.", "danger")
            return redirect(url_for("upload_page"))

        filename = secure_filename(f.filename)
        save_path = Path(app.config["UPLOAD_FOLDER"]) / filename
        f.save(save_path)

        res = predict_crop(str(save_path))

        result = {
            "crop": res.crop,
            "scientific": res.scientific,
            "confidence": res.confidence,
            "raw_label": res.raw_label,
            "is_plant": res.is_plant,
            "suggestions": res.suggestions,
            "image_url": url_for("static", filename=f"uploads/{filename}")
        }
        return render_template("upload.html", result=result)

    # -----------------------------
    # Growth
    # -----------------------------
    @app.get("/growth/<crop_name>")
    def growth(crop_name: str):
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        crops = load_crop_data()
        crop = crops.get(crop_name)
        if not crop:
            flash("Crop data not found for this crop.", "danger")
            return redirect(url_for("upload_page"))

        return render_template(
            "growth.html",
            crop_name=crop_name,
            crop=crop,
            recommendation=None,
            weather_result=None
        )

    # -----------------------------
    # Soil check
    # -----------------------------
    @app.post("/soil-check/<crop_name>")
    def soil_check(crop_name: str):
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        crops = load_crop_data()
        crop = crops.get(crop_name)
        if not crop:
            flash("Crop data not found.", "danger")
            return redirect(url_for("upload_page"))

        soil_type = request.form.get("soil_type", "").strip()
        nutrient_level = request.form.get("nutrient_level", "").strip()

        soil_match = soil_type in crop.get("soil", [])
        required_n = crop["nutrients"]["Nitrogen"]
        nutrient_match = (nutrient_level == required_n)

        score = (50 if soil_match else 0) + (50 if nutrient_match else 0)

        if score == 100:
            recommendation = {
                "status": "Highly Suitable",
                "color": "success",
                "message": "Soil and nutrient levels match the crop’s optimal requirements."
            }
        elif score >= 50:
            recommendation = {
                "status": "Moderately Suitable",
                "color": "warning",
                "message": "Partial match. Improve soil preparation or adjust nutrient inputs for better yield."
            }
        else:
            recommendation = {
                "status": "Low Suitability",
                "color": "danger",
                "message": "Conditions are not suitable. Consider changing soil type and improving NPK balance."
            }

        return render_template(
            "growth.html",
            crop_name=crop_name,
            crop=crop,
            recommendation=recommendation,
            weather_result=None
        )

    # -----------------------------
    # Weather check
    # -----------------------------
    @app.post("/weather-check/<crop_name>")
    def weather_check(crop_name: str):
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        # Hackathon: hardcode key
        api_key = "994a5e490ede765c1dd0e9abda4d6a6a"

        crops = load_crop_data()
        crop = crops.get(crop_name)
        if not crop:
            flash("Crop data not found.", "danger")
            return redirect(url_for("upload_page"))

        region = request.form.get("region", "").strip()
        city = request.form.get("city", "").strip()
        soil_type = request.form.get("soil_type", "").strip()
        nutrient_level = request.form.get("nutrient_level", "").strip()

        try:
            w = fetch_weather(city, api_key)
        except requests.HTTPError:
            flash("Weather API error. Check API key / city selection.", "danger")
            return render_template(
                "growth.html",
                crop_name=crop_name,
                crop=crop,
                recommendation=None,
                weather_result=None
            )

        temp_c = float(w["main"]["temp"])
        condition = w["weather"][0]["main"]
        humidity = float(w["main"].get("humidity", 50))

        ideal_min, ideal_max = parse_temp_range(crop.get("optimal_temp", ""))
        weather_component = temp_score(temp_c, ideal_min, ideal_max)

        soil_ok = soil_type in crop.get("soil", [])
        soil_component = 100 if soil_ok else 30

        required_n = crop["nutrients"]["Nitrogen"]
        nutrient_ok = (nutrient_level == required_n)
        nutrient_component = 100 if nutrient_ok else 40

        rain_mm = 0.0
        if "rain" in w and isinstance(w["rain"], dict):
            rain_mm = float(w["rain"].get("1h", 0.0) or 0.0)
        water_component = 90 if (rain_mm > 0.0 or humidity >= 60) else 50

        total = (
            0.40 * weather_component +
            0.30 * soil_component +
            0.20 * nutrient_component +
            0.10 * water_component
        )
        total_score = int(round(clamp(total, 0, 100)))
        risk_label, risk_color = risk_from_score(total_score)

        weather_result = {
            "region": region,
            "city": city,
            "temp_c": round(temp_c, 1),
            "condition": condition,
            "total_score": total_score,
            "risk_label": risk_label,
            "risk_color": risk_color,
            "breakdown": {
                "weather": int(round(0.40 * weather_component)),
                "soil": int(round(0.30 * soil_component)),
                "nutrient": int(round(0.20 * nutrient_component)),
                "water": int(round(0.10 * water_component)),
            }
        }

        return render_template(
            "growth.html",
            crop_name=crop_name,
            crop=crop,
            recommendation=None,
            weather_result=weather_result
        )

    # -----------------------------
    # Fund hub (Campaigns + Investing)
    # -----------------------------
    @app.get("/fund")
    def fund_page():
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        campaigns = FundCampaign.query.order_by(FundCampaign.id.desc()).all()
        return render_template("fund.html", campaigns=campaigns)

    @app.post("/create-fund")
    def create_fund():
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        try:
            target_amount = float(request.form.get("target_amount", "0") or 0)
        except ValueError:
            target_amount = 0

        try:
            duration_days = int(request.form.get("duration_days", "30") or 30)
        except ValueError:
            duration_days = 30

        if not title or not description or target_amount <= 0:
            flash("Please fill title, description, and a valid target amount.", "danger")
            return redirect(url_for("fund_page"))

        # optional: start from 0 so investing feels real; or keep a small seed for demo
        raised_amount = 0.0

        # Keyword risk scoring
        suspicious_keywords = ["guaranteed", "double money", "risk free", "100% profit", "instant return"]
        risk_score = 0
        desc_lower = description.lower()
        for word in suspicious_keywords:
            if word in desc_lower:
                risk_score += 25
        risk_score = int(clamp(risk_score, 0, 100))

        if risk_score == 0:
            trust_label = "High Trust"
        elif risk_score <= 25:
            trust_label = "Moderate Risk"
        else:
            trust_label = "High Risk"

        campaign = FundCampaign(
            user_id=session.get("user_id"),
            title=title,
            description=description,
            target_amount=target_amount,
            raised_amount=raised_amount,
            duration_days=duration_days,
            risk_score=risk_score,
            trust_label=trust_label
        )
        db.session.add(campaign)
        db.session.commit()

        flash("Campaign created ✅", "success")
        return redirect(url_for("fund_page"))

    @app.post("/invest/<int:campaign_id>")
    def invest(campaign_id: int):
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))

        amount_raw = request.form.get("amount", "").strip()
        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Invalid amount.", "danger")
            return redirect(url_for("fund_page"))

        if amount <= 0:
            flash("Investment must be greater than 0.", "danger")
            return redirect(url_for("fund_page"))

        campaign = FundCampaign.query.get_or_404(campaign_id)

        # Create investment record
        inv = Investment(
            campaign_id=campaign.id,
            investor_id=session.get("user_id"),
            amount=amount
        )

        # Update campaign total
        campaign.raised_amount = float(campaign.raised_amount or 0) + amount

        db.session.add(inv)
        db.session.commit()

        flash("Investment successful ✅", "success")
        return redirect(url_for("fund_page"))

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
