from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from models import db, User
from ai_crop import predict_crop

BASE_DIR = Path(__file__).resolve().parent


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "agrovision_dev_secret_change_me"

    # ----------------------------
    # Database (SQLite)
    # ----------------------------
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DIR / 'agrovision.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ----------------------------
    # Upload config
    # ----------------------------
    upload_dir = BASE_DIR / "static" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = str(upload_dir)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # 6MB

    db.init_app(app)
    with app.app_context():
        db.create_all()

    # ----------------------------
    # Helpers
    # ----------------------------
    def is_logged_in() -> bool:
        return bool(session.get("user_id"))

    def load_crop_data() -> dict:
        path = BASE_DIR / "data" / "crop_data.json"
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ----------------------------
    # Auth Routes
    # ----------------------------
    @app.get("/")
    def index():
        if is_logged_in():
            return redirect(url_for("dashboard"))
        return render_template("index.html")

    @app.post("/signup")
    def signup():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if len(username) < 3:
            flash("Username must be at least 3 characters.", "danger")
            return redirect(url_for("index"))

        if len(password) < 4:
            flash("Password must be at least 4 characters.", "danger")
            return redirect(url_for("index"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "warning")
            return redirect(url_for("index"))

        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()

        flash("Account created. Please login.", "success")
        return redirect(url_for("index"))

    @app.post("/login")
    def login():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username).first()
        if not user:
            flash("User not found. Please sign up first.", "danger")
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

    # ----------------------------
    # App Routes
    # ----------------------------
    @app.get("/dashboard")
    def dashboard():
        if not is_logged_in():
            flash("Please login first.", "warning")
            return redirect(url_for("index"))
        return render_template("dashboard.html", user=session.get("username"))

    # ----------------------------
    # Phase 3: Upload + Identify
    # ----------------------------
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

        # Real inference (MobileNetV2)
        res = predict_crop(str(save_path))

        result = {
            "crop": res.crop,
            "scientific": res.scientific,
            "confidence": res.confidence,
            "raw_label": res.raw_label,
            "image_url": url_for("static", filename=f"uploads/{filename}")
        }
        return render_template("upload.html", result=result)

    # ----------------------------
    # Phase 4: Growth Simulator
    # ----------------------------
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

        return render_template("growth.html", crop_name=crop_name, crop=crop)

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
