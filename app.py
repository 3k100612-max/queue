import os
from flask import Flask, render_template, request, redirect, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load database credentials from .env file
load_dotenv()

app = Flask(__name__)

def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'queue'),
            user=os.getenv('DB_USER', 'postgres'),
            password=os.getenv('DB_PASSWORD')
        )
        return conn
    except Exception as e:
        print(f"❌ Database Connection Error: {e}")
        return None

# --- CUSTOMER VIEW ---
@app.route('/')
def index():
    conn = get_db_connection()
    if not conn: return "Database Connection Error", 500
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get Waiting List (Aliased to match HTML: person.id and person.name)
    cur.execute("""
        SELECT ticket_code as id, customer_name as name 
        FROM que 
        WHERE status = 'Waiting' 
        ORDER BY id ASC
    """)
    waiting_list = cur.fetchall()
    
    # Get Currently Serving (Joined with counters table)
    cur.execute("""
        SELECT q.ticket_code as id, q.customer_name as name, c.name as counter_name 
        FROM que q 
        JOIN counters c ON q.counter_id = c.id 
        WHERE q.status = 'Serving'
    """)
    serving_now = cur.fetchall()
    
    cur.close()
    conn.close()
    
    # Estimate 10 mins per person in line
    est_wait = len(waiting_list) * 10
    
    return render_template('index.html', queue=waiting_list, serving=serving_now, wait_time=est_wait)

# --- JOIN QUEUE ACTION ---
@app.route('/join', methods=['POST'])
def join_queue():
    name = request.form.get('name')
    if name:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Generate a ticket number based on current count
        cur.execute("SELECT COUNT(*) FROM que")
        count = cur.fetchone()[0]
        ticket_id = f"T-{101 + count}"
        
        cur.execute("INSERT INTO que (customer_name, ticket_code, status) VALUES (%s, %s, %s)", 
                    (name, ticket_id, 'Waiting'))
        conn.commit()
        cur.close()
        conn.close()
    return redirect(url_for('index'))

# --- ADMIN VIEW ---
@app.route('/admin')
def admin():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM counters ORDER BY id ASC")
    counters = cur.fetchall()
    
    cur.execute("SELECT id, customer_name, ticket_code FROM que WHERE status = 'Waiting' ORDER BY id ASC")
    waiting = cur.fetchall()
    
    cur.close()
    conn.close()
    return render_template('admin.html', counters=counters, waiting=waiting)

# --- CALL NEXT CUSTOMER (ADMIN ACTION) ---
@app.route('/assign/<int:counter_id>')
def assign_next(counter_id):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Find the next person in line
    cur.execute("SELECT id FROM que WHERE status = 'Waiting' ORDER BY id ASC LIMIT 1")
    next_person = cur.fetchone()
    
    if next_person:
        # Update their status to 'Serving' and link to this counter
        cur.execute("UPDATE que SET status = 'Serving', counter_id = %s WHERE id = %s", 
                    (counter_id, next_person[0]))
        conn.commit()
    
    cur.close()
    conn.close()
    return redirect(url_for('admin'))

# --- COMPLETE SERVICE (ADMIN ACTION) ---
@app.route('/complete/<int:que_id>')
def complete_service(que_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE que SET status = 'Completed' WHERE id = %s", (que_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    # debug=True will show you the exact error in the browser if something fails
    app.run(host='0.0.0.0', port=5000, debug=True)
