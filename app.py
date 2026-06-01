from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import uuid
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- DATABASE CONNECTION (SECURE) ---
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "queue"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD")
        )
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

# --- PUBLIC VIEW ---
@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "Database Connection Error", 500
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM queue WHERE status = 'Waiting' ORDER BY id ASC")
    waiting_list = cur.fetchall()
    
    cur.execute("""
        SELECT q.ticket_code, q.customer_name, c.name as counter_name 
        FROM queue q 
        JOIN counters c ON q.counter_id = c.id 
        WHERE q.status = 'Serving'
    """)
    serving_now = cur.fetchall()
    
    est_wait = len(waiting_list) * 10
    cur.close()
    conn.close()
    return render_template('index.html', queue=waiting_list, serving=serving_now, wait_time=est_wait)

# --- CUSTOMER: JOIN QUEUE ---
@app.route('/join', methods=['POST'])
def join():
    name = request.form.get('name')
    if name:
        ticket_code = str(uuid.uuid4())[:4].upper()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO queue (ticket_code, customer_name, status) VALUES (%s, %s, %s)",
            (ticket_code, name, 'Waiting')
        )
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('index'))

# --- ADMIN/STAFF DASHBOARD ---
@app.route('/admin')
def admin():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM counters ORDER BY name ASC")
    counters = cur.fetchall()
    cur.execute("SELECT * FROM queue WHERE status = 'Waiting' ORDER BY id ASC")
    waiting_list = cur.fetchall()
    cur.execute("""
        SELECT c.id as counter_id, c.name as counter_name, 
               q.id as queue_id, q.ticket_code, q.customer_name
        FROM counters c
        LEFT JOIN queue q ON c.id = q.counter_id AND q.status = 'Serving'
        ORDER BY c.name ASC
    """)
    counter_activity = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin.html', counters=counters, waiting=waiting_list, activity=counter_activity)

# --- ADMIN: CREATE COUNTERS ---
@app.route('/create_counter', methods=['POST'])
def create_counter():
    counter_name = request.form.get('counter_name')
    if counter_name:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO counters (name) VALUES (%s)", (counter_name,))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('admin'))

# --- STAFF: ASSIGN NEXT USER TO COUNTER ---
@app.route('/assign_next/<int:counter_id>')
def assign_next(counter_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM queue WHERE status = 'Waiting' ORDER BY id ASC LIMIT 1")
    next_user = cur.fetchone()
    if next_user:
        cur.execute(
            "UPDATE queue SET status = 'Serving', counter_id = %s WHERE id = %s",
            (counter_id, next_user[0])
        )
        conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin'))

# --- STAFF: COMPLETE SERVING ---
@app.route('/complete_serving/<int:queue_id>')
def complete_serving(queue_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE queue SET status = 'Completed' WHERE id = %s", (queue_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    # Try port 5000 if 5001 is giving the Gateway error
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
