"""
Orderly - database layer.

Tables:
    customers   (customer_id, name, phone, address)
    products    (product_id, name, price, stock, available)
    orders      (order_id, customer_id, order_date, created_at, delivery_date, note,
                 discount_type, discount_value, amount_paid, status)
    order_items (item_id, order_id, product_id, quantity, unit_price)

Money rules:
    subtotal     = sum of (quantity x unit_price) of the order's items
    discount     = percent of subtotal, or a flat amount
    final amount = subtotal - discount
    pending      = final amount - amount paid
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orderly.db")

ORDER_STATUSES = ("Active", "Completed", "Cancelled")
DISCOUNT_TYPES = ("Percent", "Flat")

# India time (UTC+5:30). Streamlit Cloud servers run on UTC, so we can't
# trust the server clock - that was why the time looked wrong.
IST = timezone(timedelta(hours=5, minutes=30))


def now_local():
    return datetime.now(IST)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # must be set on EVERY connection
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()      # if anything fails, nothing is half-saved
        raise
    finally:
        conn.close()


def _df(query, params=()):
    with get_conn() as conn:
        return pd.read_sql_query(query, conn, params=params)


def _add_column(conn, table, column, definition):
    """Add a column to an old database that doesn't have it yet."""
    existing = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
                stock       INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
                available   INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id    INTEGER NOT NULL,
                order_date     TEXT,
                created_at     TEXT,
                delivery_date  TEXT,
                note           TEXT DEFAULT '',
                discount_type  TEXT NOT NULL DEFAULT 'Percent',
                discount_value REAL NOT NULL DEFAULT 0,
                amount_paid    REAL NOT NULL DEFAULT 0,
                status         TEXT NOT NULL DEFAULT 'Active'
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
        # If you already have an older orderly.db, upgrade it
        _add_column(conn, "products", "stock", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "orders", "created_at", "TEXT")
        _add_column(conn, "orders", "delivery_date", "TEXT")
        _add_column(conn, "orders", "note", "TEXT DEFAULT ''")
        _add_column(conn, "orders", "discount_type", "TEXT NOT NULL DEFAULT 'Percent'")
        _add_column(conn, "orders", "discount_value", "REAL NOT NULL DEFAULT 0")
        _add_column(conn, "orders", "amount_paid", "REAL NOT NULL DEFAULT 0")


# ============================ SMALL HELPERS ============================

def _clean_phone(phone):
    """A phone number must be exactly 10 digits."""
    phone = (phone or "").strip()
    if not (phone.isascii() and phone.isdigit() and len(phone) == 10):
        raise ValueError("Phone number must be exactly 10 digits (numbers only).")
    return phone


def calc_discount(subtotal, discount_type, discount_value):
    """Discount amount in rupees (never more than the subtotal)."""
    if discount_type == "Percent":
        amount = subtotal * discount_value / 100
    else:
        amount = discount_value
    return max(0.0, min(amount, subtotal))


def payment_status(final_amount, paid, status):
    if status == "Cancelled":
        return "-"
    if paid >= final_amount - 0.005:
        return "Paid"
    if paid <= 0:
        return "Pending"
    return "Partly paid"


def _check_discount(discount_type, discount_value):
    if discount_type not in DISCOUNT_TYPES:
        raise ValueError("Invalid discount type.")
    value = float(discount_value or 0)
    if value < 0:
        raise ValueError("Discount cannot be negative.")
    if discount_type == "Percent" and value > 100:
        raise ValueError("Discount cannot be more than 100%.")
    return value


def _check_dates(order_date, delivery_date):
    try:
        od = date.fromisoformat(str(order_date)[:10])
        dd = date.fromisoformat(str(delivery_date)[:10])
    except ValueError:
        raise ValueError("Please choose a valid order date and delivery date.")
    if dd < od:
        raise ValueError("Delivery date cannot be before the order date.")
    return od.isoformat(), dd.isoformat()


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


# ============================ CUSTOMERS ============================

def add_customer(name, phone, address=""):
    name, address = name.strip(), (address or "").strip()
    if not name:
        raise ValueError("Name is required.")
    phone = _clean_phone(phone)
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
    name = name.strip()
    if not name:
        raise ValueError("Name is required.")
    phone = _clean_phone(phone)
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

