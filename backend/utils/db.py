"""DB 연결 context manager"""

from contextlib import contextmanager
from database import get_connection


@contextmanager
def db_cursor(commit=False):
    """���서만 필요한 경우. commit=True면 자동 커밋."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        if commit:
            conn.commit()
    finally:
        conn.close()


@contextmanager
def db_connection():
    """conn과 cursor 모두 필요한 경우 (수동 커밋 등)."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield conn, cursor
    finally:
        conn.close()
