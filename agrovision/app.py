from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash


# ----------------------------
# Paths / App setup
# ----------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"

app = Flask(__name__)
app.secret_key = "agrovision_dev_secret_change_me"  # for hackathon; can set env later

DATA_DIR.mkdir(exist_ok=True)


# ----------------------------
# JSON Helpers
# ----------------------------
def load_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # If file gets corrupted during hackathon, recover safely
        path.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_users():
    return load_json(USERS_FILE, {"users": []})


def find_user(username: str):
    db = get_users()
    for u in db["users"]:
        if u["username"].lower() == username.lower():
            return u
    return None


# ----------------------------
# Auth guard
# ----------------------------
def login_required():
    return "user" in session


# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def index():
    # If already logged in, jump to dashboard
    if login_required():
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

    db = get_users()

    # Check existing
    for u in db["users"]:
        if u["username"].lower() == username.lower():
            flash("Username already exists. Try a different one.", "warning")
            return redirect(url_for("index"))

    db["users"].append({
        "username": username,
        "password_hash": generate_password_hash(password)
    })
    save_json(USERS_FILE, db)

    flash("Account created! Now login.", "success")
    return redirect(url_for("index"))


@app.post("/login")
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    user = find_user(username)
    if not user:
        flash("User not found. Please sign up first.", "danger")
        return redirect(url_for("index"))

    if not check_password_hash(user["password_hash"], password):
        flash("Wrong password. Try again.", "danger")
        return redirect(url_for("index"))

    session["user"] = user["username"]
    flash("Logged in successfully ✅", "success")
    return redirect(url_for("dashboard"))


@app.get("/dashboard")
def dashboard():
    if not login_required():
        flash("Please login first.", "warning")
        return redirect(url_for("index"))

    return render_template("dashboard.html", user=session.get("user"))


@app.get("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
