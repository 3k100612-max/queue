import os
import qrcode
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load database credentials from .env file
load_dotenv()
app = Flask(__name__)

# --- DATABASE CONNECTION ---
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', '127.0.0.1'),
            database=os.getenv('DB_NAME', 'queue'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD'),
            connect_timeout=5
        )
        return conn
    except Exception as e:
        print(f"Database Error: {e}")
        return None

# --- PUBLIC DASHBOARD (Big Screen) ---
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

# --- QR CODE GENERATOR ---
@app.route('/qr_code')
def serve_qr():
    """Generates a QR code pointing to the /join page for mobile users."""
    join_url = request.host_url + "join"
    qr = qrcode.make(join_url)
    buf = BytesIO()
    qr.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

# --- MOBILE JOIN PAGE ---
@app.route('/join', methods=['GET', 'POST'])
def join_queue():
    if request.method == 'POST':
        name = request.form.get('name')
        conn = get_db_connection()
        if conn and name:
            cur = conn.cursor()
            cur.execute("INSERT INTO que (customer_name, ticket_code, status) VALUES (%s, %s, %s)", 
                        (name, 'MOBILE', 'Waiting'))
            conn.commit()
            cur.close()
            conn.close()
            return render_template('success.html', name=name)
    return render_template('join_form.html')

# --- ADMIN PANEL (Staff Management) ---
@app.route('/admin')
def admin():
    conn = get_db_connection()
    if not conn: return "DB Error", 200
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Get Waiting Pool
    cur.execute("SELECT id, customer_name, ticket_code FROM que WHERE status = 'Waiting' ORDER BY id ASC")
    waiting = cur.fetchall()
    
    # 2. Get All Counters and their current status
    cur.execute("""
        SELECT c.id as counter_id, c.name as counter_name, q.customer_name, q.id as queue_id
        FROM counters c 
        LEFT JOIN que q ON c.id = q.counter_id AND q.status = 'Serving' 
        ORDER BY c.id ASC
    """)
    activity = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template('admin.html', waiting=waiting, activity=activity)

@app.route('/add_counter', methods=['POST'])
def add_counter():
    name = request.form.get('counter_name')
    if name:
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO counters (name) VALUES (%s)", (name,))
            conn.commit()
            cur.close()
            conn.close()
    return redirect(url_for('admin'))

@app.route('/delete_counter/<int:counter_id>')
def delete_counter(counter_id):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM counters WHERE id = %s", (counter_id,))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('admin'))

@app.route('/assign/<int:counter_id>')
def assign_next(counter_id):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM que WHERE status = 'Waiting' ORDER BY id ASC LIMIT 1")
        next_p = cur.fetchone()
        if next_p:
            cur.execute("UPDATE que SET status = 'Serving', counter_id = %s WHERE id = %s", 
                        (counter_id, next_p[0]))
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
    # host 0.0.0.0 is required for Hostinger VPS access
    app.run(host='0.0.0.0', port=8080)
