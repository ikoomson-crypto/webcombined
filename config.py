# config.py
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

    # Upload folder configuration
    UPLOAD_FOLDER = 'uploads/journal_attachments'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

        SQLALCHEMY_DATABASE_URI = database_url
    else:
        SQLALCHEMY_DATABASE_URI = "sqlite:///combined.db"

    SQLALCHEMY_TRACK_MODIFICATIONS = False


# Export an instance of Config
config = Config()