def add_product(name, price, stock=0):
    name = name.strip()
    if not name:
        raise ValueError("Product name is required.")
    try:
        price = float(price)
        stock = int(stock)
    except (TypeError, ValueError):
        raise ValueError("Please enter a valid price and stock.")
    if price < 0:
        raise ValueError("Price cannot be negative.")
    if stock < 0:
        raise ValueError("Stock cannot be negative.")
    with get_conn() as conn:
        return conn.execute(
            "INSERT INTO products (name, price, stock, available) VALUES (?, ?, ?, 1)",
            (name, price, stock),
        ).lastrowid


def get_products(only_available=False):
    q = "SELECT product_id, name, price, stock, available FROM products"
    if only_available:
        q += " WHERE available = 1"
    return _df(q + " ORDER BY name")


def update_product(product_id, price, stock, is_available):
    try:
        price = float(price)
        stock = int(stock)
    except (TypeError, ValueError):
        raise ValueError("Please enter a valid price and stock.")
    if price < 0:
        raise ValueError("Price cannot be negative.")
    if stock < 0:
        raise ValueError("Stock cannot be negative.")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE products SET price=?, stock=?, available=? WHERE product_id=?",
            (price, stock, 1 if is_available else 0, product_id),
        )
        if not cur.rowcount:
            raise ValueError("Product not found.")


def get_low_stock(limit=5):
    """Available products whose stock is at or below `limit`."""
    return _df(
        """SELECT product_id, name, stock FROM products
           WHERE available = 1 AND stock <= ? ORDER BY stock, name""",
        (limit,),
    )


def get_best_sellers(limit=5):
    """Products sold the most (cancelled orders are not counted)."""
    return _df(
        """SELECT p.name AS product, SUM(oi.quantity) AS qty_sold,
                  SUM(oi.quantity * oi.unit_price) AS sales
           FROM order_items oi
           JOIN orders o ON o.order_id = oi.order_id
           JOIN products p ON p.product_id = oi.product_id
           WHERE o.status != 'Cancelled'
           GROUP BY p.product_id
           ORDER BY qty_sold DESC, sales DESC
           LIMIT ?""",
        (limit,),
    )


# ============================= ORDERS ==============================

def _with_amounts(df):
    """Add discount, final_amount, pending and payment columns to an orders table."""
    df["discount"] = [calc_discount(s, t, v) for s, t, v in
                      zip(df["subtotal"], df["discount_type"], df["discount_value"])]
    df["final_amount"] = df["subtotal"] - df["discount"]
    df["pending"] = [0.0 if st == "Cancelled" else max(0.0, f - p) for f, p, st in
                     zip(df["final_amount"], df["paid"], df["status"])]
    df["payment"] = [payment_status(f, p, st) for f, p, st in
                     zip(df["final_amount"], df["paid"], df["status"])]
    return df


