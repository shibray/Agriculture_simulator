from __future__ import annotations
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class FundCampaign(db.Model):
    __tablename__ = "fund_campaigns"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)

    target_amount = db.Column(db.Float, nullable=False)
    raised_amount = db.Column(db.Float, default=0.0)

    duration_days = db.Column(db.Integer, nullable=False)

    risk_score = db.Column(db.Integer, default=0)
    trust_label = db.Column(db.String(50), default="Unknown")
