from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import run_simple
from flask import Flask

from app1.app import app as app1
from app2.app import app as app2
from app3.app import app as app3


main_app = Flask(__name__)


@main_app.route("/")
def home():
    return """
    <h2>Main Dashboard</h2>
    <ul>
        <li><a href="/app1">Application 1</a></li>
        <li><a href="/app2">Application 2</a></li>
        <li><a href="/app3">Application 3</a></li>
    </ul>
    """


application = DispatcherMiddleware(
    main_app,
    {
        "/app1": app1,
        "/app2": app2,
        "/app3": app3,
    }
)


if __name__ == "__main__":
    run_simple(
        "localhost",
        5000,
        application,
        use_reloader=True
    )