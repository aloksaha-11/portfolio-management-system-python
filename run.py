"""Starts Portfolio Rebalancing System (Python version).

    python run.py

Then open http://localhost:8000/ (change the port with PORTFOLIO_PORT).
"""
import logging
import os

from waitress import serve

from portfolio_app import create_app, scheduler
from portfolio_app.services import mail


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app()
    mail.log_configuration_warning()
    scheduler.start()
    host = os.environ.get("PORTFOLIO_HOST", "127.0.0.1")
    port = int(os.environ.get("PORTFOLIO_PORT", "8000"))
    logging.getLogger(__name__).info("Portfolio Rebalancing System is running at http://%s:%s/", host, port)
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
