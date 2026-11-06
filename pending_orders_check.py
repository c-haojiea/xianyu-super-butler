import sqlite3
import sys

db_path = sys.argv[1]
con = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True)
count = con.execute(
    "select count(*) from orders where order_status=?", ("pending_ship",)
).fetchone()[0]
print(count)
con.close()
