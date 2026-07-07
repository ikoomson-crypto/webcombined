from flask import Flask
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from extensions import db, migrate

from app1.app import app as app1
from app2.app import app as app2
from app3.app import app as app3


def create_app():
    flask_app = Flask(__name__)

    # Load configuration
    flask_app.config.from_object("config.Config")

    # Initialize extensions
    db.init_app(flask_app)
    migrate.init_app(flask_app, db)

    @flask_app.route("/")
    def home():
        return """
        <h2>Web Application Portal</h2>
        <ul>
            <li><a href="/app1/">Liquidity Schedule</a></li>
            <li><a href="/app2/">Asset Register</a></li>
            <li><a href="/app3/">Prepayment</a></li>
        </ul>
        """

    return flask_app


# Create main Flask application
main_app = create_app()


# Combine multiple Flask applications
application = DispatcherMiddleware(
    main_app,
    {
        "/app1": app1,
        "/app2": app2,
        "/app3": app3
    }
)


# Gunicorn entry point
app = application


# Run locally
if __name__ == "__main__":
    from werkzeug.serving import run_simple

    run_simple(
        "localhost",
        5000,
        app,
        use_reloader=True
    )