"""
Orderly - database layer.

Tables:
    customers   (customer_id, name, phone, address)
    products    (product_id, name, price, available)
    orders      (order_id, customer_id, order_date, delivery_date, address, status)
    order_items (item_id, order_id, product_id, quantity, unit_price)

Every function opens its own short-lived connection, so it is safe to use
from Streamlit (which re-runs the script on every click).
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import pandas as pd

try:
    from zoneinfo import ZoneInfo
except ImportError:  # very old Python
    ZoneInfo = None

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orderly.db")

ORDER_STATUSES = ("Active", "Completed", "Cancelled")


def now_local():
    """Current time in India. Streamlit Cloud servers run on UTC, so we
    set the timezone ourselves."""
    try:
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # must be set on EVERY connection
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def setup_tables():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                phone       TEXT NOT NULL UNIQUE,
                address     TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                price       REAL NOT NULL CHECK(price >= 0),
                available   INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id   INTEGER NOT NULL,
                order_date    TEXT,
                delivery_date TEXT,
                address       TEXT DEFAULT '',
                status        TEXT NOT NULL DEFAULT 'Active'
                              CHECK(status IN ('Active', 'Completed', 'Cancelled')),
                FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
            );

            CREATE TABLE IF NOT EXISTS order_items (
                item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id    INTEGER NOT NULL,
                product_id  INTEGER NOT NULL,
                quantity    INTEGER NOT NULL CHECK(quantity > 0),
                unit_price  REAL NOT NULL,   -- price at the time of the order
                FOREIGN KEY (order_id)   REFERENCES orders(order_id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );
        """)
        # If you already have an older orderly.db, add the two new columns to it
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(orders)")]
        if "delivery_date" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN delivery_date TEXT")
        if "address" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN address TEXT DEFAULT ''")


def _df(query, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(query, conn, params=params)


# ============================ CUSTOMERS ============================

def add_customer(name, phone, address=""):
    name, phone, address = name.strip(), phone.strip(), (address or "").strip()
    if not name or not phone:
        raise ValueError("Name and phone number are required.")
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO customers (name, phone, address) VALUES (?, ?, ?)",
                (name, phone, address),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError("A customer with this phone number already exists.")


def get_customers(search=""):
    like = f"%{search.strip()}%"
    return _df(
        """SELECT customer_id, name, phone, address FROM customers
           WHERE name LIKE ? OR phone LIKE ? ORDER BY name""",
        (like, like),
    )


def update_customer(customer_id, name, phone, address=""):
    name, phone = name.strip(), phone.strip()
    if not name or not phone:
        raise ValueError("Name and phone number are required.")
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "UPDATE customers SET name=?, phone=?, address=? WHERE customer_id=?",
                (name, phone, (address or "").strip(), customer_id),
            )
            if not cur.rowcount:
                raise ValueError("Customer not found.")
    except sqlite3.IntegrityError:
        raise ValueError("Another customer already uses this phone number.")


def delete_customer(customer_id):
    with get_conn() as conn:
        used = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE customer_id=?", (customer_id,)
        ).fetchone()[0]
        if used:
            raise ValueError(
                "This customer has orders, so they can't be deleted "
                "(it would break the order history)."
            )
        conn.execute("DELETE FROM customers WHERE customer_id=?", (customer_id,))


# ============================ PRODUCTS =============================

def add_product(name, price):
    name = name.strip()
    if not name:
        raise ValueError("Product name is required.")
    try:
        price = float(price)
    except (TypeError, ValueError):
        raise ValueError("Please enter a valid price.")
    if price < 0:
        raise ValueError("Price cannot be negative.")
    with get_conn() as conn:
        return conn.execute(
            "INSERT INTO products (name, price, available) VALUES (?, ?, 1)",
            (name, price),
        ).lastrowid


def get_products(only_available=False):
    q = "SELECT product_id, name, price, available FROM products"
    if only_available:
        q += " WHERE available = 1"
    return _df(q + " ORDER BY name")


def update_product_price(product_id, new_price):
    try:
        new_price = float(new_price)
    except (TypeError, ValueError):
        raise ValueError("Please enter a valid price.")
    if new_price < 0:
        raise ValueError("Price cannot be negative.")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE products SET price=? WHERE product_id=?", (new_price, product_id)
        )
        if not cur.rowcount:
            raise ValueError("Product not found.")


def set_product_availability(product_id, is_available):
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE products SET available=? WHERE product_id=?",
            (1 if is_available else 0, product_id),
        )
        if not cur.rowcount:
            raise ValueError("Product not found.")


# ============================= ORDERS ==============================

def _clean_items(items):
    """Merge duplicate products and validate quantities.
    items: list of (product_id, quantity)."""
    merged = {}
    for pid, qty in items:
        if pid is None:
            continue
        qty = int(qty)
        if qty <= 0:
            raise ValueError("Quantity must be at least 1.")
        merged[int(pid)] = merged.get(int(pid), 0) + qty
    if not merged:
        raise ValueError("Add at least one product to the order.")
    return merged


