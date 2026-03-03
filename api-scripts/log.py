# log.py — shared logging for the Microsoft 365 Tenant Pipeline
from datetime import datetime

def _ts(): return datetime.now().strftime("%H:%M:%S")
def info(msg):  print(f"[{_ts()}] INFO   {msg}")
def ok(msg):    print(f"[{_ts()}] OK     {msg}")
def warn(msg):  print(f"[{_ts()}] WARN   {msg}")
def err(msg):   print(f"[{_ts()}] ERROR  {msg}")
