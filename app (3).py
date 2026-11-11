"""
Orderly - Order, Customer & Product Management (Streamlit app)
Run:  streamlit run app.py

Files:
    app.py                    -> the pages (this file)
    db.py                     -> all the database code
    assets/logo.png           -> the logo
    .streamlit/config.toml    -> the colours (from the Figma design)
"""

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")

st.set_page_config(page_title="Orderly", page_icon=LOGO_PATH, layout="wide")
db.setup_tables()   # creates the tables the first time


# ------------------------------ helpers ------------------------------

def flash(message):
    """Save a message so it can be shown after the page reloads."""
    st.session_state["flash"] = message


def show_flash():
    if "flash" in st.session_state:
        st.toast(st.session_state.pop("flash"), icon="✅")


def money(x):
    return f"Rs. {x:,.2f}"


def parse_date(text, fallback):
    try:
        return date.fromisoformat(str(text)[:10])
    except Exception:
        return fallback


COLUMN_NAMES = {
    "order_id": "Order ID", "product_id": "Product ID", "customer_id": "Customer ID",
    "unit_price": "Price", "order_date": "Order date", "delivery_date": "Delivery date",
    "available": "Availability",
}


def show_table(df, money_columns=(), empty_message="Nothing here yet."):
    """Show a DataFrame as a neat table (money formatted, nice column names)."""
    if df.empty:
        st.info(empty_message)
        return
    df = df.copy()
    for col in money_columns:
        df[col] = df[col].map(money)
    if "available" in df.columns:
        df["available"] = df["available"].map({1: "Available", 0: "Unavailable"})
    df = df.rename(columns=lambda c: COLUMN_NAMES.get(c, c.replace("_", " ").capitalize()))
    st.dataframe(df, hide_index=True)


def product_label(row):
    return f"{row['name']} (#{row['product_id']})"


def label_to_id(label):
    return int(label.rsplit("#", 1)[1].rstrip(")"))


def customer_label(row):
    return f"{row['name']} - {row['phone']} (#{row['customer_id']})"