def create_order(customer_id, items, delivery_date=None, address=""):
    items = _clean_items(items)
    with get_conn() as conn:
        if not conn.execute(
            "SELECT 1 FROM customers WHERE customer_id=?", (customer_id,)
        ).fetchone():
            raise ValueError("Customer not found.")

        rows = []
        for pid, qty in items.items():
            p = conn.execute(
                "SELECT name, price, available FROM products WHERE product_id=?", (pid,)
            ).fetchone()
            if not p:
                raise ValueError(f"Product #{pid} not found.")
            if not p["available"]:
                raise ValueError(f"'{p['name']}' is currently unavailable.")
            rows.append((pid, qty, p["price"]))

        order_id = conn.execute(
            """INSERT INTO orders (customer_id, order_date, delivery_date, address)
               VALUES (?, ?, ?, ?)""",
            (customer_id, now_local().strftime("%Y-%m-%d %H:%M:%S"),
             delivery_date, (address or "").strip()),
        ).lastrowid
        conn.executemany(
            """INSERT INTO order_items (order_id, product_id, quantity, unit_price)
               VALUES (?, ?, ?, ?)""",
            [(order_id, pid, qty, price) for pid, qty, price in rows],
        )
        return order_id


def get_orders(customer_id=None, status=None, search=""):
    where, params = [], []
    if customer_id is not None:
        where.append("o.customer_id = ?")
        params.append(customer_id)
    if status:
        where.append("o.status = ?")
        params.append(status)
    if search.strip():
        like = f"%{search.strip()}%"
        where.append("(c.name LIKE ? OR c.phone LIKE ? OR CAST(o.order_id AS TEXT) = ?)")
        params += [like, like, search.strip()]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return _df(
        f"""SELECT o.order_id, c.name AS customer, c.phone, o.order_date,
                   o.delivery_date, o.status,
                   COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            {clause}
            GROUP BY o.order_id
            ORDER BY o.order_id DESC""",
        params,
    )


def get_order(order_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        return dict(row) if row else None


def get_order_items(order_id):
    return _df(
        """SELECT oi.product_id, p.name AS product, oi.quantity, oi.unit_price,
                  oi.quantity * oi.unit_price AS amount
           FROM order_items oi JOIN products p ON p.product_id = oi.product_id
           WHERE oi.order_id = ? ORDER BY oi.item_id""",
        (order_id,),
    )


def update_order(order_id, customer_id, items, delivery_date=None, address=""):
    """Edit an Active order: customer, delivery details and/or its items.
    Products already in the order keep their original price."""
    items = _clean_items(items)
    with get_conn() as conn:
        order = conn.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if not order:
            raise ValueError("Order not found.")
        if order["status"] != "Active":
            raise ValueError("Only Active orders can be edited.")

        old_prices = {
            r["product_id"]: r["unit_price"]
            for r in conn.execute(
                "SELECT product_id, unit_price FROM order_items WHERE order_id=?", (order_id,)
            )
        }
        rows = []
        for pid, qty in items.items():
            p = conn.execute(
                "SELECT name, price, available FROM products WHERE product_id=?", (pid,)
            ).fetchone()
            if not p:
                raise ValueError(f"Product #{pid} not found.")
            if pid in old_prices:
                price = old_prices[pid]
            else:
                if not p["available"]:
                    raise ValueError(f"'{p['name']}' is currently unavailable.")
                price = p["price"]
            rows.append((order_id, pid, qty, price))

        conn.execute(
            "UPDATE orders SET customer_id=?, delivery_date=?, address=? WHERE order_id=?",
            (customer_id, delivery_date, (address or "").strip(), order_id),
        )
        conn.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
        conn.executemany(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?,?,?,?)",
            rows,
        )


def set_order_status(order_id, status):
    if status not in ORDER_STATUSES:
        raise ValueError("Invalid status.")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE orders SET status=? WHERE order_id=? AND status='Active'",
            (status, order_id),
        )
        if not cur.rowcount:
            raise ValueError("Active order not found.")


def cancel_order(order_id):
    set_order_status(order_id, "Cancelled")


# ============================ DASHBOARD ============================

def get_stats():
    with get_conn() as conn:
        one = lambda q: conn.execute(q).fetchone()[0]
        return {
            "customers": one("SELECT COUNT(*) FROM customers"),
            "products": one("SELECT COUNT(*) FROM products"),
            "active_orders": one("SELECT COUNT(*) FROM orders WHERE status='Active'"),
            "revenue": one(
                """SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0)
                   FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
                   WHERE o.status != 'Cancelled'"""
            ),
        }


def get_upcoming_deliveries(days=3):
    """Active orders that are due for delivery from today up to `days` days ahead."""
    today = now_local().date()
    last = today + timedelta(days=days)
    return _df(
        """SELECT o.order_id, c.name AS customer, o.delivery_date,
                  COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
           FROM orders o
           JOIN customers c ON c.customer_id = o.customer_id
           LEFT JOIN order_items oi ON oi.order_id = o.order_id
           WHERE o.status = 'Active' AND o.delivery_date BETWEEN ? AND ?
           GROUP BY o.order_id
           ORDER BY o.delivery_date, o.order_id""",
        (today.isoformat(), last.isoformat()),
    )


def get_daily_revenue(days=7):
    """Revenue per day for the last `days` days (days with no orders show 0)."""
    today = now_local().date()
    day_list = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    found = _df(
        """SELECT date(o.order_date) AS day, SUM(oi.quantity * oi.unit_price) AS revenue
           FROM orders o JOIN order_items oi ON oi.order_id = o.order_id
           WHERE o.status != 'Cancelled' AND date(o.order_date) >= ?
           GROUP BY day""",
        (day_list[0],),
    )
    full = pd.DataFrame({"day": day_list}).merge(found, on="day", how="left")
    full["revenue"] = full["revenue"].fillna(0)
    return full.set_index("day")