def create_order(customer_id, items, order_date, delivery_date, note="",
                 discount_type="Percent", discount_value=0, amount_paid=0):
    items = _clean_items(items)
    order_date, delivery_date = _check_dates(order_date, delivery_date)
    discount_value = _check_discount(discount_type, discount_value)
    amount_paid = float(amount_paid or 0)
    if amount_paid < 0:
        raise ValueError("Advance payment cannot be negative.")

    with get_conn() as conn:
        if not conn.execute(
            "SELECT 1 FROM customers WHERE customer_id=?", (customer_id,)
        ).fetchone():
            raise ValueError("Customer not found.")

        rows, subtotal = [], 0.0
        for pid, qty in items.items():
            p = conn.execute(
                "SELECT name, price, available, stock FROM products WHERE product_id=?", (pid,)
            ).fetchone()
            if not p:
                raise ValueError(f"Product #{pid} not found.")
            if not p["available"]:
                raise ValueError(f"'{p['name']}' is currently unavailable.")
            if p["stock"] < qty:
                raise ValueError(f"Only {p['stock']} of '{p['name']}' left in stock.")
            rows.append((pid, qty, p["price"]))
            subtotal += qty * p["price"]

        if discount_type == "Flat" and discount_value > subtotal:
            raise ValueError("Discount cannot be more than the order total.")
        final = subtotal - calc_discount(subtotal, discount_type, discount_value)
        if amount_paid > final + 0.005:
            raise ValueError("Advance payment cannot be more than the final amount.")

        order_id = conn.execute(
            """INSERT INTO orders (customer_id, order_date, created_at, delivery_date, note,
                                   discount_type, discount_value, amount_paid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (customer_id, order_date, now_local().strftime("%Y-%m-%d %H:%M:%S"),
             delivery_date, (note or "").strip(), discount_type, discount_value, amount_paid),
        ).lastrowid
        for pid, qty, price in rows:
            conn.execute(
                """INSERT INTO order_items (order_id, product_id, quantity, unit_price)
                   VALUES (?, ?, ?, ?)""",
                (order_id, pid, qty, price),
            )
            conn.execute("UPDATE products SET stock = stock - ? WHERE product_id = ?", (qty, pid))
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
    df = _df(
        f"""SELECT o.order_id, c.name AS customer, c.phone, o.order_date, o.created_at,
                   o.delivery_date, o.status, o.note, o.discount_type, o.discount_value,
                   o.amount_paid AS paid,
                   COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS subtotal
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            {clause}
            GROUP BY o.order_id
            ORDER BY o.order_id DESC""",
        params,
    )
    return _with_amounts(df)


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


def update_order(order_id, customer_id, items, order_date, delivery_date, note="",
                 discount_type="Percent", discount_value=0):
    """Edit an Active order. Stock is corrected automatically: the old
    quantities go back to stock, then the new ones are taken out.
    Products already in the order keep their original price."""
    items = _clean_items(items)
    order_date, delivery_date = _check_dates(order_date, delivery_date)
    discount_value = _check_discount(discount_type, discount_value)

    with get_conn() as conn:
        order = conn.execute(
            "SELECT status, amount_paid FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        if not order:
            raise ValueError("Order not found.")
        if order["status"] != "Active":
            raise ValueError("Only Active orders can be edited.")
        if not conn.execute("SELECT 1 FROM customers WHERE customer_id=?", (customer_id,)).fetchone():
            raise ValueError("Customer not found.")

        # 1. give the old quantities back to stock
        old_prices = {}
        for r in conn.execute(
            "SELECT product_id, quantity, unit_price FROM order_items WHERE order_id=?", (order_id,)
        ).fetchall():
            old_prices[r["product_id"]] = r["unit_price"]
            conn.execute("UPDATE products SET stock = stock + ? WHERE product_id = ?",
                         (r["quantity"], r["product_id"]))

        # 2. check the new items
        rows, subtotal = [], 0.0
        for pid, qty in items.items():
            p = conn.execute(
                "SELECT name, price, available, stock FROM products WHERE product_id=?", (pid,)
            ).fetchone()
            if not p:
                raise ValueError(f"Product #{pid} not found.")
            if pid in old_prices:
                price = old_prices[pid]
            else:
                if not p["available"]:
                    raise ValueError(f"'{p['name']}' is currently unavailable.")
                price = p["price"]
            if p["stock"] < qty:
                raise ValueError(f"Only {p['stock']} of '{p['name']}' left in stock.")
            rows.append((pid, qty, price))
            subtotal += qty * price

        if discount_type == "Flat" and discount_value > subtotal:
            raise ValueError("Discount cannot be more than the order total.")
        final = subtotal - calc_discount(subtotal, discount_type, discount_value)
        if order["amount_paid"] > final + 0.005:
            raise ValueError(
                f"Rs. {order['amount_paid']:.2f} is already paid, which is more than the new "
                f"final amount (Rs. {final:.2f}). Please adjust the order."
            )

        # 3. save
        conn.execute(
            """UPDATE orders SET customer_id=?, order_date=?, delivery_date=?, note=?,
                                 discount_type=?, discount_value=? WHERE order_id=?""",
            (customer_id, order_date, delivery_date, (note or "").strip(),
             discount_type, discount_value, order_id),
        )
        conn.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
        for pid, qty, price in rows:
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?,?,?,?)",
                (order_id, pid, qty, price),
            )
            conn.execute("UPDATE products SET stock = stock - ? WHERE product_id = ?", (qty, pid))


def set_order_status(order_id, status):
    """Change an Active order to Completed or Cancelled.
    Cancelling puts the items back into stock."""
    if status not in ("Completed", "Cancelled"):
        raise ValueError("Invalid status.")
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE orders SET status=? WHERE order_id=? AND status='Active'",
            (status, order_id),
        )
        if not cur.rowcount:
            raise ValueError("Active order not found.")
        if status == "Cancelled":
            conn.execute(
                """UPDATE products SET stock = stock +
                       (SELECT COALESCE(SUM(quantity), 0) FROM order_items
                        WHERE order_id = ? AND order_items.product_id = products.product_id)
                   WHERE product_id IN (SELECT product_id FROM order_items WHERE order_id = ?)""",
                (order_id, order_id),
            )


def cancel_order(order_id):
    set_order_status(order_id, "Cancelled")


# ============================ PAYMENTS =============================

def add_payment(order_id, amount):
    """Record a payment received for an order."""
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise ValueError("Please enter a valid amount.")
    if amount <= 0:
        raise ValueError("Payment must be more than 0.")
    with get_conn() as conn:
        order = conn.execute(
            "SELECT status, amount_paid, discount_type, discount_value FROM orders WHERE order_id=?",
            (order_id,),
        ).fetchone()
        if not order:
            raise ValueError("Order not found.")
        if order["status"] == "Cancelled":
            raise ValueError("This order is cancelled.")
        subtotal = conn.execute(
            "SELECT COALESCE(SUM(quantity * unit_price), 0) FROM order_items WHERE order_id=?",
            (order_id,),
        ).fetchone()[0]
        final = subtotal - calc_discount(subtotal, order["discount_type"], order["discount_value"])
        pending = final - order["amount_paid"]
        if amount > pending + 0.005:
            raise ValueError(f"Only Rs. {max(pending, 0):.2f} is pending for this order.")
        conn.execute("UPDATE orders SET amount_paid = amount_paid + ? WHERE order_id=?",
                     (amount, order_id))


def mark_fully_paid(order_id):
    orders = get_orders(search=str(order_id))
    row = orders[orders["order_id"] == order_id]
    if row.empty:
        raise ValueError("Order not found.")
    pending = float(row.iloc[0]["pending"])
    if pending <= 0.005:
        raise ValueError("Nothing is pending for this order.")
    add_payment(order_id, pending)


def get_pending_payments():
    """Orders (not cancelled) that still have money to collect, earliest delivery first."""
    df = get_orders()
    df = df[(df["status"] != "Cancelled") & (df["pending"] > 0.005)]
    return df.sort_values(["delivery_date", "order_id"], na_position="last")


# ============================ PRIORITY =============================

def urgency_text(days_left):
    if pd.isna(days_left):
        return "No delivery date"
    if days_left < 0:
        return "Overdue"
    if days_left == 0:
        return "Due today"
    if days_left == 1:
        return "Due tomorrow"
    if days_left <= 3:
        return "Due soon"
    return "Later"


def get_priority_orders():
    """Active orders in the order they should be made: earliest delivery date first."""
    df = get_orders(status="Active")
    today = now_local().date()
    days = []
    for d in df["delivery_date"]:
        try:
            days.append((date.fromisoformat(str(d)[:10]) - today).days)
        except ValueError:
            days.append(None)
    df["days_left"] = pd.array(days, dtype="Int64")
    df = df.sort_values(["days_left", "order_id"], na_position="last")
    df["urgency"] = [urgency_text(d) for d in df["days_left"]]
    df.insert(0, "priority", range(1, len(df) + 1))
    return df


# ======================= DASHBOARD AND REPORTS =======================

def get_stats():
    orders = get_orders()
    live = orders[orders["status"] != "Cancelled"]
    with get_conn() as conn:
        customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    return {
        "customers": customers,
        "products": products,
        "active_orders": int((orders["status"] == "Active").sum()),
        "revenue": float(live["final_amount"].sum()),
        "pending": float(live["pending"].sum()),
    }


def get_monthly_report():
    """One row per month: revenue, orders, average order value and growth %."""
    orders = get_orders()
    live = orders[orders["status"] != "Cancelled"].copy()
    if live.empty:
        return pd.DataFrame(columns=["revenue", "orders", "avg_order_value",
                                     "collected", "growth_percent"])
    live["month"] = live["order_date"].astype(str).str[:7]
    report = live.groupby("month").agg(
        revenue=("final_amount", "sum"),
        orders=("order_id", "count"),
        collected=("paid", "sum"),
    ).sort_index()
    report["avg_order_value"] = report["revenue"] / report["orders"]
    report["growth_percent"] = report["revenue"].pct_change() * 100
    return report


def get_daily_revenue(days=30):
    """Revenue for each of the last `days` days (0 on days with no orders)."""
    today = now_local().date()
    day_list = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    orders = get_orders()
    live = orders[orders["status"] != "Cancelled"].copy()
    live["day"] = live["order_date"].astype(str).str[:10]
    per_day = live.groupby("day")["final_amount"].sum()
    return pd.DataFrame({"revenue": [float(per_day.get(d, 0.0)) for d in day_list]}, index=day_list)
