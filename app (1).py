"""
Orderly - Order, Customer & Product Management (Streamlit app)
Run locally:  streamlit run app.py

Files:
    app.py     -> the pages (this file)
    db.py      -> all the database code
    style.css  -> colours, fonts and layout (copied from the Figma design)
    assets/    -> the logo
"""

import base64
import html
import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db

BASE = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(BASE, "assets", "logo.png")

st.set_page_config(
    page_title="Orderly",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "🛒",
    layout="wide",
)
db.setup_tables()

PAGES = ["Dashboard", "New order", "Orders", "Customers", "Products"]
if "page" not in st.session_state:
    st.session_state["page"] = "Dashboard"


# ------------------------------ styling ------------------------------

with open(os.path.join(BASE, "style.css"), encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


@st.cache_data
def logo_b64():
    """The logo as text, so it can be placed inside our own HTML."""
    if not os.path.exists(LOGO_PATH):
        return ""
    with open(LOGO_PATH, "rb") as f:
        return base64.b64encode(f.read()).decode()


def logo_chip():
    data = logo_b64()
    return f'<div class="logo-chip"><img src="data:image/png;base64,{data}"></div>' if data else ""


def banner(title, subtitle=""):
    sub = f"<p>{html.escape(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="banner"><h1>{html.escape(title)}</h1>{sub}</div>',
                unsafe_allow_html=True)


def heading(text):
    st.markdown(f'<h3 class="section">{html.escape(text)}</h3>', unsafe_allow_html=True)


def notice(kind, msg):
    """kind: success / error / info (all use the Figma colours)."""
    icon = {"success": "✓", "error": "!", "info": "i"}[kind]
    st.markdown(f'<div class="notice {kind}"><b>{icon}</b><span>{html.escape(msg)}</span></div>',
                unsafe_allow_html=True)


def flash(kind, msg):
    """Remember a message across the st.rerun() that follows an action."""
    st.session_state["flash"] = (kind, msg)


def show_flash():
    if "flash" in st.session_state:
        kind, msg = st.session_state.pop("flash")
        notice(kind, msg)


# ------------------------------ helpers ------------------------------

LABELS = {
    "order_id": "Order ID", "product_id": "Product ID", "customer_id": "Customer ID",
    "unit_price": "Price", "order_date": "Order date", "delivery_date": "Delivery date",
    "available": "Availability",
}


def money(x):
    return f"Rs. {x:,.2f}"


def parse_date(text, fallback):
    try:
        return date.fromisoformat(str(text)[:10])
    except Exception:
        return fallback


def cell(col, val, money_cols):
    try:
        if pd.isna(val):
            return "-"
    except (TypeError, ValueError):
        pass
    if col == "status":
        return f'<span class="pill {str(val).lower()}">{html.escape(str(val))}</span>'
    if col == "available":
        return "Available" if val else "Unavailable"
    if col in money_cols:
        return money(val)
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return html.escape(str(val))


