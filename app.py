import os
import qrcode
import csv
from io import BytesIO, StringIO
from flask import Flask, render_template, request, redirect, url_for, send_file, make_response
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from datetime import datetime
import pytz


load_dotenv()
app = Flask(__name__)

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

@app.route('/qr_code')
def serve_qr():
    join_url = request.host_url + "join"
    qr = qrcode.make(join_url)
    buf = BytesIO()
    qr.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/join', methods=['GET', 'POST'])
def join_queue():
    if request.method == 'POST':
        name = request.form.get('name')
        conn = get_db_connection()
        if conn and name:
            cur = conn.cursor()
            
            # 1. Get the current time in Manila
            manila_tz = pytz.timezone('Asia/Manila')
            ph_time = datetime.now(manila_tz)
            
            # 2. Update the INSERT to include created_at
            cur.execute("""
                INSERT INTO que (customer_name, ticket_code, status, created_at) 
                VALUES (%s, %s, %s, %s)
            """, (name, 'MOBILE', 'Waiting', ph_time))
            
            conn.commit()
            cur.close()
            conn.close()
            return render_template('success.html', name=name)
    return render_template('join_form.html')


@app.route('/admin')
def admin():
    conn = get_db_connection()
    if not conn: return "DB Error", 200
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Added created_at to the selection
    cur.execute("SELECT id, customer_name, ticket_code, created_at FROM que WHERE status = 'Waiting' ORDER BY id ASC")
    waiting = cur.fetchall()
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

@app.route('/export_history')
def export_history():
    conn = get_db_connection()
    if not conn: return "DB Error", 500
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Added q.created_at to the export query
    cur.execute("""
        SELECT q.id as ticket_id, q.customer_name, c.name as counter_served_by, q.created_at
        FROM que q 
        JOIN counters c ON q.counter_id = c.id 
        WHERE q.status = 'Completed' 
        ORDER BY q.id ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Ticket ID', 'Customer Name', 'Served By Counter', 'Date Joined'])
    for row in rows:
        # Format the timestamp for the CSV
        date_str = row['created_at'].strftime('%Y-%m-%d %H:%M:%S') if row['created_at'] else "N/A"
        cw.writerow([row['ticket_id'], row['customer_name'], row['counter_served_by'], date_str])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=full_service_history.csv"
    output.headers["Content-type"] = "text/csv"
    return output

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
    app.run(host='0.0.0.0', port=8080)
