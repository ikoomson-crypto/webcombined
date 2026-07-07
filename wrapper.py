from flask import Flask
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from extensions import db, migrate

from app1.app import app as app1
from app2.app import app as app2
from app3.app import app as app3


main_app = Flask(__name__)

main_app.config.from_object("config.Config")

db.init_app(main_app)
migrate.init_app(main_app, db)


@main_app.route("/")
def home():
    return """
    <h2>Web Application Portal</h2>
    <ul>
        <li><a href="/app1/">Liquidity Schedule</a></li>
        <li><a href="/app2/">Asset Register</a></li>
        <li><a href="/app3/">Prepayment</a></li>
    </ul>
    """


app = DispatcherMiddleware(
    main_app,
    {
        "/app1": app1,
        "/app2": app2,
        "/app3": app3
    }
)