def show_table(df, money_cols=(), empty="Nothing here yet."):
    """Draw a table in the Figma style (cream cells, blue borders)."""
    if df.empty:
        notice("info", empty)
        return
    head = "".join(
        f"<th>{html.escape(LABELS.get(c, c.replace('_', ' ').capitalize()))}</th>" for c in df.columns
    )
    body = ""
    for _, r in df.iterrows():
        body += "<tr>" + "".join(f"<td>{cell(c, r[c], money_cols)}</td>" for c in df.columns) + "</tr>"
    st.markdown(
        f'<div class="tbl-wrap"><table class="tbl"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def product_label(row):
    return f"{row['name']} (#{row['product_id']})"


def label_to_id(label):
    return int(label.rsplit("#", 1)[1].rstrip(")"))


def customer_label(row):
    return f"{row['name']} - {row['phone']} (#{row['customer_id']})"


def item_editor(key, labels, initial=None):
    """Editable table of (Product, Quantity). Returns list of (product_id, qty)."""
    if initial is None:
        initial = pd.DataFrame({"Product": pd.Series(dtype="object"),
                                "Quantity": pd.Series(dtype="int64")})
    edited = st.data_editor(
        initial,
        key=key,
        num_rows="dynamic",
        column_config={
            "Product": st.column_config.SelectboxColumn("Product", options=labels, required=True),
            "Quantity": st.column_config.NumberColumn("Quantity", min_value=1, step=1, default=1),
        },
    )
    items = []
    for _, r in edited.iterrows():
        if pd.notna(r["Product"]):
            qty = 1 if pd.isna(r["Quantity"]) else int(r["Quantity"])
            items.append((label_to_id(r["Product"]), qty))
    return items


# ------------------------------ sidebar ------------------------------

def sidebar():
    st.sidebar.markdown(
        f'<div class="side-head">{logo_chip()}<span>ORDERLY!</span></div>',
        unsafe_allow_html=True,
    )
    for name in PAGES:
        kind = "primary" if st.session_state["page"] == name else "secondary"
        if st.sidebar.button(name, key=f"nav_{name}", type=kind):
            st.session_state["page"] = name
            st.rerun()


# ------------------------------ pages --------------------------------

ICONS = {
    "customers": '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>',
    "active": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    "products": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>',
    "revenue": "₹",
}


def tile(icon, value, label):
    return (f'<div class="tile"><div class="ico">{ICONS[icon]}</div>'
            f'<div class="val">{value}</div><div class="lbl">{label}</div></div>')


def page_dashboard():
    st.markdown("<style>.stApp{background:#F3F3F3}</style>", unsafe_allow_html=True)
    hour = db.now_local().hour
    greeting = "Good morning!" if hour < 12 else "Good afternoon!" if hour < 17 else "Good evening!"
    st.markdown(
        f'<div class="banner home">{logo_chip()}<div><h1>{greeting}</h1>'
        "<p>Here’s what’s happening with your business today.</p></div></div>",
        unsafe_allow_html=True,
    )

    s = db.get_stats()
    heading("Today’s overview")
    st.markdown(
        '<div class="tiles">'
        + tile("customers", s["customers"], "Customers")
        + tile("active", s["active_orders"], "Active orders")
        + tile("products", s["products"], "Products")
        + tile("revenue", money(s["revenue"]), "Revenue")
        + "</div>",
        unsafe_allow_html=True,
    )

    heading("Recent orders")
    recent = db.get_orders().head(8)
    show_table(recent[["order_id", "customer", "status", "total"]] if not recent.empty else recent,
               money_cols=("total",),
               empty="No orders yet. Add a customer and a product, then place your first order.")

    due = db.get_upcoming_deliveries(days=3)
    if not due.empty:
        heading("Deliveries due in the next 3 days")
        show_table(due, money_cols=("total",))

    heading("Revenue, last 7 days")
    st.bar_chart(db.get_daily_revenue(7), color="#007AA6")


def page_new_order():
    banner("New order")
    show_flash()

    products = db.get_products(only_available=True)
    customers = db.get_customers()
    if products.empty:
        notice("info", "Add at least one available product first (Products page).")
        return

    # ---- customer ----
    heading("Customer")
    mode = st.radio("Customer type", ["Existing customer", "New customer"],
                    horizontal=True, label_visibility="collapsed")
    customer_id, new_name, new_phone, default_addr = None, "", "", ""
    if mode == "Existing customer":
        if customers.empty:
            notice("info", "No customers yet. Choose “New customer”.")
        else:
            opts = {customer_label(r): r for _, r in customers.iterrows()}
            row = opts[st.selectbox("Select the customer", list(opts))]
            customer_id = int(row["customer_id"])
            default_addr = row["address"] or ""
    else:
        c1, c2 = st.columns(2)
        new_name = c1.text_input("Customer name")
        new_phone = c2.text_input("Phone number")

    # ---- items ----
    heading("Products")
    st.caption("Click the empty row at the bottom of the table to add a product.")
    labels = [product_label(r) for _, r in products.iterrows()]
    items = item_editor("new_order_items", labels)
    price_of = dict(zip(products["product_id"], products["price"]))
    total = sum(price_of[pid] * qty for pid, qty in items)
    st.markdown(f'<div class="total-bar"><span>Total</span><span>{money(total)}</span></div>',
                unsafe_allow_html=True)

    # ---- delivery details ----
    heading("Order details")
    today = db.now_local().date()
    with st.form("order_form"):
        c1, c2 = st.columns(2)
        c1.text_input("Order ID", value="Assigned when placed", disabled=True)
        c2.text_input("Status", value="Active", disabled=True)
        c1.text_input("Order date", value=today.strftime("%d %b %Y"), disabled=True)
        delivery = c2.date_input("Delivery date", value=today + timedelta(days=1), min_value=today)
        c1.text_input("Total", value=money(total), disabled=True)
        address = st.text_input("Address", value=default_addr, key=f"order_addr_{customer_id}")
        placed = st.form_submit_button("Place order", type="primary")

    if placed:
        try:
            if not items:
                raise ValueError("Add at least one product to the order.")
            cid = customer_id
            if mode == "New customer":
                cid = db.add_customer(new_name, new_phone, address)
            if cid is None:
                raise ValueError("Please select a customer.")
            order_id = db.create_order(cid, items, delivery.isoformat(), address)
            st.session_state.pop("new_order_items", None)  # empty the table next time
            flash("success", f"Order #{order_id} placed successfully.")
            st.rerun()
        except ValueError as e:
            notice("error", str(e))


def page_orders():
    banner("Orders")
    show_flash()

    f1, f2 = st.columns([2, 1])
    search = f1.text_input("Search by order ID, customer name or phone")
    status = f2.selectbox("Status", ["All"] + list(db.ORDER_STATUSES))
    orders = db.get_orders(status=None if status == "All" else status, search=search)
    if orders.empty:
        notice("info", "No orders found.")
        return

    show_table(orders[["order_id", "customer", "status", "delivery_date", "total"]],
               money_cols=("total",))
    st.download_button("Download as CSV", orders.to_csv(index=False).encode("utf-8"),
                       "orders.csv", "text/csv")

    # ---- details ----
    heading("Order details")
    oid = st.selectbox("Select the order", orders["order_id"].tolist(),
                       format_func=lambda i: f"Order #{i}")
    order = db.get_order(oid)
    items = db.get_order_items(oid)
    row = orders[orders["order_id"] == oid].iloc[0]

    def fact(label, value):
        return f"<div><span>{label}</span><b>{value}</b></div>"

    st.markdown(
        '<div class="facts">'
        + fact("Customer", html.escape(row["customer"]))
        + fact("Phone", html.escape(row["phone"]))
        + fact("Order date", cell("order_date", row["order_date"], ()))
        + fact("Delivery date", cell("delivery_date", row["delivery_date"], ()))
        + fact("Status", cell("status", row["status"], ()))
        + fact("Address", html.escape(order["address"] or "-"))
        + "</div>",
        unsafe_allow_html=True,
    )
    show_table(items[["product_id", "product", "unit_price", "quantity", "amount"]],
               money_cols=("unit_price", "amount"))
    st.markdown(f'<div class="total-bar"><span>Total</span><span>{money(row["total"])}</span></div>',
                unsafe_allow_html=True)

    if order["status"] != "Active":
        return

    # ---- edit ----
    heading("Edit order")
    customers = db.get_customers()
    c_opts = {customer_label(r): int(r["customer_id"]) for _, r in customers.iterrows()}
    c_labels = list(c_opts)
    current = next(k for k, v in c_opts.items() if v == order["customer_id"])
    e1, e2 = st.columns(2)
    new_cust = e1.selectbox("Customer", c_labels, index=c_labels.index(current), key=f"edit_cust_{oid}")
    new_delivery = e2.date_input("Delivery date",
                                 value=parse_date(order["delivery_date"], db.now_local().date()),
                                 key=f"edit_date_{oid}")
    new_addr = st.text_input("Address", value=order["address"] or "", key=f"edit_addr_{oid}")

    all_products = db.get_products()
    in_order = set(items["product_id"])
    usable = all_products[(all_products["available"] == 1) | (all_products["product_id"].isin(in_order))]
    labels = [product_label(r) for _, r in usable.iterrows()]
    label_by_id = {r["product_id"]: product_label(r) for _, r in all_products.iterrows()}
    initial = pd.DataFrame({
        "Product": [label_by_id[p] for p in items["product_id"]],
        "Quantity": items["quantity"].astype("int64"),
    })
    new_items = item_editor(f"edit_items_{oid}", labels, initial)

    b1, b2, b3, _ = st.columns([1, 1, 1, 2])
    if b1.button("Save changes", type="primary"):
        try:
            db.update_order(oid, c_opts[new_cust], new_items, new_delivery.isoformat(), new_addr)
            flash("success", f"Order #{oid} updated.")
            st.rerun()
        except ValueError as e:
            notice("error", str(e))
    if b2.button("Mark completed"):
        db.set_order_status(oid, "Completed")
        flash("success", f"Order #{oid} marked as completed.")
        st.rerun()
    if b3.button("Cancel order"):
        db.cancel_order(oid)
        flash("success", f"Order #{oid} cancelled.")
        st.rerun()


def page_customers():
    banner("Customers")
    show_flash()
    tab_list, tab_add, tab_manage = st.tabs(["All / Search", "Add customer", "Edit / Delete"])

    with tab_list:
        search = st.text_input("Search by name or phone")
        customers = db.get_customers(search)
        show_table(customers, empty="No customers found.")
        if not customers.empty:
            heading("Previous orders")
            options = {customer_label(r): r["customer_id"] for _, r in customers.iterrows()}
            pick = st.selectbox("Select the customer", list(options), key="hist_cust")
            hist = db.get_orders(customer_id=int(options[pick]))
            show_table(
                hist[["order_id", "order_date", "delivery_date", "status", "total"]] if not hist.empty else hist,
                money_cols=("total",), empty="No previous orders for this customer.",
            )

    with tab_add:
        with st.form("add_customer", clear_on_submit=True):
            name = st.text_input("Name")
            phone = st.text_input("Phone")
            address = st.text_input("Address (optional)")
            submitted = st.form_submit_button("Add customer")
        if submitted:
            try:
                db.add_customer(name, phone, address)
                flash("success", "Customer added successfully.")
                st.rerun()
            except ValueError as e:
                notice("error", str(e))

    with tab_manage:
        customers = db.get_customers()
        if customers.empty:
            notice("info", "No customers yet.")
        else:
            options = {customer_label(r): r for _, r in customers.iterrows()}
            c = options[st.selectbox("Select the customer", list(options), key="manage_cust")]
            cid = int(c["customer_id"])
            with st.form(f"edit_customer_{cid}"):
                name = st.text_input("Name", c["name"])
                phone = st.text_input("Phone", c["phone"])
                address = st.text_input("Address", c["address"] or "")
                save = st.form_submit_button("Save changes")
            if save:
                try:
                    db.update_customer(cid, name, phone, address)
                    flash("success", "Customer updated.")
                    st.rerun()
                except ValueError as e:
                    notice("error", str(e))
            if st.button("Delete customer"):
                try:
                    db.delete_customer(cid)
                    flash("success", "Customer deleted.")
                    st.rerun()
                except ValueError as e:
                    notice("error", str(e))


def page_products():
    banner("Products")
    show_flash()
    tab_list, tab_add, tab_manage = st.tabs(["All products", "Add products", "Edit"])

    with tab_list:
        show_table(db.get_products(), money_cols=("price",), empty="No products yet.")

    with tab_add:
        with st.form("add_product", clear_on_submit=True):
            name = st.text_input("Product name")
            price = st.number_input("Price (Rs.)", min_value=0.0, step=1.0, format="%.2f")
            submitted = st.form_submit_button("Add product")
        if submitted:
            try:
                db.add_product(name, price)
                flash("success", "Product added successfully.")
                st.rerun()
            except ValueError as e:
                notice("error", str(e))

    with tab_manage:
        products = db.get_products()
        if products.empty:
            notice("info", "No products yet.")
        else:
            options = {product_label(r): r for _, r in products.iterrows()}
            p = options[st.selectbox("Select the product", list(options), key="manage_prod")]
            pid = int(p["product_id"])
            with st.form(f"edit_product_{pid}"):
                new_price = st.number_input("New price (Rs.)", min_value=0.0, step=1.0,
                                            value=float(p["price"]), format="%.2f")
                avail = st.selectbox("Availability", ["Available", "Unavailable"],
                                     index=0 if p["available"] else 1)
                update = st.form_submit_button("Update")
            if update:
                try:
                    db.update_product_price(pid, new_price)
                    db.set_product_availability(pid, avail == "Available")
                    flash("success", "Product updated. Existing orders keep their old price.")
                    st.rerun()
                except ValueError as e:
                    notice("error", str(e))


# ------------------------------ router -------------------------------

sidebar()
{
    "Dashboard": page_dashboard,
    "New order": page_new_order,
    "Orders": page_orders,
    "Customers": page_customers,
    "Products": page_products,
}[st.session_state["page"]]()
