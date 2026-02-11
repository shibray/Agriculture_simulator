from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    full_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    province = db.Column(db.String(50))
    district = db.Column(db.String(50))
    municipality = db.Column(db.String(100))

    farm_size_ropani = db.Column(db.Float)
    experience_years = db.Column(db.Integer)
    primary_crops = db.Column(db.String(200))


class FundCampaign(db.Model):
    __tablename__ = "fund_campaigns"   # IMPORTANT

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)

    target_amount = db.Column(db.Float, nullable=False)
    raised_amount = db.Column(db.Float, default=0.0)

    duration_days = db.Column(db.Integer)
    risk_score = db.Column(db.Integer)
    trust_label = db.Column(db.String(50))


class Investment(db.Model):
    __tablename__ = "investments"

    id = db.Column(db.Integer, primary_key=True)

    campaign_id = db.Column(
        db.Integer,
        db.ForeignKey("fund_campaigns.id"),  # MUST MATCH EXACT TABLE NAME
        nullable=False
    )

    investor_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
