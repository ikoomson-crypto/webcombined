import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        SQLALCHEMY_DATABASE_URI = database_url
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///combined.db"

    SQLALCHEMY_TRACK_MODIFICATIONS = False