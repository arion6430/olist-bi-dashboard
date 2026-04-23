"""
Superset setup: datasets + charts + dashboards for olist_ecommerce.
Run: PYTHONUTF8=1 python setup_superset.py
"""
import json, uuid, requests

BASE_URL = "http://localhost:8088"
SCHEMA    = "olist"

s = requests.Session()

# ── Auth ──────────────────────────────────────────────────────────────────

def login():
    r = s.post(f"{BASE_URL}/api/v1/security/login",
               json={"username": "admin", "password": "admin123", "provider": "db"})
    r.raise_for_status()
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    csrf = s.get(f"{BASE_URL}/api/v1/security/csrf_token/").json()["result"]
    s.headers.update({"X-CSRFToken": csrf, "Referer": BASE_URL})
    print("OK login")

def db_id():
    for db in s.get(f"{BASE_URL}/api/v1/database/").json()["result"]:
        if db["backend"] == "postgresql":
            print(f"OK db id={db['id']} name={db['database_name']}")
            return db["id"]
    raise RuntimeError("postgresql db not found")

# ── Cleanup ───────────────────────────────────────────────────────────────

def delete_all(resource):
    r = s.get(f"{BASE_URL}/api/v1/{resource}/",
              params={"q": json.dumps({"page_size": 100})})
    for item in r.json().get("result", []):
        s.delete(f"{BASE_URL}/api/v1/{resource}/{item['id']}")
    print(f"  cleared {resource}")

# ── Datasets ──────────────────────────────────────────────────────────────

def mk_dataset(did, table, schema=SCHEMA, sql=None):
    body = {"database": did, "table_name": table, "schema": schema}
    if sql:
        body["sql"] = sql
    r = s.post(f"{BASE_URL}/api/v1/dataset/", json=body)
    if not r.ok:
        print(f"  FAIL dataset {table}: {r.text[:120]}")
        return None
    return r.json()["id"]

# ── Metric helper ─────────────────────────────────────────────────────────

def m(sql_expr, label=None):
    return {
        "expressionType": "SQL",
        "sqlExpression": sql_expr,
        "label": label or sql_expr,
        "optionName": f"metric_{uuid.uuid4().hex[:8]}",
    }

# ── Chart ─────────────────────────────────────────────────────────────────

BASE_PARAMS = {
    "time_range": "No filter",
    "adhoc_filters": [],
}

def mk_chart(name, viz, ds_id, extra_params):
    params = {**BASE_PARAMS, "viz_type": viz, **extra_params}
    r = s.post(f"{BASE_URL}/api/v1/chart/", json={
        "slice_name": name,
        "viz_type": viz,
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(params),
        "owners": [1],
    })
    if not r.ok:
        print(f"  FAIL chart '{name}': {r.text[:150]}")
        return None
    cid = r.json()["id"]
    print(f"  chart {cid}: {name}")
    return cid

# ── Dashboard ─────────────────────────────────────────────────────────────

