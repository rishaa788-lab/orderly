"""
Orderly - Order, Customer & Product Management (Streamlit app)
Run:  streamlit run app.py

Files:
    app.py                  -> the pages (this file)
    db.py                   -> all the database code
    assets/logo.png         -> the logo
    .streamlit/config.toml  -> the colours (from the Figma design)
"""

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo.png")

st.set_page_config(
    page_title="Orderly",
    page_icon=LOGO_PATH if os.path.exists(LOGO_PATH) else "🛒",
    layout="wide",
)
db.setup_tables()


# ------------------------------ helpers ------------------------------

def flash(kind, message):
    """Save a message so it can be shown after the page reloads."""
    st.session_state["flash"] = (kind, message)


def show_flash():
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        if kind == "success":
            st.success(message)
        else:
            st.error(message)


def money(x):
    return f"Rs. {x:,.2f}"


def percent(x):
    return "-" if pd.isna(x) else f"{x:+.1f}%"


def parse_date(text, fallback):
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return fallback


COLUMN_NAMES = {
    "order_id": "Order ID", "product_id": "Product ID", "customer_id": "Customer ID",
    "unit_price": "Price", "order_date": "Order date", "delivery_date": "Delivery date",
    "created_at": "Placed at", "final_amount": "Final amount", "days_left": "Days left",
    "avg_order_value": "Avg order value", "growth_percent": "Growth %",
    "qty_sold": "Sold (qty)", "stock_status": "Stock status", "available": "Availability",
    "note": "Message / note", "paid": "Paid",
}


def pretty(column):
    return COLUMN_NAMES.get(column, column.replace("_", " ").capitalize())


def show_table(df, money_columns=(), percent_columns=(), empty_message="Nothing here yet."):
    """Show a DataFrame as a neat table (money formatted, nice column names)."""
    if df.empty:
        st.info(empty_message)
        return
    df = df.copy()
    for col in money_columns:
        df[col] = df[col].map(money)
    for col in percent_columns:
        df[col] = df[col].map(percent)
    if "available" in df.columns:
        df["available"] = df["available"].map({1: "Available", 0: "Unavailable"})
    st.dataframe(df.rename(columns=pretty), hide_index=True)


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


DISCOUNT_CHOICES = {"Percent (%)": "Percent", "Flat (Rs.)": "Flat"}


def discount_inputs(key, default_type="Percent", default_value=0.0):
    """Discount type + value boxes. Returns (discount_type, discount_value)."""
    labels = list(DISCOUNT_CHOICES)
    c1, c2 = st.columns(2)
    choice = c1.radio("Discount type", labels, horizontal=True,
                      index=0 if default_type == "Percent" else 1, key=f"{key}_dtype")
    value = c2.number_input("Discount value", min_value=0.0, step=1.0, format="%.2f",
                            value=float(default_value), key=f"{key}_dvalue")
    return DISCOUNT_CHOICES[choice], value


def amount_summary(subtotal, discount_type, discount_value):
    """Show subtotal, discount and the final amount. Returns the final amount."""
    discount = db.calc_discount(subtotal, discount_type, discount_value)
    final = subtotal - discount
    c1, c2, c3 = st.columns(3)
    c1.metric("Subtotal", money(subtotal))
    c2.metric("Discount", "- " + money(discount))
    c3.metric("Final amount", money(final))
    return final


def stock_status(stock, limit):
    if stock == 0:
        return "Out of stock"
    if stock <= limit:
        return "Low"
    return "OK"


# ------------------------------ pages --------------------------------

