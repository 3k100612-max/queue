from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
import uuid

app = Flask(__name__)

# Data storage
queue_data = []
serving_now = None

@app.route('/')
def index():
    # Calculate estimated wait (10 mins per person in line)
    est_wait = len(queue_data) * 10
    return render_template('index.html', queue=queue_data, serving=serving_now, wait_time=est_wait)

@app.route('/join', methods=['POST'])
def join():
    name = request.form.get('name')
    if name:
        ticket = {
            'id': str(uuid.uuid4())[:4].upper(), # Generates a short ID like 'A1B2'
            'name': name,
            'arrival_time': datetime.now().strftime('%H:%M'),
            'status': 'Waiting'
        }
        queue_data.append(ticket)
    return redirect(url_for('index'))

@app.route('/admin')
def admin():
    return render_template('admin.html', queue=queue_data, serving=serving_now)

@app.route('/call_next')
def call_next():
    global serving_now
    if queue_data:
        serving_now = queue_data.pop(0)
        serving_now['status'] = 'Being Served'
    return redirect(url_for('admin'))

@app.route('/complete')
def complete():
    global serving_now
    serving_now = None
    return redirect(url_for('admin'))

if __name__ == '__main__':
    # Using port 5001 to avoid common conflicts
    app.run(debug=True, port=5001)
