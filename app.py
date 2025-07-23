from flask import Flask, request, render_template, send_file
from io import BytesIO
import base64
import re
import os
import sqlite3
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
from datetime import datetime, timedelta
from weasyprint import HTML

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default_secret")

UPLOAD_FOLDER = "output"
DB_PATH = "reports.db"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def convert_time_to_12hr(time_str):
    try:
        return datetime.strptime(time_str, "%H:%M").strftime("%I:%M %p")
    except ValueError:
        return time_str

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Service_Report_Number TEXT,
                Date TEXT,
                Company_Name TEXT,
                Company_Address TEXT,
                Company_Phone TEXT,
                Company_Email TEXT,
                technician TEXT,
                technician_email TEXT,
                technician_phone TEXT,
                Work_Order TEXT,
                Reason_For_Service TEXT,
                Customer_Asset_Number TEXT,
                Serial_Number TEXT,
                Incident TEXT,
                Work_Order_Type TEXT,
                Start_Time TEXT,
                End_Time TEXT,
                On_Site_Duration TEXT,
                Functional_Location_Address TEXT,
                products TEXT,
                service_tasks TEXT,
                customer_notes TEXT,
                signature BLOB,
                Customer_Name TEXT,
                photo BLOB,
                created_at TEXT
            )
        """)

def save_report_to_db(data, sig_bytes, photo_bytes):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO reports (
                Service_Report_Number, Date, Company_Name, Company_Address, Company_Phone, Company_Email,
                technician, technician_email, technician_phone, Work_Order, Reason_For_Service,
                Customer_Asset_Number, Serial_Number, Incident, Work_Order_Type,
                Start_Time, End_Time, On_Site_Duration, Functional_Location_Address,
                products, service_tasks, customer_notes, signature, Customer_Name, photo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('Service_Report_Number', ''), data.get('Date', ''), data.get('Company_Name', ''), data.get('Company_Address', ''), data.get('Company_Phone', ''),
            data.get('Company_Email', ''), data.get('technician', ''), data.get('technician_email', ''), data.get('technician_phone', ''), data.get('Work_Order', ''),
            data.get('Reason_For_Service', ''), data.get('Customer_Asset_Number', ''), data.get('Serial_Number', ''), data.get('Incident', ''),
            data.get('Work_Order_Type', ''), data.get('Start_Time', ''), data.get('End_Time', ''), data.get('On_Site_Duration', ''),
            data.get('Functional_Location_Address', ''), data.get('products', ''), data.get('service_tasks', ''), data.get('customer_notes', ''),
            sig_bytes, data.get('Customer_Name', ''), photo_bytes, datetime.now().isoformat()
        ))

def generate_pdf(data, sig_bytes, photo_bytes_list):
    signature_data = None
    if sig_bytes:
        signature_data = "data:image/png;base64," + base64.b64encode(sig_bytes).decode("utf-8")
        
    photo_data_list = [
        "data:image/png;base64," + base64.b64encode(photo).decode("utf-8")
        for photo in photo_bytes_list
    ]

    rendered_html = render_template(
        "report.html",
        data=data,
        signature_data=signature_data,
        photo_data_list=photo_data_list
    )

    filename = f"{data.get('Company_Name', 'report').replace(' ', '_')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    pdf_path = os.path.join(UPLOAD_FOLDER, filename)

    HTML(string=rendered_html).write_pdf(pdf_path)
    return pdf_path

def send_report_email(pdf_path, data):
    sender_email = data.get("technician_email") or os.getenv("EMAIL_FROM")
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("USE_TLS", "false").strip().lower() == "true"
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))

    recipients = list(filter(None, [
        data.get('Company_Email'),
        os.getenv("EMAIL_TO")
    ]))

    if not recipients:
        print("No recipient emails found, skipping email sending.")
        return

    msg = EmailMessage()
    msg['Subject'] = f"Service Report - {data.get('Company_Name', '')}"
    msg['From'] = sender_email
    msg['To'] = ", ".join(recipients)
    msg.set_content("Attached is your service report.\n\nBest regards,\nIPG Photonics")

    with open(pdf_path, 'rb') as f:
        msg.add_attachment(f.read(), maintype='application', subtype='pdf', filename=os.path.basename(pdf_path))

    try:
        if use_tls:
            with smtplib.SMTP(smtp_server, smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(smtp_username, smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as smtp:
                smtp.login(smtp_username, smtp_password)
                smtp.send_message(msg)
        print(f"Email sent successfully to: {', '.join(recipients)}")
    except Exception as e:
        print(f"Email send error: {e}")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        data = request.form.to_dict()
        data['Start_Time'] = convert_time_to_12hr(data.get('Start_Time', ''))
        data['End_Time'] = convert_time_to_12hr(data.get('End_Time', ''))

        def time_str_to_datetime(t):
            try:
                return datetime.strptime(t, "%I:%M %p")
            except ValueError:
                return None

        start_dt = time_str_to_datetime(data['Start_Time'])
        end_dt = time_str_to_datetime(data['End_Time'])

        if start_dt and end_dt:
            duration = end_dt - start_dt
            if duration.total_seconds() < 0:
                duration += timedelta(days=1)
            hours, remainder = divmod(duration.seconds, 3600)
            minutes = remainder // 60
            data['On_Site_Duration'] = f"{hours}h {minutes}m"
        else:
            data['On_Site_Duration'] = ""

        sig_data = re.sub('^data:image/.+;base64,', '', data.get('signature', ''))
        sig_bytes = base64.b64decode(sig_data) if sig_data else None

        photos = request.files.getlist("photos")
        photo_bytes_list = [p.read() for p in photos if p and p.filename != '']
        first_photo = photo_bytes_list[0] if photo_bytes_list else None

        init_db()
        save_report_to_db(data, sig_bytes, first_photo)

        pdf_path = generate_pdf(data, sig_bytes, photo_bytes_list)
        send_report_email(pdf_path, data)

        return send_file(pdf_path, as_attachment=True)

    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)














