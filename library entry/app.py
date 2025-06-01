from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from datetime import datetime
import os
import sqlite3

app = Flask(__name__)
app.secret_key = os.urandom(24) # In a real app, use a fixed, strong secret key from env or config

DATABASE = 'library_system.db'

# --- Database Helper Functions ---
def get_db_connection():
    """Connects to the specific database. Creates it if it doesn't exist on first call."""
    conn = getattr(g, '_database', None)
    if conn is None:
        conn = g._database = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row # Access columns by name
    return conn

@app.teardown_appcontext
def close_connection(exception):
    """Closes the database again at the end of the request."""
    conn = getattr(g, '_database', None)
    if conn is not None:
        conn.close()

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    with app.app_context(): # Ensures we have an application context
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT,
                course TEXT,
                section TEXT,
                date_in TEXT,
                time_in TEXT,
                time_out TEXT
            )
        ''')
        db.commit()
        print("Database initialized and 'logs' table ensured (called from app.py module scope).")

# --- IMPORTANT: Initialize DB when app module is loaded ---
# This ensures that when 'app.py' is imported (e.g., by wsgi.py or Gunicorn),
# the database initialization logic runs.
init_db()
# --- END OF IMPORTANT CHANGE ---

# --- User Routes ---
@app.route('/')
def index():
    return render_template('index.html', now=datetime.utcnow())

@app.route('/process', methods=['POST'])
def process_action():
    action_type = request.form.get('action_type')
    user_id = request.form.get('user_id')
    current_dt = datetime.now() # Use current_dt for consistency
    current_date = current_dt.strftime("%Y-%m-%d")
    current_time = current_dt.strftime("%H:%M:%S")

    if not user_id:
        flash('User ID is required.', 'error')
        return redirect(url_for('index'))

    db = get_db_connection()
    cursor = db.cursor()

    if action_type == 'enter':
        name = request.form.get('name')
        course = request.form.get('course')
        section = request.form.get('section')

        if not all([name, course, section]):
            flash('Name, Course, and Section are required for entry.', 'error')
            return redirect(url_for('index'))

        # Check if user is already marked as 'IN' without an 'OUT'
        cursor.execute("SELECT * FROM logs WHERE user_id = ? AND time_out IS NULL ORDER BY id DESC LIMIT 1", (user_id,))
        existing_active_entry = cursor.fetchone()

        if existing_active_entry:
            flash(f'User ID {user_id} ({existing_active_entry["name"]}) is already marked as IN. Please check out first.', 'error')
            return redirect(url_for('index'))

        cursor.execute('''
            INSERT INTO logs (user_id, name, course, section, date_in, time_in)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, name, course, section, current_date, current_time))
        db.commit()
        flash(f'User {name} ({user_id}) entered successfully at {current_time} on {current_date}.', 'success')

    elif action_type == 'out':
        # Find the most recent "IN" record for this user_id that hasn't been "OUT" yet
        cursor.execute('''
            SELECT id FROM logs 
            WHERE user_id = ? AND time_in IS NOT NULL AND time_out IS NULL 
            ORDER BY date_in DESC, time_in DESC, id DESC
            LIMIT 1
        ''', (user_id,))
        entry_to_update = cursor.fetchone()
        
        if entry_to_update:
            entry_id = entry_to_update['id']
            cursor.execute("UPDATE logs SET time_out = ? WHERE id = ?", (current_time, entry_id))
            db.commit()
            flash(f'User ID {user_id} checked out successfully at {current_time}.', 'success')
        else:
            flash(f'No active entry record found for User ID {user_id} to check out, or already checked out.', 'error')
            
    return redirect(url_for('index'))

# --- Admin Routes ---
@app.route('/admin')
def admin_login():
    if 'admin_logged_in' in session:
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html', now=datetime.utcnow())

@app.route('/admin/login', methods=['POST'])
def admin_login_post():
    username = request.form.get('username')
    password = request.form.get('password')

    if username == 'admin' and password == 'admin': # Simple admin credentials
        session['admin_logged_in'] = True
        flash('Admin login successful!', 'success')
        return redirect(url_for('admin_dashboard'))
    else:
        flash('Invalid admin credentials.', 'error')
        return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_logged_in' not in session:
        flash('Please log in to access the dashboard.', 'error')
        return redirect(url_for('admin_login'))
    
    db = get_db_connection()
    cursor = db.cursor()
    
    search_query = request.args.get('q', '').strip()
    query_params = []
    
    base_sql = "SELECT * FROM logs"
    where_clauses = []

    if search_query:
        search_term_like = f"%{search_query}%"
        fields_to_search = ["user_id", "name", "course", "section", "date_in"]
        
        if search_query.isdigit():
            where_clauses.append("id = ?")
            query_params.append(int(search_query))

        for field in fields_to_search:
            where_clauses.append(f"{field} LIKE ?")
            query_params.append(search_term_like)
        
        if where_clauses:
            base_sql += " WHERE (" + " OR ".join(where_clauses) + ")"
            
    base_sql += " ORDER BY id DESC"
    
    cursor.execute(base_sql, query_params)
    records = cursor.fetchall()
    
    return render_template('admin_dashboard.html', 
                           records=records, 
                           now=datetime.utcnow(), 
                           search_query=search_query)

@app.route('/admin/delete_log/<int:log_id>', methods=['POST'])
def delete_log(log_id):
    if 'admin_logged_in' not in session:
        flash('Authentication required.', 'error')
        return redirect(url_for('admin_login'))

    try:
        db = get_db_connection()
        cursor = db.cursor()
        cursor.execute("DELETE FROM logs WHERE id = ?", (log_id,))
        db.commit()
        if cursor.rowcount > 0:
            flash(f'Log entry #{log_id} deleted successfully.', 'success')
        else:
            flash(f'Log entry #{log_id} not found or already deleted.', 'warning')
    except sqlite3.Error as e:
        flash(f'Database error: {e}', 'error')
    return redirect(url_for('admin_dashboard', q=request.args.get('q', '')))


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    # init_db() # This is now called at the module level above, so not strictly needed here.
                # However, it doesn't hurt to leave it if you also run app.py directly for dev.
    # For local development if you run "python app.py":
    local_port = int(os.environ.get("APP_PY_PORT", 5001)) # Use a distinct port for clarity
    app.run(debug=True, host="0.0.0.0", port=local_port)
