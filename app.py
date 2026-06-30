import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# --- DATABASE CONNECTION ---
def get_db_connection():
    host = os.getenv('DB_HOST', '127.0.0.1')
    db = os.getenv('DB_NAME', 'queue')
    user = os.getenv('DB_USER', 'postgres')
    pw = os.getenv('DB_PASSWORD')
    try:
        conn = psycopg2.connect(host=host, database=db, user=user, password=pw, connect_timeout=5)
        return conn
    except Exception as e:
        print(f"Database Error: {e}")
        return None

# --- PUBLIC DASHBOARD ---
@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "<h1>Database Offline</h1>", 200
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Get Waiting List
    cur.execute("SELECT id, customer_name as name FROM que WHERE status = 'Waiting' ORDER BY id ASC")
    waiting_list = cur.fetchall()
    # Get Currently Serving
    cur.execute("""
        SELECT q.id, q.customer_name as name, c.name as counter_name 
        FROM que q JOIN counters c ON q.counter_id = c.id WHERE q.status = 'Serving'
    """)
    serving_now = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', queue=waiting_list, serving=serving_now, wait_time=len(waiting_list)*10)

# --- KIOSK SCANNER (For the tablet at the entrance) ---
@app.route('/kiosk')
def kiosk_page():
    return render_template('kiosk.html')

@app.route('/api/scan', methods=['POST'])
def api_scan():
    """Endpoint called by the Kiosk tablet when a QR is scanned."""
    data = request.json
    name = data.get('name')
    conn = get_db_connection()
    if conn and name:
        cur = conn.cursor()
        # 'T-QR' identifies this person was scanned at the kiosk
        cur.execute("INSERT INTO que (customer_name, ticket_code, status) VALUES (%s, %s, %s)", (name, 'T-QR', 'Waiting'))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "message": f"Added {name}"}), 200
    return jsonify({"status": "error"}), 400

# --- ADMIN PANEL ---
@app.route('/admin')
def admin():
    conn = get_db_connection()
    if not conn: return "DB Error", 200
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, customer_name, ticket_code FROM que WHERE status = 'Waiting' ORDER BY id ASC")
    waiting = cur.fetchall()
    cur.execute("""
        SELECT c.id as counter_id, c.name as counter_name, q.ticket_code, q.customer_name, q.id as queue_id
        FROM counters c LEFT JOIN que q ON c.id = q.counter_id AND q.status = 'Serving' ORDER BY c.id ASC
    """)
    activity = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin.html', waiting=waiting, activity=activity)

@app.route('/assign/<int:counter_id>')
def assign_next(counter_id):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM que WHERE status = 'Waiting' ORDER BY id ASC LIMIT 1")
        next_p = cur.fetchone()
        if next_p:
            cur.execute("UPDATE que SET status = 'Serving', counter_id = %s WHERE id = %s", (counter_id, next_p[0]))
            conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('admin'))

@app.route('/complete/<int:queue_id>')
def complete_serving(queue_id):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("UPDATE que SET status = 'Completed' WHERE id = %s", (queue_id,))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
