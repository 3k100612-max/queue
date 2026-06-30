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

load_dotenv()
app = Flask(__name__)

# --- DATABASE LOGIC ---

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

# --- UTILITY LOGIC ---

def get_local_ip():
    """Gets the local IP address to create a scannable Join Link."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

# --- QR SCANNER LOGIC (OPENCV) ---

def run_qr_scanner():
    """Runs in a separate thread to scan QR codes via webcam."""
    cap = cv2.VideoCapture(0)
    last_scan_time = 0
    cooldown = 3 
    last_data = ""

    print("--- Camera Scanner Started ---")
    while True:
        ret, frame = cap.read()
        if not ret: break

        for code in decode(frame):
            name = code.data.decode('utf-8')
            current_time = time.time()

            # Prevent duplicate scans within the cooldown period
            if name != last_data or (current_time - last_scan_time) > cooldown:
                print(f"QR Scanned: {name}")
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
                    last_data = name
                    last_scan_time = current_time
                
                # Draw a green box in the preview window
                pts = code.polygon
                if len(pts) == 4:
                    cv2.polylines(frame, [pts], True, (0, 255, 0), 3)

        cv2.imshow('Kiosk QR Scanner (Press Q to Close Window)', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

# --- FLASK ROUTES ---

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
    
    # Pass local_ip so the UI can show the URL next to the QR code
    return render_template('index.html', 
                           queue=waiting_list, 
                           serving=serving_now, 
                           wait_time=len(waiting_list)*10,
                           local_ip=get_local_ip())

@app.route('/qr_code')
def serve_qr():
    """Generates the 'Join Link' QR code image dynamically."""
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

# ... [Keep all your other admin routes (admin, assign, complete, etc.) here] ...

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

# [Remaining admin routes: create_counter, edit_counter, delete_counter, assign_next, complete_serving]

if __name__ == '__main__':
    # Start the QR Scanner in a separate background thread
    scanner_thread = threading.Thread(target=run_qr_scanner, daemon=True)
    scanner_thread.start()

    # Start the Flask Web Server
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
