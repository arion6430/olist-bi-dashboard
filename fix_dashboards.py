"""
Fix dashboards: create dashboards and directly insert chart-dashboard relationships
into the Superset metadata DB (dashboard_slices table).
Run: PYTHONUTF8=1 python fix_dashboards.py
"""
import json, subprocess, requests

BASE_URL = "http://localhost:8088"

s = requests.Session()

def login():
    r = s.post(f"{BASE_URL}/api/v1/security/login",
               json={"username": "admin", "password": "admin123", "provider": "db"})
    r.raise_for_status()
    s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    csrf = s.get(f"{BASE_URL}/api/v1/security/csrf_token/").json()["result"]
    s.headers.update({"X-CSRFToken": csrf, "Referer": BASE_URL})
    print("OK login")

def get_chart_ids():
    r = s.get(f"{BASE_URL}/api/v1/chart/", params={"q": json.dumps({"page_size": 100})})
    return {c["slice_name"]: c["id"] for c in r.json().get("result", [])}

def get_dashboards():
    r = s.get(f"{BASE_URL}/api/v1/dashboard/", params={"q": json.dumps({"page_size": 20})})
    return {d["dashboard_title"]: d["id"] for d in r.json().get("result", [])}

def delete_dashboard(did):
    s.delete(f"{BASE_URL}/api/v1/dashboard/{did}")

def build_position_json(chart_ids):
    W, H = 6, 50
    positions = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID":  {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID":  {"type": "GRID", "id": "GRID_ID", "children": [],
                     "parents": ["ROOT_ID"]},
    }
    for i, cid in enumerate(chart_ids):
        row_id    = f"ROW-{i // 2}"
        chart_key = f"CHART-{cid}-{i}"
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
    return json.dumps(positions)

def create_dashboard(title, chart_ids):
    chart_ids = [c for c in chart_ids if c]
    r = s.post(f"{BASE_URL}/api/v1/dashboard/", json={
        "dashboard_title": title,
        "published": True,
        "position_json": build_position_json(chart_ids),
        "owners": [1],
    })
    if not r.ok:
        print(f"  FAIL create '{title}': {r.text[:200]}")
        return None
    did = r.json()["id"]
    print(f"  created dashboard {did}: '{title}'")
    return did, chart_ids

def psql(sql):
    """Run SQL in superset-db container."""
    res = subprocess.run(
        ["docker", "exec", "superset-db", "psql", "-U", "superset", "-d", "superset", "-c", sql],
        capture_output=True, text=True
    )
    if res.returncode != 0:
        print(f"  PSQL ERROR: {res.stderr[:200]}")
    return res.stdout.strip()

def link_charts(dashboard_id, chart_ids):
    """Insert rows into dashboard_slices to link charts to the dashboard."""
    for cid in chart_ids:
        psql(f"INSERT INTO dashboard_slices (dashboard_id, slice_id) "
             f"VALUES ({dashboard_id}, {cid}) ON CONFLICT DO NOTHING;")
    print(f"  linked {len(chart_ids)} charts to dashboard {dashboard_id}")

def main():
    print("\n=== Fix dashboards ===\n")
    login()

    C = get_chart_ids()
    print(f"Found {len(C)} charts")

    dashes = get_dashboards()
    to_delete = ["Sales & Revenue", "Customers", "Products & Categories", "Logistics & Delivery"]
    for title in to_delete:
        if title in dashes:
            delete_dashboard(dashes[title])
            print(f"  deleted: '{title}'")

    print()

    def ids(*names):
        result = []
        for n in names:
            if n in C:
                result.append(C[n])
            else:
                print(f"  WARNING: chart '{n}' not found")
        return result

    dashboards = [
        ("Sales & Revenue", ids(
            "Total Revenue (R$)", "Total Orders", "Avg Order Value (R$)",
            "Monthly Revenue", "Orders per Month",
            "Revenue by State", "Orders by Status", "Payment Types",
        )),
        ("Customers", ids(
            "Total Customers", "Customers by State", "Orders per Month",
        )),
        ("Products & Categories", ids(
            "Revenue by Category (Top 20)", "Items Sold by Category (Top 15)",
            "Avg Review Score by Category", "Avg Price by Category (R$)",
        )),
        ("Logistics & Delivery", ids(
            "Avg Delivery Time (Days)", "On-Time Delivery Rate %",
            "Avg Delivery Days by State", "Late Orders per Month",
            "Review Score Distribution", "Avg Delay Days by State",
        )),
    ]

    for title, chart_ids in dashboards:
        result = create_dashboard(title, chart_ids)
        if result:
            did, cids = result
            link_charts(did, cids)

    print(f"\n=== Done! http://localhost:8088/dashboard/list ===\n")

if __name__ == "__main__":
    main()
