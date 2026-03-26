from flask import Flask, request, jsonify, send_from_directory, session
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import sqlite3
import os
import secrets
import requests as http_requests
from datetime import datetime, timedelta
 
load_dotenv()  # loads .env file when running locally
 
app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'skycast-local-dev-key')
 
app.config['MAIL_SERVER']         = 'smtp.gmail.com'
app.config['MAIL_PORT']           = 587
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USERNAME']       = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD']       = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME', '')
 
OWNER_EMAIL     = os.environ.get('OWNER_EMAIL', '')
ADMIN_PASSWORD  = os.environ.get('ADMIN_PASSWORD', 'skycast123')
WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY', '')
 
mail = Mail(app)
 
DB_PATH = 'skycast.db'
 
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        email TEXT NOT NULL, subject TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'medium', message TEXT NOT NULL,
        submitted_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unread',
        reply TEXT DEFAULT NULL, replied_at TEXT DEFAULT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
        created_at TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        city TEXT NOT NULL, country TEXT NOT NULL DEFAULT '',
        nickname TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id))''')
    for col in ['reply TEXT DEFAULT NULL', 'replied_at TEXT DEFAULT NULL']:
        try: c.execute(f'ALTER TABLE contacts ADD COLUMN {col}')
        except: pass
    conn.commit()
    conn.close()
    print("✅ Database ready.")
 
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
 
def email_owner(cid, name, email, subject, priority, message):
    plabel = {'low':'🟢 Low','medium':'🟡 Medium','high':'🔴 High'}.get(priority, priority)
    html = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0d0020;color:#e9d5ff;border-radius:16px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#6a00b8,#f59e0b);padding:24px 28px;">
        <h2 style="color:#fff;margin:0;">📬 New Message #{cid}</h2></div>
      <div style="padding:28px;">
        <p><strong style="color:#d8b4fe;">From:</strong> {name} &lt;{email}&gt;</p>
        <p><strong style="color:#d8b4fe;">Subject:</strong> {subject}</p>
        <p><strong style="color:#d8b4fe;">Priority:</strong> {plabel}</p>
        <div style="margin-top:16px;background:rgba(42,0,80,0.6);border:1px solid rgba(168,85,247,0.3);border-radius:10px;padding:16px;">
        <p style="color:#e9d5ff;line-height:1.75;margin:0;white-space:pre-line;">{message}</p></div>
      </div></div>"""
    msg = Message(subject=f"[SkyCast] {plabel}: {subject}", recipients=[OWNER_EMAIL], reply_to=email, html=html)
    mail.send(msg)
 
def email_user_reply(name, user_email, subject, original_message, reply_text):
    html = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;background:#0d0020;color:#e9d5ff;border-radius:16px;overflow:hidden;">
      <div style="background:linear-gradient(135deg,#6a00b8,#f59e0b);padding:24px 28px;">
        <h2 style="color:#fff;margin:0;">🌤️ Reply from Randhawa SkyCast</h2></div>
      <div style="padding:28px;">
        <p>Hi <strong style="color:#fcd34d;">{name}</strong>,</p>
        <div style="background:rgba(52,211,153,0.08);border:1px solid rgba(52,211,153,0.3);border-radius:12px;padding:16px;margin:1rem 0;">
        <p style="color:#a7f3d0;line-height:1.8;margin:0;white-space:pre-line;">{reply_text}</p></div>
        <p style="color:rgba(216,180,254,0.55);font-size:0.83rem;">Original: {original_message[:200]}...</p>
      </div></div>"""
    msg = Message(subject=f"[SkyCast] Re: {subject}", recipients=[user_email], html=html)
    mail.send(msg)
 
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')
 
@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)
 
@app.route('/contact', methods=['POST'])
def contact():
    data = request.get_json()
    for f in ['name','email','subject','message']:
        if not data.get(f,'').strip():
            return jsonify({'error': f'Missing: {f}'}), 400
    name     = data['name'].strip()[:100]
    email    = data['email'].strip()[:100]
    subject  = data['subject'].strip()[:200]
    priority = data.get('priority','medium')
    message  = data['message'].strip()[:2000]
    if priority not in ('low','medium','high'): priority = 'medium'
    conn = get_db()
    cur  = conn.execute(
        'INSERT INTO contacts (name,email,subject,priority,message,submitted_at,status) VALUES (?,?,?,?,?,?,?)',
        (name,email,subject,priority,message,datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'unread'))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    print(f"✅ Saved message #{cid} from {name}")
    try:
        email_owner(cid,name,email,subject,priority,message)
        print("✅ Owner notified")
    except Exception as e:
        print(f"⚠️ Owner email failed: {e}")
    return jsonify({'success':True,'id':cid}), 200
 
@app.route('/auth/signup', methods=['POST'])
def signup():
    data     = request.get_json()
    email    = data.get('email','').strip().lower()
    password = data.get('password','')
    if not email or not password:
        return jsonify({'error':'Email and password are required.'}), 400
    if len(password) < 8:
        return jsonify({'error':'Password must be at least 8 characters.'}), 400
    conn     = get_db()
    existing = conn.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error':'An account with this email already exists.'}), 409
    hashed = generate_password_hash(password)
    conn.execute('INSERT INTO users (email,password,created_at) VALUES (?,?,?)',
        (email,hashed,datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    user = conn.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    conn.close()
    session['user_id']    = user['id']
    session['user_email'] = user['email']
    print(f"✅ New user: {email}")
    return jsonify({'success':True,'email':email}), 200
 
@app.route('/auth/login', methods=['POST'])
def login():
    data     = request.get_json()
    email    = data.get('email','').strip().lower()
    password = data.get('password','')
    if not email or not password:
        return jsonify({'error':'Email and password are required.'}), 400
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user['password'], password):
        return jsonify({'error':'Incorrect email or password.'}), 401
    session['user_id']    = user['id']
    session['user_email'] = user['email']
    print(f"✅ Login: {email}")
    return jsonify({'success':True,'email':email}), 200
 
@app.route('/auth/direct-reset', methods=['POST'])
def direct_reset():
    data     = request.get_json()
    email    = data.get('email','').strip().lower()
    password = data.get('password','')
    if not email or not password:
        return jsonify({'error':'Email and password are required.'}), 400
    if len(password) < 8:
        return jsonify({'error':'Password must be at least 8 characters.'}), 400
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error':'No account found with this email address.'}), 404
    hashed = generate_password_hash(password)
    conn.execute('UPDATE users SET password=? WHERE email=?',(hashed,email))
    conn.commit()
    conn.close()
    print(f"✅ Password reset: {email}")
    return jsonify({'success':True}), 200
 
@app.route('/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id',None)
    session.pop('user_email',None)
    return jsonify({'success':True}), 200
 
@app.route('/auth/me')
def auth_me():
    if session.get('user_id'):
        return jsonify({'logged_in':True,'email':session.get('user_email')}), 200
    return jsonify({'logged_in':False}), 200
 
@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    if data.get('password') == ADMIN_PASSWORD:
        session['admin'] = True
        return jsonify({'success':True}), 200
    return jsonify({'error':'Wrong password'}), 401
 
@app.route('/admin/get-messages')
def admin_get_messages():
    if not session.get('admin'):
        return jsonify({'error':'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM contacts ORDER BY submitted_at DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200
 
@app.route('/admin/reply', methods=['POST'])
def admin_reply():
    if not session.get('admin'):
        return jsonify({'error':'Unauthorized'}), 401
    data  = request.get_json()
    cid   = data.get('id')
    reply = data.get('reply','').strip()
    if not cid or not reply:
        return jsonify({'error':'Missing id or reply'}), 400
    conn = get_db()
    row  = conn.execute('SELECT * FROM contacts WHERE id=?',(cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error':'Not found'}), 404
    conn.execute('UPDATE contacts SET reply=?,replied_at=?,status=? WHERE id=?',
        (reply,datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'replied',cid))
    conn.commit()
    conn.close()
    print(f"✅ Reply saved #{cid}")
    try:
        email_user_reply(row['name'],row['email'],row['subject'],row['message'],reply)
        print(f"✅ Reply emailed to {row['email']}")
    except Exception as e:
        print(f"⚠️ Reply email failed: {e}")
    return jsonify({'success':True}), 200
 
@app.route('/locations/get')
def get_locations():
    if not session.get('user_id'):
        return jsonify({'error':'Not logged in'}), 401
    conn = get_db()
    rows = conn.execute('SELECT * FROM locations WHERE user_id=? ORDER BY added_at ASC',
        (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows]), 200
 
@app.route('/locations/add', methods=['POST'])
def add_location():
    if not session.get('user_id'):
        return jsonify({'error':'Not logged in'}), 401
    data     = request.get_json()
    city     = data.get('city','').strip()
    country  = data.get('country','').strip()
    nickname = data.get('nickname','').strip()
    if not city:
        return jsonify({'error':'City name is required'}), 400
    conn     = get_db()
    existing = conn.execute('SELECT id FROM locations WHERE user_id=? AND LOWER(city)=LOWER(?)',
        (session['user_id'],city)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error':f'{city} is already in your list!'}), 409
    conn.execute('INSERT INTO locations (user_id,city,country,nickname,added_at) VALUES (?,?,?,?,?)',
        (session['user_id'],city,country,nickname,datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    loc = conn.execute('SELECT * FROM locations WHERE user_id=? ORDER BY id DESC LIMIT 1',
        (session['user_id'],)).fetchone()
    conn.close()
    print(f"✅ Location: {city} for user {session['user_id']}")
    return jsonify(dict(loc)), 200
 
@app.route('/locations/delete/<int:loc_id>', methods=['DELETE'])
def delete_location(loc_id):
    if not session.get('user_id'):
        return jsonify({'error':'Not logged in'}), 401
    conn = get_db()
    conn.execute('DELETE FROM locations WHERE id=? AND user_id=?',(loc_id,session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success':True}), 200
 
@app.route('/weather/get')
def get_weather():
    if not session.get('user_id'):
        return jsonify({'error':'Not logged in'}), 401
    city    = request.args.get('city','')
    country = request.args.get('country','')
    query   = f"{city},{country}" if country else city
 
    # Icon code → emoji mapping
    icon_map = {
        '01d':'☀️','01n':'🌙',
        '02d':'🌤️','02n':'🌤️',
        '03d':'☁️','03n':'☁️',
        '04d':'☁️','04n':'☁️',
        '09d':'🌧️','09n':'🌧️',
        '10d':'🌦️','10n':'🌦️',
        '11d':'⛈️','11n':'⛈️',
        '13d':'❄️','13n':'❄️',
        '50d':'🌫️','50n':'🌫️',
    }
    def to_emoji(code): return icon_map.get(code, '🌤️')
 
    # Wind direction
    def wind_dir(deg):
        dirs = ['N','NE','E','SE','S','SW','W','NW']
        return dirs[round(deg/45) % 8]
 
    try:
        curr_url = f"https://api.openweathermap.org/data/2.5/weather?q={query}&appid={WEATHER_API_KEY}&units=metric"
        curr = http_requests.get(curr_url, timeout=8).json()
        if curr.get('cod') != 200:
            return jsonify({'error': f"City not found: {city}"}), 404
 
        lat = curr['coord']['lat']
        lon = curr['coord']['lon']
 
        # Get forecast (5 day / 3 hour = 40 slots)
        fore = http_requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric",
            timeout=8).json()
 
        # Air quality
        air = http_requests.get(
            f"https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}",
            timeout=8).json()
        aqi = air['list'][0]['main']['aqi'] if air.get('list') else None
        aqi_labels = {1:'Good 😊',2:'Fair 🙂',3:'Moderate 😐',4:'Poor 😷',5:'Very Poor ☠️'}
 
        # Hourly — next 16 slots (covers 48 hours, shows full day graph)
        hourly = []
        for item in fore['list'][:16]:
            hourly.append({
                'time': item['dt_txt'][11:13],   # just the hour e.g. "14"
                'temp': round(item['main']['temp']),
                'icon': to_emoji(item['weather'][0]['icon']),
                'desc': item['weather'][0]['description'].title(),
                'pop':  round(item.get('pop', 0) * 100)  # precipitation %
            })
 
        # 7-day daily
        daily = {}
        for item in fore['list']:
            d = item['dt_txt'][:10]
            if d not in daily:
                daily[d] = {'date':d,'temps':[],'icons':[],'desc':item['weather'][0]['description'].title(),'pop':0}
            daily[d]['temps'].append(item['main']['temp'])
            daily[d]['icons'].append(to_emoji(item['weather'][0]['icon']))
            daily[d]['pop'] = max(daily[d]['pop'], round(item.get('pop',0)*100))
 
        seven_day = []
        for d in list(daily.values())[:7]:
            seven_day.append({
                'date': d['date'],
                'high': round(max(d['temps'])),
                'low':  round(min(d['temps'])),
                'icon': d['icons'][0],
                'desc': d['desc'],
                'pop':  d['pop']
            })
 
        deg = curr['wind'].get('deg', 0)
        return jsonify({
            'city':        curr['name'],
            'country':     curr['sys']['country'],
            'temp':        round(curr['main']['temp']),
            'feels_like':  round(curr['main']['feels_like']),
            'temp_min':    round(curr['main']['temp_min']),
            'temp_max':    round(curr['main']['temp_max']),
            'humidity':    curr['main']['humidity'],
            'pressure':    curr['main']['pressure'],
            'visibility':  round(curr.get('visibility', 0) / 1000, 1),
            'wind_speed':  round(curr['wind']['speed'] * 3.6, 1),
            'wind_deg':    deg,
            'wind_dir':    wind_dir(deg),
            'description': curr['weather'][0]['description'].title(),
            'icon':        to_emoji(curr['weather'][0]['icon']),
            'sunrise':     datetime.fromtimestamp(curr['sys']['sunrise']).strftime('%H:%M'),
            'sunset':      datetime.fromtimestamp(curr['sys']['sunset']).strftime('%H:%M'),
            'aqi':         aqi,
            'aqi_label':   aqi_labels.get(aqi, 'Unknown'),
            'hourly':      hourly,
            'seven_day':   seven_day,
        }), 200
 
    except Exception as e:
        print(f"⚠️ Weather error: {e}")
        return jsonify({'error': 'Failed to fetch weather data'}), 500
init_db()

if __name__ == '__main__':
    init_db()
    print("🌤  Randhawa SkyCast → http://localhost:5000")
    print(f"🔐  Admin panel    → http://localhost:5000/admin.html")
    print(f"🔑  Admin password → {ADMIN_PASSWORD}")
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
