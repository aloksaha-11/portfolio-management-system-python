"""MySQL access with PyMySQL.

Each web request gets one connection and one transaction: it is committed when the
request finishes normally and rolled back when an error is raised (like Spring's
@Transactional in the Java version). Background jobs open their own connection.
"""
from contextlib import contextmanager

import pymysql
from flask import g

from .config import database_settings

# MySQL error numbers
DUPLICATE_KEY = 1062
ROW_IS_REFERENCED = 1451
ROW_IS_REFERENCED_2 = 1217


def connect():
    settings = database_settings()
    return pymysql.connect(
        host=settings.host,
        port=settings.port,
        user=settings.user,
        password=settings.password,
        database=settings.database,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        # TIMESTAMP values are read and written in IST, as in the Java app
        init_command="SET time_zone = '+05:30'",
        connect_timeout=10,
    )


def get_db():
    """The connection for the current request, opened on first use."""
    if "db" not in g:
        g.db = connect()
        g.after_commit = []
    return g.db


def after_commit(callback):
    """Runs callback once the current request's transaction has been committed."""
    get_db()
    g.after_commit.append(callback)


def finish_request(success):
    """Commits or rolls back the request transaction and closes the connection."""
    connection = g.pop("db", None)
    callbacks = g.pop("after_commit", [])
    if connection is None:
        return
    try:
        if success:
            connection.commit()
        else:
            connection.rollback()
    finally:
        connection.close()
    if success:
        for callback in callbacks:
            callback()


def rollback_request():
    """Rolls back the request transaction now (used when an API error is returned)."""
    connection = g.get("db")
    if connection is not None:
        connection.rollback()
        g.after_commit = []


@contextmanager
def standalone_transaction():
    """A connection and transaction for background jobs outside a web request."""
    connection = connect()
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def is_error(exception, *codes):
    return isinstance(exception, pymysql.err.MySQLError) and exception.args and exception.args[0] in codes
