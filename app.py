import os
from flask import Flask, render_template, request, redirect, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

def get_db_connection():
    host = os.getenv('DB_HOST', '127.0.0.1')
    db = os.getenv('DB_NAME', 'queue')
    user = os.getenv('DB_USER', 'postgres')
    pw = os.getenv('DB_PASSWORD')
    try:
        conn = psycopg2.connect(host=host, database=db, user=user, password=pw, connect_timeout=5)
        return conn
    except Exception as e:
        return None

@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "<h1>Database Offline</h1>", 200
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, customer_name as name FROM que WHERE status = 'Waiting' ORDER BY id ASC")
    waiting_list = cur.fetchall()
    cur.execute("""
        SELECT q.id, q.customer_name as name, c.name as counter_name 
        FROM que q JOIN counters c ON q.counter_id = c.id WHERE q.status = 'Serving'
    """)
    serving_now = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('index.html', queue=waiting_list, serving=serving_now, wait_time=len(waiting_list)*10)

@app.route('/join', methods=['POST'])
def join_queue():
    name = request.form.get('name')
    conn = get_db_connection()
    if conn and name:
        cur = conn.cursor()
        cur.execute("INSERT INTO que (customer_name, ticket_code, status) VALUES (%s, %s, %s)", (name, 'T-NEW', 'Waiting'))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('index'))

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

@app.route('/create_counter', methods=['POST'])
def create_counter():
    name = request.form.get('counter_name')
    conn = get_db_connection()
    if conn and name:
        cur = conn.cursor()
        cur.execute("INSERT INTO counters (name) VALUES (%s)", (name,))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('admin'))

@app.route('/edit_counter/<int:counter_id>', methods=['POST'])
def edit_counter(counter_id):
    new_name = request.form.get('new_name')
    conn = get_db_connection()
    if conn and new_name:
        cur = conn.cursor()
        cur.execute("UPDATE counters SET name = %s WHERE id = %s", (new_name, counter_id))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('admin'))

@app.route('/delete_counter/<int:counter_id>')
def delete_counter(counter_id):
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        cur.execute("UPDATE que SET counter_id = NULL WHERE counter_id = %s", (counter_id,))
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
