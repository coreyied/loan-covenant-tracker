# export_data.py
import sqlite3
import csv

conn = sqlite3.connect("credit_warehouse.db")
cursor = conn.cursor()

# Query your analytical SQL window view
cursor.execute("SELECT * FROM v_credit_covenant_monitor")
rows = cursor.fetchall()
headers = [description[0] for description in cursor.description]

# Write to a CSV file
with open("credit_surveillance_output.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    writer.writerows(rows)

conn.close()
print("[SUCCESS] Data exported to 'credit_surveillance_output.csv'!")