import os
import cv2
import time
import socket
import threading
import qrcode
from io import BytesIO
from pyzbar.pyzbar import decode
from flask import Flask, render_template, request, redirect, url_for, send_file
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load variables from .env
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
        print(f"Connection Error: {e}")
        return None

# --- UTILITIES ---
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# --- PHYSICAL QR SCANNER (Kiosk Mode) ---
def run_qr_scanner():
    """Background thread that uses the webcam to scan names into the queue."""
    cap = cv2.VideoCapture(0)
    last_scan_time = 0
    cooldown = 3 
    last_data = ""

    print("Scanner Thread: Active")
    while True:
        ret, frame = cap.read()
        if not ret: break

        for code in decode(frame):
            name = code.data.decode('utf-8')
            current_time = time.time()

            # Prevent rapid duplicate scans
            if name != last_data or (current_time - last_scan_time) > cooldown:
                conn = get_db_connection()
                if conn:
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO que (customer_name, ticket_code, status) VALUES (%s, %s, %s)",
                        (name, 'T-QR', 'Waiting')
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    print(f"Added to Queue via QR: {name}")
                    last_data = name
                    last_scan_time = current_time
                
                # Visual feedback on camera window
                pts = code.polygon
                if len(pts) == 4:
                    cv2.polylines(frame, [pts], True, (0, 255, 0), 3)

        cv2.imshow('Kiosk Scanner (Show QR to Camera)', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

# --- PUBLIC ROUTES ---

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
    return render_template('index.html', 
                           queue=waiting_list, 
                           serving=serving_now, 
                           wait_time=len(waiting_list)*10,
                           local_ip=get_local_ip())

@app.route('/qr_code')
def serve_qr():
    """Generates the QR code for phones to scan to open this website."""
    base_url = f"http://{get_local_ip()}:8080"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(base_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

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

# --- ADMIN ROUTES ---

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

# --- STARTUP ---

if __name__ == '__main__':
    # Start the OpenCV camera scanner in a background thread
    threading.Thread(target=run_qr_scanner, daemon=True).start()

    # Start Flask
    port = int(os.environ.get('PORT', 8080))
    # use_reloader=False is required to prevent the camera starting twice
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