def mk_dashboard(title, chart_ids):
    chart_ids = [c for c in chart_ids if c]

    # Build position_json — 2 charts per row, each 6/12 cols wide
    W, H = 6, 50
    positions = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID":  {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID":  {"type": "GRID", "id": "GRID_ID", "children": [],
                     "parents": ["ROOT_ID"]},
    }
    for i, cid in enumerate(chart_ids):
        row_id   = f"ROW-{i // 2}"
        col_idx  = i % 2
        chart_key = f"CHART-{cid}-{i}"          # unique per dashboard
        if row_id not in positions:
            positions[row_id] = {
                "type": "ROW", "id": row_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            positions["GRID_ID"]["children"].append(row_id)
        positions[row_id]["children"].append(chart_key)
        positions[chart_key] = {
            "type": "CHART", "id": chart_key, "children": [],
            "parents": ["ROOT_ID", "GRID_ID", row_id],
            "meta": {"chartId": cid, "width": W, "height": H, "sliceName": ""},
        }

    r = s.post(f"{BASE_URL}/api/v1/dashboard/", json={
        "dashboard_title": title,
        "published": True,
        "position_json": json.dumps(positions),
        "owners": [1],
    })
    if not r.ok:
        print(f"  FAIL dashboard '{title}': {r.text[:150]}")
        return None
    did = r.json()["id"]
    print(f"  dashboard {did}: '{title}'  ({len(chart_ids)} charts)")
    return did

# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("\n=== Setup olist_ecommerce in Superset ===\n")
    login()
    DB = db_id()

    print("\n[1] Cleanup old objects...")
    delete_all("dashboard")
    delete_all("chart")
    delete_all("dataset")

    print("\n[2] Physical datasets...")
    ds = {}
    for tbl in ["orders", "order_items", "customers", "products", "sellers",
                "order_payments", "order_reviews", "geolocation",
                "product_category_translation"]:
        ds[tbl] = mk_dataset(DB, tbl)
        print(f"  dataset {ds[tbl]}: {tbl}")

    print("\n[3] Virtual datasets...")

    orders_sql = f"""
SELECT
    o.order_id,
    o.customer_id,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    DATE_TRUNC('month', o.order_purchase_timestamp) AS order_month,
    c.customer_city,
    c.customer_state,
    COALESCE(p.payment_value, 0)         AS payment_value,
    COALESCE(p.payment_type, 'unknown')  AS payment_type,
    COALESCE(p.payment_installments, 1)  AS payment_installments
FROM {SCHEMA}.orders o
LEFT JOIN {SCHEMA}.customers c
       ON o.customer_id = c.customer_id
LEFT JOIN (
    SELECT order_id,
           SUM(payment_value)          AS payment_value,
           MAX(payment_type)           AS payment_type,
           MAX(payment_installments)   AS payment_installments
    FROM {SCHEMA}.order_payments
    GROUP BY order_id
) p ON o.order_id = p.order_id
""".strip()

    delivery_sql = f"""
SELECT
    o.order_id,
    o.order_status,
    o.order_purchase_timestamp,
    DATE_TRUNC('month', o.order_purchase_timestamp) AS order_month,
    c.customer_state,
    c.customer_city,
    EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp))
        / 86400.0 AS actual_delivery_days,
    EXTRACT(EPOCH FROM (o.order_estimated_delivery_date - o.order_purchase_timestamp))
        / 86400.0 AS estimated_delivery_days,
    CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date
         THEN 1 ELSE 0 END AS delivered_on_time,
    CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date
         THEN 1 ELSE 0 END AS is_late,
    EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_estimated_delivery_date))
        / 86400.0 AS delay_days,
    r.review_score
FROM {SCHEMA}.orders o
LEFT JOIN {SCHEMA}.customers c  ON o.customer_id = c.customer_id
LEFT JOIN {SCHEMA}.order_reviews r ON o.order_id = r.order_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
""".strip()

    products_sql = f"""
SELECT
    i.order_id,
    i.product_id,
    i.seller_id,
    i.price,
    i.freight_value,
    i.price + i.freight_value                                          AS total_item_value,
    COALESCE(t.category_name_english, p.product_category_name, 'unknown') AS category_english,
    p.product_category_name                                            AS category_portuguese,
    p.product_weight_g,
    r.review_score,
    o.order_purchase_timestamp,
    DATE_TRUNC('month', o.order_purchase_timestamp)                    AS order_month,
    c.customer_state
FROM {SCHEMA}.order_items i
LEFT JOIN {SCHEMA}.products p
       ON i.product_id = p.product_id
LEFT JOIN {SCHEMA}.product_category_translation t
       ON p.product_category_name = t.category_name_portuguese
LEFT JOIN {SCHEMA}.orders o ON i.order_id = o.order_id
LEFT JOIN {SCHEMA}.customers c ON o.customer_id = c.customer_id
LEFT JOIN {SCHEMA}.order_reviews r ON i.order_id = r.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
""".strip()

    ds["orders_enriched"]  = mk_dataset(DB, "orders_enriched",  sql=orders_sql)
    ds["delivery_metrics"] = mk_dataset(DB, "delivery_metrics", sql=delivery_sql)
    ds["products_enriched"]= mk_dataset(DB, "products_enriched",sql=products_sql)
    for k in ["orders_enriched","delivery_metrics","products_enriched"]:
        print(f"  virtual dataset {ds[k]}: {k}")

    print("\n[4] Charts...")
    C = {}   # name → chart_id

    # ── Dashboard 1: Sales & Revenue ──────────────────────────────────────
    oe = ds["orders_enriched"]
    print("  [Sales & Revenue]")

    C["revenue_total"] = mk_chart("Total Revenue (R$)", "big_number_total", oe, {
        "metric": m("SUM(payment_value)", "Revenue"),
        "y_axis_format": ",.0f",
        "subheader": "R$ total",
    })
    C["orders_total"] = mk_chart("Total Orders", "big_number_total", oe, {
        "metric": m("COUNT(DISTINCT order_id)", "Orders"),
        "subheader": "orders placed",
    })
    C["aov"] = mk_chart("Avg Order Value (R$)", "big_number_total", oe, {
        "metric": m("AVG(payment_value)", "AOV"),
        "y_axis_format": ",.2f",
        "subheader": "R$ average",
    })
    C["revenue_monthly"] = mk_chart("Monthly Revenue", "echarts_timeseries_line", oe, {
        "granularity_sqla": "order_purchase_timestamp",
        "time_grain_sqla":  "P1M",
        "time_range": "2016-01-01 : 2019-01-01",
        "metrics": [m("SUM(payment_value)", "Revenue (R$)")],
        "x_axis": "order_purchase_timestamp",
        "color_scheme": "supersetColors",
        "rich_tooltip": True,
    })
    C["orders_monthly"] = mk_chart("Monthly Orders", "echarts_timeseries_bar", oe, {
        "granularity_sqla": "order_purchase_timestamp",
        "time_grain_sqla":  "P1M",
        "time_range": "2016-01-01 : 2019-01-01",
        "metrics": [m("COUNT(DISTINCT order_id)", "Orders")],
        "x_axis": "order_purchase_timestamp",
        "color_scheme": "supersetColors",
    })
    C["revenue_by_state"] = mk_chart("Revenue by State", "dist_bar", oe, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("SUM(payment_value)", "Revenue (R$)")],
        "groupby": ["customer_state"],
        "row_limit": 30,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })
    C["orders_by_status"] = mk_chart("Orders by Status", "pie", oe, {
        "metric": m("COUNT(DISTINCT order_id)", "Orders"),
        "groupby": ["order_status"],
        "donut": True,
        "show_labels": True,
        "show_legend": True,
        "color_scheme": "supersetColors",
    })
    C["payment_types"] = mk_chart("Payment Types", "pie", oe, {
        "metric": m("COUNT(DISTINCT order_id)", "Orders"),
        "groupby": ["payment_type"],
        "donut": False,
        "show_labels": True,
        "show_legend": True,
        "color_scheme": "supersetColors",
    })

    # ── Dashboard 2: Customers ────────────────────────────────────────────
    print("  [Customers]")

    C["customers_total"] = mk_chart("Total Customers", "big_number_total", oe, {
        "metric": m("COUNT(DISTINCT customer_id)", "Customers"),
        "subheader": "unique customers",
    })
    C["customers_by_state"] = mk_chart("Customers by State", "dist_bar", oe, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("COUNT(DISTINCT customer_id)", "Customers")],
        "groupby": ["customer_state"],
        "row_limit": 30,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })
    C["customers_monthly"] = mk_chart("New Customers per Month", "echarts_timeseries_bar", oe, {
        "granularity_sqla": "order_purchase_timestamp",
        "time_grain_sqla":  "P1M",
        "time_range": "2016-01-01 : 2019-01-01",
        "metrics": [m("COUNT(DISTINCT customer_id)", "Customers")],
        "x_axis": "order_purchase_timestamp",
        "color_scheme": "supersetColors",
    })
    C["installments"] = mk_chart("Payment Installments Distribution", "dist_bar", oe, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("COUNT(DISTINCT order_id)", "Orders")],
        "groupby": ["payment_installments"],
        "row_limit": 24,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })

    # ── Dashboard 3: Products & Categories ───────────────────────────────
    pe = ds["products_enriched"]
    print("  [Products & Categories]")

    C["revenue_by_cat"] = mk_chart("Revenue by Category", "dist_bar", pe, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("SUM(price)", "Revenue (R$)")],
        "groupby": ["category_english"],
        "row_limit": 20,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })
    C["items_by_cat"] = mk_chart("Items Sold by Category (Top 15)", "pie", pe, {
        "metric": m("COUNT(*)", "Items"),
        "groupby": ["category_english"],
        "row_limit": 15,
        "donut": True,
        "show_labels": True,
        "color_scheme": "supersetColors",
    })
    C["review_by_cat"] = mk_chart("Avg Review Score by Category", "dist_bar", pe, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("AVG(review_score)", "Avg Score")],
        "groupby": ["category_english"],
        "row_limit": 20,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })
    C["price_by_cat"] = mk_chart("Avg Item Price by Category (R$)", "dist_bar", pe, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("AVG(price)", "Avg Price (R$)")],
        "groupby": ["category_english"],
        "row_limit": 20,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })

    # ── Dashboard 4: Logistics & Delivery ────────────────────────────────
    dm = ds["delivery_metrics"]
    print("  [Logistics & Delivery]")

    C["avg_days"] = mk_chart("Avg Delivery Time (Days)", "big_number_total", dm, {
        "metric": m("AVG(actual_delivery_days)", "Avg Days"),
        "y_axis_format": ".1f",
        "subheader": "average calendar days",
    })
    C["on_time_pct"] = mk_chart("On-Time Delivery Rate %", "big_number_total", dm, {
        "metric": m("100.0 * SUM(delivered_on_time) / COUNT(*)", "On-Time %"),
        "y_axis_format": ".1f",
        "subheader": "% orders delivered on time",
    })
    C["days_by_state"] = mk_chart("Avg Delivery Days by State", "dist_bar", dm, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("AVG(actual_delivery_days)", "Avg Days")],
        "groupby": ["customer_state"],
        "row_limit": 30,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })
    C["late_monthly"] = mk_chart("Late Orders per Month", "echarts_timeseries_line", dm, {
        "granularity_sqla": "order_purchase_timestamp",
        "time_grain_sqla":  "P1M",
        "time_range": "2016-01-01 : 2019-01-01",
        "metrics": [m("SUM(is_late)", "Late Orders")],
        "x_axis": "order_purchase_timestamp",
        "color_scheme": "supersetColors",
    })
    C["review_dist"] = mk_chart("Review Score Distribution", "pie", dm, {
        "metric": m("COUNT(*)", "Reviews"),
        "groupby": ["review_score"],
        "donut": False,
        "show_labels": True,
        "show_legend": True,
        "color_scheme": "supersetColors",
    })
    C["delay_by_state"] = mk_chart("Avg Delay (Days) by State", "dist_bar", dm, {
        "granularity_sqla": "order_purchase_timestamp",
        "metrics": [m("AVG(CASE WHEN is_late=1 THEN delay_days ELSE 0 END)", "Avg Delay")],
        "groupby": ["customer_state"],
        "row_limit": 30,
        "bar_stacked": False,
        "color_scheme": "supersetColors",
    })

    print("\n[5] Dashboards...")

    def ids(*names):
        return [C[n] for n in names if C.get(n)]

    mk_dashboard("Sales & Revenue", ids(
        "revenue_total", "orders_total", "aov",
        "revenue_monthly", "orders_monthly",
        "revenue_by_state", "orders_by_status", "payment_types",
    ))
    mk_dashboard("Customers", ids(
        "customers_total",
        "customers_by_state", "customers_monthly", "installments",
    ))
    mk_dashboard("Products & Categories", ids(
        "revenue_by_cat", "items_by_cat",
        "review_by_cat", "price_by_cat",
    ))
    mk_dashboard("Logistics & Delivery", ids(
        "avg_days", "on_time_pct",
        "days_by_state", "late_monthly",
        "review_dist", "delay_by_state",
    ))

    print("\n=== Done! http://localhost:8088/dashboard/list ===\n")

if __name__ == "__main__":
    main()
