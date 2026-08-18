import cv2
from PIL import Image, ImageTk
import tkinter as tk

# Test Pillow
print("Pillow imported OK")

# Test camera
cap = cv2.VideoCapture(1)
if not cap.isOpened():
    print("❌ Camera 0 not opened")
else:
    ret, frame = cap.read()
    if ret:
        print(f"✅ Camera OK, frame shape: {frame.shape}")
        # Test conversion
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        print("✅ Image conversion OK")
    else:
        print("❌ Camera read failed")
    cap.release()

# Test Tkinter
root = tk.Tk()
root.title("Test")
label = tk.Label(root, text="Hello")
label.pack()
root.after(1000, root.destroy)
root.mainloop()
print("✅ Tkinter OK")