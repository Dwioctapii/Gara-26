import json

def baca():
    with open('data.json', 'r') as f:
        return json.load(f)

def tulis(data):
    with open('data.json', 'w') as f:
        json.dump(data, f)

# Init pertama kali
try:
    baca()
except:
    tulis({'nilai': 0})