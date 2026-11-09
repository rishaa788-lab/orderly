"""
Orderly - Order, Customer & Product Management (Streamlit app)
Run locally:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="Orderly", page_icon="🛒", layout="wide")
db.setup_tables()


# ------------------------------ helpers ------------------------------

def flash(kind, msg):
    """Remember a message across the st.rerun() that follows an action."""
    st.session_state["flash"] = (kind, msg)


def show_flash():
    if "flash" in st.session_state:
        kind, msg = st.session_state.pop("flash")
        getattr(st, kind)(msg)


def money(x):
    return f"Rs. {x:,.2f}"


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
        use_container_width=True,
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
    st.title("🛒 Orderly")
    s = db.get_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customers", s["customers"])
    c2.metric("Products", s["products"])
    c3.metric("Active orders", s["active_orders"])
    c4.metric("Revenue (excl. cancelled)", money(s["revenue"]))

    st.subheader("Recent orders")
    orders = db.get_orders().head(10)
    if orders.empty:
        st.info("No orders yet. Add customers and products, then place an order.")
    else:
        orders["total"] = orders["total"].map(money)
        st.dataframe(orders, use_container_width=True, hide_index=True)


def page_customers():
    st.title("👤 Customers")
    show_flash()
    tab_list, tab_add, tab_manage = st.tabs(["All / Search", "Add customer", "Edit / Delete"])

    with tab_list:
        search = st.text_input("Search by name or phone")
        customers = db.get_customers(search)
        if customers.empty:
            st.info("No customers found.")
        else:
            st.dataframe(customers, use_container_width=True, hide_index=True)
            st.subheader("Previous orders")
            options = {customer_label(r): r["customer_id"] for _, r in customers.iterrows()}
            pick = st.selectbox("Select a customer", list(options), key="hist_cust")
            hist = db.get_orders(customer_id=options[pick])
            if hist.empty:
                st.info("No previous orders for this customer.")
            else:
                hist["total"] = hist["total"].map(money)
                st.dataframe(hist.drop(columns=["customer", "phone"]),
                             use_container_width=True, hide_index=True)

    with tab_add:
        with st.form("add_customer", clear_on_submit=True):
            name = st.text_input("Name")
            phone = st.text_input("Phone")
            address = st.text_input("Address (optional)")
            if st.form_submit_button("Add customer"):
                try:
                    db.add_customer(name, phone, address)
                    flash("success", "Customer added successfully.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    with tab_manage:
        customers = db.get_customers()
        if customers.empty:
            st.info("No customers yet.")
            return
        options = {customer_label(r): r for _, r in customers.iterrows()}
        pick = st.selectbox("Select a customer", list(options), key="manage_cust")
        c = options[pick]
        with st.form(f"edit_customer_{c['customer_id']}"):
            name = st.text_input("Name", c["name"])
            phone = st.text_input("Phone", c["phone"])
            address = st.text_input("Address", c["address"] or "")
            save = st.form_submit_button("Save changes")
        if save:
            try:
                db.update_customer(int(c["customer_id"]), name, phone, address)
                flash("success", "Customer updated.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if st.button("🗑️ Delete this customer"):
            try:
                db.delete_customer(int(c["customer_id"]))
                flash("success", "Customer deleted.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def page_products():
    st.title("📦 Products")
    show_flash()
    tab_list, tab_add, tab_manage = st.tabs(["All products", "Add product", "Edit price / availability"])

    with tab_list:
        products = db.get_products()
        if products.empty:
            st.info("No products yet.")
        else:
            products["status"] = products["available"].map({1: "Available", 0: "Unavailable"})
            products["price"] = products["price"].map(money)
            st.dataframe(products.drop(columns=["available"]),
                         use_container_width=True, hide_index=True)

    with tab_add:
        with st.form("add_product", clear_on_submit=True):
            name = st.text_input("Product name")
            price = st.number_input("Price (Rs.)", min_value=0.0, step=1.0, format="%.2f")
            if st.form_submit_button("Add product"):
                try:
                    db.add_product(name, price)
                    flash("success", "Product added successfully.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    with tab_manage:
        products = db.get_products()
        if products.empty:
            st.info("No products yet.")
            return
        options = {product_label(r): r for _, r in products.iterrows()}
        pick = st.selectbox("Select a product", list(options), key="manage_prod")
        p = options[pick]
        pid = int(p["product_id"])

        col1, col2 = st.columns(2)
        with col1:
            with st.form(f"price_{pid}"):
                new_price = st.number_input("New price (Rs.)", min_value=0.0, step=1.0,
                                            value=float(p["price"]), format="%.2f")
                if st.form_submit_button("Update price"):
                    try:
                        db.update_product_price(pid, new_price)
                        flash("success", "Price updated. Existing orders keep their old price.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        with col2:
            with st.form(f"avail_{pid}"):
                avail = st.checkbox("Available for new orders", value=bool(p["available"]))
                if st.form_submit_button("Update availability"):
                    db.set_product_availability(pid, avail)
                    flash("success", "Availability updated.")
                    st.rerun()


def page_new_order():
    st.title("➕ New order")
    show_flash()

    products = db.get_products(only_available=True)
    customers = db.get_customers()
    if products.empty:
        st.warning("Add at least one available product first (Products page).")
        return

    mode = st.radio("Customer", ["Existing customer", "New customer"], horizontal=True)
    customer_id, new_name, new_phone, new_addr = None, "", "", ""
    if mode == "Existing customer":
        if customers.empty:
            st.info("No customers yet - choose 'New customer'.")
        else:
            opts = {customer_label(r): r["customer_id"] for _, r in customers.iterrows()}
            customer_id = opts[st.selectbox("Select customer", list(opts))]
    else:
        c1, c2, c3 = st.columns(3)
        new_name = c1.text_input("Name")
        new_phone = c2.text_input("Phone")
        new_addr = c3.text_input("Address (optional)")

    st.markdown("**Items** - click the empty row at the bottom to add a product.")
    labels = [product_label(r) for _, r in products.iterrows()]
    items = item_editor("new_order_items", labels)

    price_of = dict(zip(products["product_id"], products["price"]))
    total = sum(price_of[pid] * qty for pid, qty in items)
    st.metric("Order total", money(total))

    if st.button("Place order", type="primary"):
        try:
            if mode == "New customer":
                customer_id = db.add_customer(new_name, new_phone, new_addr)
            if customer_id is None:
                raise ValueError("Please select a customer.")
            order_id = db.create_order(customer_id, items)
            # reset the items table on next run
            st.session_state.pop("new_order_items", None)
            flash("success", f"Order #{order_id} placed successfully.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def page_orders():
    st.title("📋 Orders")
    show_flash()

    status = st.selectbox("Filter by status", ["All"] + list(db.ORDER_STATUSES))
    orders = db.get_orders(status=None if status == "All" else status)
    if orders.empty:
        st.info("No orders found.")
        return

    shown = orders.copy()
    shown["total"] = shown["total"].map(money)
    st.dataframe(shown, use_container_width=True, hide_index=True)

    st.subheader("Order details")
    ids = orders["order_id"].tolist()
    oid = st.selectbox("Select order", ids, format_func=lambda i: f"Order #{i}")
    order = db.get_order(oid)
    items = db.get_order_items(oid)
    row = orders[orders["order_id"] == oid].iloc[0]

    st.write(f"**Customer:** {row['customer']} ({row['phone']})  |  "
             f"**Status:** {row['status']}  |  **Date:** {row['order_date']}")
    view = items.drop(columns=["product_id"]).copy()
    view["unit_price"] = view["unit_price"].map(money)
    view["amount"] = view["amount"].map(money)
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.write(f"**Total: {money(row['total'])}**")

    if order["status"] != "Active":
        return

    st.divider()
    st.subheader("Edit this order")
    customers = db.get_customers()
    c_opts = {customer_label(r): r["customer_id"] for _, r in customers.iterrows()}
    current = next(k for k, v in c_opts.items() if v == order["customer_id"])
    new_cust = st.selectbox("Customer", list(c_opts), index=list(c_opts).index(current),
                            key=f"edit_cust_{oid}")

    all_products = db.get_products()
    in_order = set(items["product_id"])
    usable = all_products[(all_products["available"] == 1) |
                          (all_products["product_id"].isin(in_order))]
    labels = [product_label(r) for _, r in usable.iterrows()]
    label_by_id = {r["product_id"]: product_label(r) for _, r in all_products.iterrows()}
    initial = pd.DataFrame({
        "Product": [label_by_id[p] for p in items["product_id"]],
        "Quantity": items["quantity"].astype("int64"),
    })
    new_items = item_editor(f"edit_items_{oid}", labels, initial)

    b1, b2, b3 = st.columns(3)
    if b1.button("💾 Save changes"):
        try:
            db.update_order(oid, c_opts[new_cust], new_items)
            flash("success", f"Order #{oid} updated.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if b2.button("✅ Mark completed"):
        db.set_order_status(oid, "Completed")
        flash("success", f"Order #{oid} marked as completed.")
        st.rerun()
    if b3.button("❌ Cancel order"):
        db.cancel_order(oid)
        flash("success", f"Order #{oid} cancelled.")
        st.rerun()


# ------------------------------ router -------------------------------

PAGES = {
    "🏠 Dashboard": page_dashboard,
    "➕ New order": page_new_order,
    "📋 Orders": page_orders,
    "👤 Customers": page_customers,
    "📦 Products": page_products,
}

st.sidebar.title("Orderly")
choice = st.sidebar.radio("Go to", list(PAGES), label_visibility="collapsed")
PAGES[choice]()