def page_dashboard(low_limit):
    st.title("🛒 Orderly")
    stats = db.get_stats()
    priority = db.get_priority_orders()
    low = db.get_low_stock(low_limit)
    best = db.get_best_sellers(5)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customers", stats["customers"])
    c2.metric("Products", stats["products"])
    c3.metric("Active orders", stats["active_orders"])
    c4.metric("Revenue", money(stats["revenue"]))

    urgent = int(priority["urgency"].isin(["Overdue", "Due today"]).sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Payment pending", money(stats["pending"]))
    c2.metric("Best selling item", best.iloc[0]["product"] if not best.empty else "-")
    c3.metric("Low stock items", len(low))
    c4.metric("Overdue / due today", urgent)

    if not low.empty:
        names = ", ".join(f"{r['name']} ({r['stock']} left)" for _, r in low.iterrows())
        st.warning(f"Low stock: {names}")

    left, right = st.columns(2)
    with left:
        st.subheader("Orders to do first")
        top = priority.head(5)
        if not top.empty:
            top = top[["priority", "order_id", "customer", "delivery_date", "urgency"]]
        show_table(top, empty_message="No active orders.")
    with right:
        st.subheader("Best selling items")
        show_table(best, money_columns=["sales"], empty_message="No sales yet.")

    st.subheader("Recent orders")
    recent = db.get_orders().head(8)
    if not recent.empty:
        recent = recent[["order_id", "customer", "order_date", "delivery_date",
                         "status", "final_amount", "payment"]]
    show_table(recent, money_columns=["final_amount"],
               empty_message="No orders yet. Add a customer and a product, then place an order.")


def page_new_order():
    st.title("➕ New order")
    show_flash()
    # v changes after every successful order, which gives us fresh empty boxes
    v = st.session_state.get("new_order_version", 0)

    products = db.get_products(only_available=True)
    customers = db.get_customers()
    if products.empty:
        st.info("Add at least one available product first (Products page).")
        return

    # ---- customer ----
    st.subheader("Customer")
    mode = st.radio("Customer type", ["Existing customer", "New customer"],
                    horizontal=True, key=f"mode_{v}")
    customer_id, new_name, new_phone = None, "", ""
    if mode == "Existing customer":
        if customers.empty:
            st.info("No customers yet. Choose “New customer”.")
        else:
            options = {customer_label(r): int(r["customer_id"]) for _, r in customers.iterrows()}
            customer_id = options[st.selectbox("Select the customer", list(options), key=f"cust_{v}")]
    else:
        c1, c2 = st.columns(2)
        new_name = c1.text_input("Customer name", key=f"new_name_{v}")
        new_phone = c2.text_input("Mobile number (10 digits)", max_chars=10, key=f"new_phone_{v}")

    # ---- products ----
    st.subheader("Products")
    with st.expander("See available products and stock"):
        show_table(products[["product_id", "name", "price", "stock"]], money_columns=["price"])
    st.caption("Click the empty row at the bottom of the table to add a product.")
    labels = [product_label(r) for _, r in products.iterrows()]
    items = item_editor(f"new_items_{v}", labels)
    price_of = dict(zip(products["product_id"], products["price"]))
    subtotal = sum(price_of[pid] * qty for pid, qty in items)

    # ---- discount and amount ----
    st.subheader("Discount and amount")
    dtype, dvalue = discount_inputs(f"new_{v}")
    final = amount_summary(subtotal, dtype, dvalue)

    # ---- dates, message, advance ----
    st.subheader("Order details")
    today = db.now_local().date()
    c1, c2 = st.columns(2)
    order_date = c1.date_input("Order date", value=today, key=f"od_{v}")
    delivery_date = c2.date_input("Delivery date", value=today + timedelta(days=1), key=f"dd_{v}")
    note = st.text_area("Message / special instructions (e.g. name on the cake)",
                        max_chars=300, key=f"note_{v}")
    advance = st.number_input("Advance payment received (Rs.)", min_value=0.0, step=50.0,
                              format="%.2f", key=f"adv_{v}")

    if st.button("Place order", type="primary"):
        created_customer_id = None
        try:
            if not items:
                raise ValueError("Add at least one product to the order.")
            if mode == "New customer":
                customer_id = created_customer_id = db.add_customer(new_name, new_phone)
            if customer_id is None:
                raise ValueError("Please select a customer.")
            order_id = db.create_order(customer_id, items, order_date.isoformat(),
                                       delivery_date.isoformat(), note, dtype, dvalue, advance)
            st.session_state["new_order_version"] = v + 1   # empties the form
            flash("success", f"Order #{order_id} placed successfully. Final amount: {money(final)}")
            st.rerun()
        except ValueError as e:
            if created_customer_id is not None:      # order failed, so undo the new customer
                db.delete_customer(created_customer_id)
            st.error(str(e))


def order_edit_section(order, items, order_id):
    """Everything needed to correct an Active order."""
    st.subheader("Edit order")
    v = st.session_state.get("edit_version", 0)
    today = db.now_local().date()

    customers = db.get_customers()
    customer_options = {customer_label(r): int(r["customer_id"]) for _, r in customers.iterrows()}
    names = list(customer_options)
    current = next(k for k, val in customer_options.items() if val == order["customer_id"])

    c1, c2, c3 = st.columns(3)
    new_customer = c1.selectbox("Customer", names, index=names.index(current),
                                key=f"edit_customer_{order_id}_{v}")
    new_order_date = c2.date_input("Order date", value=parse_date(order["order_date"], today),
                                   key=f"edit_od_{order_id}_{v}")
    new_delivery = c3.date_input("Delivery date", value=parse_date(order["delivery_date"], today),
                                 key=f"edit_dd_{order_id}_{v}")
    new_note = st.text_area("Message / special instructions", value=order["note"] or "",
                            max_chars=300, key=f"edit_note_{order_id}_{v}")
    dtype, dvalue = discount_inputs(f"edit_{order_id}_{v}", order["discount_type"],
                                    order["discount_value"])

    # the products table (products already in the order may be unavailable now)
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
    new_items = item_editor(f"edit_items_{order_id}_{v}", labels, current_items)

    # amount preview (products already in the order keep their old price)
    price_of = dict(zip(all_products["product_id"], all_products["price"]))
    price_of.update(dict(zip(items["product_id"], items["unit_price"])))
    amount_summary(sum(price_of[pid] * qty for pid, qty in new_items), dtype, dvalue)

    confirm_cancel = st.checkbox("Yes, I want to cancel this order", key=f"confirm_cancel_{order_id}")
    b1, b2, b3 = st.columns(3)
    if b1.button("Save changes", type="primary"):
        try:
            db.update_order(order_id, customer_options[new_customer], new_items,
                            new_order_date.isoformat(), new_delivery.isoformat(),
                            new_note, dtype, dvalue)
            st.session_state["edit_version"] = v + 1    # reload the boxes from the database
            flash("success", f"Order #{order_id} updated.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if b2.button("Mark completed"):
        try:
            db.set_order_status(order_id, "Completed")
            flash("success", f"Order #{order_id} marked as completed.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if b3.button("Cancel order"):
        if not confirm_cancel:
            st.error("Tick the box above to confirm the cancellation.")
        else:
            try:
                db.cancel_order(order_id)
                flash("success", f"Order #{order_id} cancelled. Its items are back in stock.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def tab_all_orders():
    c1, c2 = st.columns([2, 1])
    search = c1.text_input("Search by order ID, customer name or phone")
    status = c2.selectbox("Status", ["All"] + list(db.ORDER_STATUSES))
    orders = db.get_orders(status=None if status == "All" else status, search=search)
    if orders.empty:
        st.info("No orders found.")
        return

    show_table(orders[["order_id", "customer", "order_date", "delivery_date", "status",
                       "final_amount", "payment"]], money_columns=["final_amount"])
    export = orders.drop(columns=["discount_type", "discount_value"])
    st.download_button("Download as CSV", export.to_csv(index=False).encode("utf-8"),
                       file_name="orders.csv", mime="text/csv")

    # ---- details ----
    st.subheader("Order details")
    order_id = st.selectbox("Select the order", orders["order_id"].tolist(),
                            format_func=lambda i: f"Order #{i}")
    order = db.get_order(order_id)
    items = db.get_order_items(order_id)
    row = orders[orders["order_id"] == order_id].iloc[0]

    left, right = st.columns(2)
    left.write(f"**Customer:** {row['customer']}  ({row['phone']})")
    left.write(f"**Status:** {row['status']}")
    left.write(f"**Message / note:** {row['note'] or '-'}")
    right.write(f"**Order date:** {row['order_date']}")
    right.write(f"**Delivery date:** {row['delivery_date'] or '-'}")
    right.write(f"**Placed at:** {row['created_at'] or '-'}")

    show_table(items[["product_id", "product", "unit_price", "quantity", "amount"]],
               money_columns=["unit_price", "amount"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Subtotal", money(row["subtotal"]))
    c2.metric("Discount", "- " + money(row["discount"]))
    c3.metric("Final amount", money(row["final_amount"]))
    c4.metric("Payment pending", money(row["pending"]), delta=row["payment"], delta_color="off")

    # ---- record a payment ----
    if row["status"] != "Cancelled" and row["pending"] > 0.005:
        st.subheader("Record a payment")
        p1, p2, p3 = st.columns([2, 1, 1])
        amount = p1.number_input("Amount received (Rs.)", min_value=0.0, step=50.0, format="%.2f",
                                 key=f"pay_{order_id}_{row['paid']}")
        if p2.button("Add payment"):
            try:
                db.add_payment(order_id, amount)
                flash("success", "Payment recorded.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if p3.button("Mark fully paid"):
            try:
                db.mark_fully_paid(order_id)
                flash("success", "Order marked as fully paid.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    if row["status"] == "Active":
        order_edit_section(order, items, order_id)


def tab_priority():
    st.write("Active orders, earliest delivery date first. Make order #1 first.")
    df = db.get_priority_orders()
    if not df.empty:
        df = df[["priority", "order_id", "customer", "delivery_date", "days_left",
                 "urgency", "note", "final_amount"]]
    show_table(df, money_columns=["final_amount"], empty_message="No active orders. 🎉")


def tab_pending_payments():
    df = db.get_pending_payments()
    st.metric("Total payment pending", money(df["pending"].sum()))
    if not df.empty:
        df = df[["order_id", "customer", "phone", "delivery_date", "final_amount",
                 "paid", "pending", "payment"]]
    show_table(df, money_columns=["final_amount", "paid", "pending"],
               empty_message="No pending payments. 🎉")


def page_orders():
    st.title("📋 Orders")
    show_flash()
    tab1, tab2, tab3 = st.tabs(["All orders", "Priority (do first)", "Payment pending"])
    with tab1:
        tab_all_orders()
    with tab2:
        tab_priority()
    with tab3:
        tab_pending_payments()


def page_customers():
    st.title("👤 Customers")
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
                history = history[["order_id", "order_date", "delivery_date", "status",
                                   "final_amount", "payment"]]
            show_table(history, money_columns=["final_amount"],
                       empty_message="No previous orders for this customer.")

    with tab_add:
        with st.form("add_customer", clear_on_submit=True):
            name = st.text_input("Name")
            phone = st.text_input("Mobile number (10 digits)", max_chars=10)
            address = st.text_input("Address (optional)")
            submitted = st.form_submit_button("Add customer")
        if submitted:
            try:
                db.add_customer(name, phone, address)
                flash("success", "Customer added successfully.")
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
                phone = st.text_input("Mobile number (10 digits)", c["phone"], max_chars=10)
                address = st.text_input("Address", c["address"] or "")
                save = st.form_submit_button("Save changes")
            if save:
                try:
                    db.update_customer(customer_id, name, phone, address)
                    flash("success", "Customer updated.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
            if st.button("Delete customer"):
                try:
                    db.delete_customer(customer_id)
                    flash("success", "Customer deleted.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def page_products(low_limit):
    st.title("📦 Products")
    show_flash()
    tab_all, tab_add, tab_edit = st.tabs(["All products", "Add product", "Edit price / stock"])

    with tab_all:
        products = db.get_products()
        if not products.empty:
            products["stock_status"] = [stock_status(s, low_limit) for s in products["stock"]]
            products = products[["product_id", "name", "price", "stock", "stock_status", "available"]]
        show_table(products, money_columns=["price"], empty_message="No products yet.")

    with tab_add:
        with st.form("add_product", clear_on_submit=True):
            name = st.text_input("Product name")
            price = st.number_input("Price (Rs.)", min_value=0.0, step=1.0, format="%.2f")
            stock = st.number_input("Number of items in stock", min_value=0, step=1)
            submitted = st.form_submit_button("Add product")
        if submitted:
            try:
                db.add_product(name, price, stock)
                flash("success", "Product added successfully.")
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
                new_price = st.number_input("Price (Rs.)", min_value=0.0, step=1.0,
                                            value=float(p["price"]), format="%.2f")
                new_stock = st.number_input("Number of items in stock", min_value=0, step=1,
                                            value=int(p["stock"]))
                availability = st.selectbox("Availability", ["Available", "Unavailable"],
                                            index=0 if p["available"] else 1)
                update = st.form_submit_button("Update")
            if update:
                try:
                    db.update_product(product_id, new_price, new_stock, availability == "Available")
                    flash("success", "Product updated. Existing orders keep their old price.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def page_reports():
    st.title("📈 Business growth report")
    report = db.get_monthly_report()
    if report.empty:
        st.info("No orders yet. The report appears after your first order.")
        return

    today = db.now_local().date()
    this_month = today.strftime("%Y-%m")
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    def value(column, month):
        return float(report.loc[month, column]) if month in report.index else 0.0

    def change(column):
        now, before = value(column, this_month), value(column, last_month)
        return None if before == 0 else f"{(now - before) / before * 100:+.1f}% vs last month"

    st.subheader("This month")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue", money(value("revenue", this_month)), delta=change("revenue"))
    c2.metric("Orders", int(value("orders", this_month)), delta=change("orders"))
    c3.metric("Average order value", money(value("avg_order_value", this_month)),
              delta=change("avg_order_value"))
    c4.metric("Payment collected", money(value("collected", this_month)))

    st.subheader("Month by month")
    show_table(report.reset_index(), money_columns=["revenue", "avg_order_value", "collected"],
               percent_columns=["growth_percent"])
    st.bar_chart(report["revenue"])

    st.subheader("Daily revenue, last 30 days")
    st.bar_chart(db.get_daily_revenue(30))

    st.subheader("Best selling items")
    show_table(db.get_best_sellers(10), money_columns=["sales"], empty_message="No sales yet.")
    st.caption("Revenue is after discounts and does not include cancelled orders.")


# ------------------------------ menu ---------------------------------

if os.path.exists(LOGO_PATH):
    st.sidebar.image(LOGO_PATH, width=110)
st.sidebar.title("Orderly")
page = st.sidebar.radio("Menu", ["🏠 Dashboard", "➕ New order", "📋 Orders",
                                 "👤 Customers", "📦 Products", "📈 Reports"])
low_limit = st.sidebar.number_input("Low stock alert at or below", min_value=0, value=5, step=1)

if page == "🏠 Dashboard":
    page_dashboard(low_limit)
elif page == "➕ New order":
    page_new_order()
elif page == "📋 Orders":
    page_orders()
elif page == "👤 Customers":
    page_customers()
elif page == "📦 Products":
    page_products(low_limit)
elif page == "📈 Reports":
    page_reports()