def item_editor(key, labels, initial=None):
    """Editable table of (Product, Quantity). Returns a list of (product_id, quantity)."""
    if initial is None:
        initial = pd.DataFrame({"Product": pd.Series(dtype="object"),
                                "Quantity": pd.Series(dtype="int64")})
    edited = st.data_editor(
        initial,
        key=key,
        num_rows="dynamic",          # lets the user add / delete rows
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


# ------------------------------ pages --------------------------------

def page_dashboard():
    hour = db.now_local().hour
    if hour < 12:
        st.title("Good morning!")
    elif hour < 17:
        st.title("Good afternoon!")
    else:
        st.title("Good evening!")
    st.write("Here’s what’s happening with your business today.")

    stats = db.get_stats()
    st.subheader("Today’s overview")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customers", stats["customers"])
    c2.metric("Active orders", stats["active_orders"])
    c3.metric("Products", stats["products"])
    c4.metric("Revenue", money(stats["revenue"]))

    st.subheader("Recent orders")
    recent = db.get_orders().head(8)
    if not recent.empty:
        recent = recent[["order_id", "customer", "status", "total"]]
    show_table(recent, ["total"], "No orders yet. Add a customer and a product, then place an order.")

    due = db.get_upcoming_deliveries(days=3)
    if not due.empty:
        st.subheader("Deliveries due in the next 3 days")
        show_table(due, ["total"])

    st.subheader("Revenue, last 7 days")
    st.bar_chart(db.get_daily_revenue(7), color="#007AA6")


def page_new_order():
    st.title("New order")
    show_flash()

    products = db.get_products(only_available=True)
    customers = db.get_customers()
    if products.empty:
        st.info("Add at least one available product first (Products page).")
        return

    # ---- customer ----
    st.subheader("Customer")
    mode = st.radio("Customer type", ["Existing customer", "New customer"],
                    horizontal=True, label_visibility="collapsed")
    customer_id, new_name, new_phone, default_address = None, "", "", ""
    if mode == "Existing customer":
        if customers.empty:
            st.info("No customers yet. Choose “New customer”.")
        else:
            options = {customer_label(r): r for _, r in customers.iterrows()}
            row = options[st.selectbox("Select the customer", list(options))]
            customer_id = int(row["customer_id"])
            default_address = row["address"] or ""
    else:
        c1, c2 = st.columns(2)
        new_name = c1.text_input("Customer name")
        new_phone = c2.text_input("Phone number")

    # ---- products ----
    st.subheader("Products")
    st.caption("Click the empty row at the bottom of the table to add a product.")
    labels = [product_label(r) for _, r in products.iterrows()]
    items = item_editor("new_order_items", labels)

    price_of = dict(zip(products["product_id"], products["price"]))
    total = sum(price_of[pid] * qty for pid, qty in items)
    st.metric("Total", money(total))

    # ---- order details ----
    st.subheader("Order details")
    today = db.now_local().date()
    with st.form("order_form"):
        c1, c2 = st.columns(2)
        c1.text_input("Order date", value=today.strftime("%d %b %Y"), disabled=True)
        c2.text_input("Status", value="Active", disabled=True)
        delivery_date = c1.date_input("Delivery date", value=today + timedelta(days=1),
                                      min_value=today)
        address = st.text_input("Address", value=default_address, key=f"order_address_{customer_id}")
        placed = st.form_submit_button("Place order", type="primary")

    if placed:
        try:
            if not items:
                raise ValueError("Add at least one product to the order.")
            if mode == "New customer":
                customer_id = db.add_customer(new_name, new_phone, address)
            if customer_id is None:
                raise ValueError("Please select a customer.")
            order_id = db.create_order(customer_id, items, delivery_date.isoformat(), address)
            st.session_state.pop("new_order_items", None)   # empty the table for next time
            flash(f"Order #{order_id} placed successfully.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def page_orders():
    st.title("Orders")
    show_flash()

    c1, c2 = st.columns([2, 1])
    search = c1.text_input("Search by order ID, customer name or phone")
    status = c2.selectbox("Status", ["All"] + list(db.ORDER_STATUSES))
    orders = db.get_orders(status=None if status == "All" else status, search=search)
    if orders.empty:
        st.info("No orders found.")
        return

    show_table(orders[["order_id", "customer", "status", "delivery_date", "total"]], ["total"])
    st.download_button("Download as CSV", orders.to_csv(index=False).encode("utf-8"),
                       file_name="orders.csv", mime="text/csv")

    # ---- order details ----
    st.subheader("Order details")
    order_id = st.selectbox("Select the order", orders["order_id"].tolist(),
                            format_func=lambda i: f"Order #{i}")
    order = db.get_order(order_id)
    items = db.get_order_items(order_id)
    row = orders[orders["order_id"] == order_id].iloc[0]

    left, right = st.columns(2)
    left.write(f"**Customer:** {row['customer']}")
    left.write(f"**Phone:** {row['phone']}")
    left.write(f"**Address:** {order['address'] or '-'}")
    right.write(f"**Status:** {row['status']}")
    right.write(f"**Order date:** {row['order_date']}")
    right.write(f"**Delivery date:** {row['delivery_date'] or '-'}")

    show_table(items[["product_id", "product", "unit_price", "quantity", "amount"]],
               ["unit_price", "amount"])
    st.metric("Total", money(row["total"]))

    if order["status"] != "Active":
        return   # only Active orders can be edited

    # ---- edit order ----
    st.subheader("Edit order")
    customers = db.get_customers()
    customer_options = {customer_label(r): int(r["customer_id"]) for _, r in customers.iterrows()}
    names = list(customer_options)
    current = next(k for k, v in customer_options.items() if v == order["customer_id"])
    c1, c2 = st.columns(2)
    new_customer = c1.selectbox("Customer", names, index=names.index(current),
                                key=f"edit_customer_{order_id}")
    new_delivery = c2.date_input("Delivery date",
                                 value=parse_date(order["delivery_date"], db.now_local().date()),
                                 key=f"edit_date_{order_id}")
    new_address = st.text_input("Address", value=order["address"] or "",
                                key=f"edit_address_{order_id}")

    all_products = db.get_products()
    in_order = set(items["product_id"])
    usable = all_products[(all_products["available"] == 1) |
                          (all_products["product_id"].isin(in_order))]
    labels = [product_label(r) for _, r in usable.iterrows()]
    label_of = {r["product_id"]: product_label(r) for _, r in all_products.iterrows()}
    current_items = pd.DataFrame({
        "Product": [label_of[p] for p in items["product_id"]],
        "Quantity": items["quantity"].astype("int64"),
    })
    new_items = item_editor(f"edit_items_{order_id}", labels, current_items)

    b1, b2, b3 = st.columns(3)
    if b1.button("Save changes", type="primary"):
        try:
            db.update_order(order_id, customer_options[new_customer], new_items,
                            new_delivery.isoformat(), new_address)
            flash(f"Order #{order_id} updated.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if b2.button("Mark completed"):
        db.set_order_status(order_id, "Completed")
        flash(f"Order #{order_id} marked as completed.")
        st.rerun()
    if b3.button("Cancel order"):
        db.cancel_order(order_id)
        flash(f"Order #{order_id} cancelled.")
        st.rerun()


def page_customers():
    st.title("Customers")
    show_flash()
    tab_all, tab_add, tab_edit = st.tabs(["All / Search", "Add customer", "Edit / Delete"])

    with tab_all:
        search = st.text_input("Search by name or phone")
        customers = db.get_customers(search)
        show_table(customers, empty_message="No customers found.")
        if not customers.empty:
            st.subheader("Previous orders")
            options = {customer_label(r): r["customer_id"] for _, r in customers.iterrows()}
            chosen = st.selectbox("Select the customer", list(options), key="history_customer")
            history = db.get_orders(customer_id=int(options[chosen]))
            if not history.empty:
                history = history[["order_id", "order_date", "delivery_date", "status", "total"]]
            show_table(history, ["total"], "No previous orders for this customer.")

    with tab_add:
        with st.form("add_customer", clear_on_submit=True):
            name = st.text_input("Name")
            phone = st.text_input("Phone")
            address = st.text_input("Address (optional)")
            submitted = st.form_submit_button("Add customer")
        if submitted:
            try:
                db.add_customer(name, phone, address)
                flash("Customer added successfully.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    with tab_edit:
        customers = db.get_customers()
        if customers.empty:
            st.info("No customers yet.")
        else:
            options = {customer_label(r): r for _, r in customers.iterrows()}
            c = options[st.selectbox("Select the customer", list(options), key="edit_customer")]
            customer_id = int(c["customer_id"])
            with st.form(f"edit_customer_form_{customer_id}"):
                name = st.text_input("Name", c["name"])
                phone = st.text_input("Phone", c["phone"])
                address = st.text_input("Address", c["address"] or "")
                save = st.form_submit_button("Save changes")
            if save:
                try:
                    db.update_customer(customer_id, name, phone, address)
                    flash("Customer updated.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
            if st.button("Delete customer"):
                try:
                    db.delete_customer(customer_id)
                    flash("Customer deleted.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def page_products():
    st.title("Products")
    show_flash()
    tab_all, tab_add, tab_edit = st.tabs(["All products", "Add products", "Edit"])

    with tab_all:
        show_table(db.get_products(), ["price"], "No products yet.")

    with tab_add:
        with st.form("add_product", clear_on_submit=True):
            name = st.text_input("Product name")
            price = st.number_input("Price (Rs.)", min_value=0.0, step=1.0, format="%.2f")
            submitted = st.form_submit_button("Add product")
        if submitted:
            try:
                db.add_product(name, price)
                flash("Product added successfully.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    with tab_edit:
        products = db.get_products()
        if products.empty:
            st.info("No products yet.")
        else:
            options = {product_label(r): r for _, r in products.iterrows()}
            p = options[st.selectbox("Select the product", list(options), key="edit_product")]
            product_id = int(p["product_id"])
            with st.form(f"edit_product_form_{product_id}"):
                new_price = st.number_input("New price (Rs.)", min_value=0.0, step=1.0,
                                            value=float(p["price"]), format="%.2f")
                availability = st.selectbox("Availability", ["Available", "Unavailable"],
                                            index=0 if p["available"] else 1)
                update = st.form_submit_button("Update")
            if update:
                try:
                    db.update_product_price(product_id, new_price)
                    db.set_product_availability(product_id, availability == "Available")
                    flash("Product updated. Existing orders keep their old price.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


# ------------------------------ menu ---------------------------------

st.sidebar.image(LOGO_PATH, width=110)
st.sidebar.title("Orderly")
page = st.sidebar.radio("Menu", ["Dashboard", "New order", "Orders", "Customers", "Products"])

if page == "Dashboard":
    page_dashboard()
elif page == "New order":
    page_new_order()
elif page == "Orders":
    page_orders()
elif page == "Customers":
    page_customers()
elif page == "Products":
    page_products()
