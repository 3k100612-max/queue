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

# Global Timezone Setting
MANILA_TZ = pytz.timezone('Asia/Manila')

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
            ph_time = datetime.now(MANILA_TZ)
            cur.execute("""
                INSERT INTO que (customer_name, ticket_code, status, created_at) 
                VALUES (%s, %s, %s, %s) RETURNING id
            """, (name, 'MOBILE', 'Waiting', ph_time))
            new_ticket_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            return redirect(url_for('view_status', ticket_id=new_ticket_id))
    return render_template('join_form.html')

@app.route('/status/<int:ticket_id>')
def view_status(ticket_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT customer_name, status, counter_id FROM que WHERE id = %s", (ticket_id,))
    user = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM que WHERE status = 'Waiting' AND id < %s", (ticket_id,))
    ahead = cur.fetchone()['count']
    counter_name = "Counter"
    if user and user['counter_id']:
        cur.execute("SELECT name FROM counters WHERE id = %s", (user['counter_id'],))
        res = cur.fetchone()
        if res: counter_name = res['name']
    cur.close()
    conn.close()
    return render_template('status.html', user=user, ahead=ahead, counter_name=counter_name)

@app.route('/admin')
def admin():
    conn = get_db_connection()
    if not conn: return "DB Error", 200
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT id, customer_name, ticket_code, created_at FROM que WHERE status = 'Waiting' ORDER BY id ASC")
    waiting = cur.fetchall()
    for row in waiting:
        if row['created_at']:
            local_time = row['created_at'].astimezone(MANILA_TZ)
            row['formatted_time'] = local_time.strftime('%I:%M %p')
        else:
            row['formatted_time'] = "N/A"
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
    # This now exports from the ARCHIVE table as you requested
    cur.execute("SELECT * FROM que_history ORDER BY archived_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)
    if rows:
        cw.writerow(rows[0].keys()) # Dynamic headers
        for row in rows:
            cw.writerow(row.values())
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=full_history_{datetime.now().date()}.csv"
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
        # First, detach any active tickets so we don't get a Foreign Key error
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

@app.route('/safe_reset', methods=['POST'])
def safe_reset():
    conn = get_db_connection()
    if not conn: return "Database Offline", 500
    cur = conn.cursor()
    
    try:
        # 1. Archive to history table
        # We use 'id' from que as 'original_id' in history
        cur.execute("""
            INSERT INTO que_history (original_id, customer_name, ticket_code, status, counter_id, created_at)
            SELECT id, customer_name, ticket_code, status, counter_id, created_at FROM que
        """)
        
        # 2. Reset the active table
        cur.execute("TRUNCATE TABLE que RESTART IDENTITY CASCADE")
        
        # COMMIT the database changes now so they are saved even if file writing fails
        conn.commit()
        
        # 3. Attempt physical CSV Backup (Optional)
        try:
            if not os.path.exists('backups'): 
                os.makedirs('backups')
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backups/queue_backup_{timestamp}.csv"
            
            # Note: Since we truncated 'que' above, we'd need to fetch 
            # from 'que_history' if we want the data we just moved.
            cur.execute("SELECT * FROM que_history WHERE archived_at >= NOW() - INTERVAL '1 minute'")
            rows = cur.fetchall()
            
            if rows:
                with open(filename, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([desc[0] for desc in cur.description])
                    writer.writerows(rows)
        except Exception as file_err:
            print(f"File Backup Warning (Skipped): {file_err}")
            # We don't return error here because the DB archive already succeeded

    except Exception as e:
        conn.rollback()
        print(f"Database Reset Error: {e}")
        return f"Database Error: {e}. Check if 'que_history' table exists.", 500
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
