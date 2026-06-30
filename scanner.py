import cv2
import os
import time
from pyzbar.pyzbar import decode
import psycopg2
from dotenv import load_dotenv

# Load database credentials from your existing .env
load_dotenv()

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
        print(f"Database connection failed: {e}")
        return None

def add_to_queue(name):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            # Inserting with 'T-QR' to distinguish scanned entries
            cur.execute(
                "INSERT INTO que (customer_name, ticket_code, status) VALUES (%s, %s, %s)",
                (name, 'T-QR', 'Waiting')
            )
            conn.commit()
            print(f"Successfully added {name} to the queue.")
            cur.close()
            conn.close()
            return True
        except Exception as e:
            print(f"Error inserting to DB: {e}")
    return False

def run_scanner():
    # Initialize webcam
    cap = cv2.VideoCapture(0)
    print("QR Scanner Active. Press 'q' to quit.")
    
    last_scan_time = 0
    cooldown = 3  # Seconds to wait before allowing the same/next scan
    last_data = ""

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Decode QR codes in the frame
        for code in decode(frame):
            current_data = code.data.decode('utf-8')
            current_time = time.time()

            # Prevent double-scanning the same code instantly
            if current_data != last_data or (current_time - last_scan_time) > cooldown:
                print(f"Detected QR: {current_data}")
                
                if add_to_queue(current_data):
                    last_data = current_data
                    last_scan_time = current_time
                    
                    # Visual feedback: Draw a green box around the QR
                    pts = code.polygon
                    if len(pts) == 4:
                        cv2.polylines(frame, [pts], True, (0, 255, 0), 3)

        # Show the camera feed
        cv2.imshow('Queue QR Scanner', frame)

        # Press 'q' to exit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    run_scanner()
